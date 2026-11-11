import io
import contextlib
import json
import os
import subprocess
from pathlib import Path
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from biosuite import backups
from biosuite.backup_backends import NativeBackend, DockerBackend, DB
from biosuite.backup_format import inspect_tar, seal, verify, extract_tar
from biosuite.operations import OperationError


class FixtureBackend(NativeBackend):
    """Filesystem real; estados PostgreSQL/serviço simulados apenas nos testes unitários."""
    def __init__(self, root):
        self.base = root / 'base'; self.base.mkdir()
        self.roots = {'data': root / 'data', 'code': self.base / 'galaxy'}
        self.lock = self.base / 'install.lock'; self.journal = self.base / 'maintenance.json'
        self.log = self.base / 'backups.log'; self.port = 8080
        self.databases = {DB: {'value': 'original'}}
        self.active = True; self.active_jobs = False; self.health_failure = False
        self.started = self.stopped = self.rehearsals = 0
    def sql(self, statement, database=DB, admin=False):
        if 'json_agg' in statement: return '[]'
        return '100'
    def pg_major(self): return 17
    def assert_idle(self):
        if self.active_jobs: raise OperationError('Jobs pendentes')
    def running(self): return self.active
    def stop(self): self.stopped += 1; self.active = False
    def start(self):
        self.started += 1; self.active = True
        if self.health_failure:
            self.health_failure = False
            raise OperationError('Falha HTTP simulada')
    def ensure_database(self): pass
    def estimate(self): return 100
    def check_space(self, info, sizes): pass
    def dump(self, path): path.write_text(json.dumps(self.databases[DB]))
    def temp_database(self, name): self.databases[name] = {}
    def drop_database(self, name): self.databases.pop(name, None)
    def rename_database(self, source, target): self.databases[target] = self.databases.pop(source)
    def restore_dump(self, path, name):
        self.rehearsals += 1; self.databases[name] = json.loads(path.read_text())


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.adapter = FixtureBackend(self.root)
        self.data = self.adapter.roots['data']; self.code = self.adapter.roots['code']
        self.config = self.root / 'config'; self.config.mkdir()
        (self.data / 'datasets').mkdir(parents=True); self.code.mkdir()
        (self.data / 'datasets/sample.dat').write_text('original dataset')
        (self.code / 'tool').write_text('original wrapper')
        (self.config / 'galaxy.yml').write_text(json.dumps({'gravity':{'gunicorn':{'bind':'127.0.0.1:8080'}},
            'galaxy':{'data_dir':str(self.data),'file_path':str(self.data/'datasets'),'tool_dependency_dir':str(self.data/'dependencies'),'database_connection':'postgresql:///biosuitegalaxy?host=/var/run/postgresql','install_database_connection':'postgresql:///biosuitegalaxy?host=/var/run/postgresql'}}))
        (self.config / 'job_conf.xml').write_text('<job_conf><plugins><plugin load="galaxy.jobs.runners.local:LocalJobRunner"/></plugins></job_conf>')
        (self.config / 'connection-private').write_text('preserve this independent identity')
        self.parent = self.root / 'backups'
        for target,value in [('biosuite.backups.backend',self.adapter),('biosuite.backup_backends.DATA',self.data),
                             ('biosuite.backup_backends.CONFIG',self.config)]:
            p=patch(target,return_value=value) if target.endswith('.backend') else patch(target,value)
            p.start(); self.addCleanup(p.stop)
        p=patch('biosuite.backup_backends.pwd.getpwnam',return_value=SimpleNamespace(pw_uid=os.getuid(),pw_gid=os.getgid()))
        p.start();self.addCleanup(p.stop)
    def create(self): return backups.create('native',self.parent,output=lambda _:None)
    def mutate(self):
        (self.data/'datasets/sample.dat').write_text('newer dataset')
        (self.code/'tool').write_text('newer wrapper')
        self.adapter.databases[DB]={'value':'newer'}
    def test_round_trip_tests_sql_preserves_safety_copy_and_independent_connection(self):
        source=self.create(); self.assertTrue(self.adapter.active)
        self.assertEqual(source.stat().st_mode & 0o777,0o700)
        self.assertTrue(all((source/name).stat().st_mode & 0o777 == 0o600 for name in verify(source)['payloads']))
        self.mutate()
        result=backups.restore('native',source,self.parent,output=lambda _:None)
        self.assertEqual((self.data/'datasets/sample.dat').read_text(),'original dataset')
        self.assertEqual((self.code/'tool').read_text(),'original wrapper')
        self.assertEqual(self.adapter.databases[DB],{'value':'original'})
        safety=Path(result['safety_backup']);self.assertEqual(json.loads((safety/'database.dump').read_text()),{'value':'newer'})
        self.assertEqual((self.config/'connection-private').read_text(),'preserve this independent identity')
        self.assertEqual(set(self.adapter.databases),{DB});self.assertTrue(self.adapter.active)
        self.assertFalse(self.adapter.journal.exists())
    def test_disconnected_progress_output_does_not_interrupt_restoration(self):
        source=self.create();self.mutate()
        def disconnected(_):raise BrokenPipeError('terminal closed')
        result=backups.restore('native',source,self.parent,output=disconnected)
        self.assertTrue(result['restored'])
        self.assertEqual(self.adapter.databases[DB],{'value':'original'})
        self.assertEqual((self.data/'datasets/sample.dat').read_text(),'original dataset')

    def test_interruption_after_commit_never_removes_restored_database(self):
        source=self.create();self.mutate()
        with patch.object(self.adapter,'discard',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                backups.restore('native',source,self.parent,output=lambda _:None)
        self.assertEqual(self.adapter.databases[DB],{'value':'original'})
        self.assertEqual((self.data/'datasets/sample.dat').read_text(),'original dataset')
        self.assertTrue(self.adapter.active)
        self.assertTrue(list(self.adapter.base.glob('cleanup-*.json')))

    def test_health_failure_restores_previous_database_and_files(self):
        source=self.create();self.mutate();self.adapter.health_failure=True
        with self.assertRaisesRegex(OperationError,'HTTP'):
            backups.restore('native',source,self.parent,output=lambda _:None)
        self.assertEqual((self.data/'datasets/sample.dat').read_text(),'newer dataset')
        self.assertEqual((self.code/'tool').read_text(),'newer wrapper')
        self.assertEqual(self.adapter.databases[DB],{'value':'newer'})
        self.assertEqual(set(self.adapter.databases),{DB});self.assertTrue(self.adapter.active)
        self.assertFalse(self.adapter.journal.exists())
    def test_failure_after_file_promotion_recovers_even_without_returned_move_record(self):
        source=self.create();self.mutate();original=self.adapter.promote
        def fail_after_promotion(*args):
            original(*args)
            raise OperationError('after promotion')
        with patch.object(self.adapter,'promote',side_effect=fail_after_promotion):
            with self.assertRaisesRegex(OperationError,'after promotion'):
                backups.restore('native',source,self.parent,output=lambda _:None)
        self.assertEqual((self.data/'datasets/sample.dat').read_text(),'newer dataset')
        self.assertEqual(self.adapter.databases[DB],{'value':'newer'})
        self.assertEqual(set(self.adapter.databases),{DB});self.assertTrue(self.adapter.active)

    def test_database_rename_failure_rolls_back_and_drops_candidate(self):
        source=self.create();self.mutate();original=self.adapter.rename_database
        def fail_candidate(source,target):
            if source.startswith('biosuite_verify_'):
                raise OperationError('rename failure')
            original(source,target)
        with patch.object(self.adapter,'rename_database',side_effect=fail_candidate):
            with self.assertRaisesRegex(OperationError,'rename failure'):
                backups.restore('native',source,self.parent,output=lambda _:None)
        self.assertEqual(self.adapter.databases[DB],{'value':'newer'})
        self.assertEqual(set(self.adapter.databases),{DB});self.assertTrue(self.adapter.active)

    def test_integrity_failure_never_replaces_live_data(self):
        source=self.create();self.mutate();(source/'data.tar').write_bytes(b'corrupt')
        with self.assertRaisesRegex(OperationError,'Checksum'):
            backups.restore('native',source,self.parent,output=lambda _:None)
        self.assertEqual(self.adapter.rehearsals,0)
        self.assertEqual((self.data/'datasets/sample.dat').read_text(),'newer dataset')
        self.assertTrue(self.adapter.active)
    def test_active_jobs_refuse_before_stopping(self):
        self.adapter.active_jobs=True
        with self.assertRaisesRegex(OperationError,'Jobs'):
            self.create()
        self.assertEqual(self.adapter.stopped,0);self.assertTrue(self.adapter.active)
        self.assertFalse(self.adapter.journal.exists())
    def test_rehearsal_does_not_stop_or_replace_live_state(self):
        source=self.create();self.mutate();stops=self.adapter.stopped
        result=backups.rehearse('native',source,output=lambda _:None)
        self.assertEqual(result['database_restore'],'verified')
        self.assertEqual(self.adapter.stopped,stops)
        self.assertEqual(self.adapter.databases[DB],{'value':'newer'})
        self.assertEqual(set(self.adapter.databases),{DB})
    def test_rehearsal_and_restore_work_without_default_temporary_filesystem(self):
        source=self.create();self.mutate()
        with patch('tempfile.tempdir',str(self.root/'unavailable-system-temp')):
            self.assertEqual(backups.rehearse('native',source,output=lambda _:None)['database_restore'],'verified')
            result=backups.restore('native',source,self.parent,output=lambda _:None)
        self.assertTrue(result['restored'])
        self.assertEqual((self.data/'datasets/sample.dat').read_text(),'original dataset')
        self.assertEqual(self.adapter.databases[DB],{'value':'original'})
        self.assertFalse(list(self.adapter.base.glob('.biosuite-rehearsal-*')))
        self.assertFalse(list(self.adapter.base.glob('.biosuite-restore-*')))
    def test_requested_staging_is_private_and_removed_after_use(self):
        source=self.create();target=self.root/'large-disk'
        original=self.adapter.prepare_files
        def inspect(work,metadata):
            self.assertEqual(work.parent,target)
            self.assertEqual(work.stat().st_mode & 0o777,0o700)
            original(work,metadata)
        with patch.dict(os.environ,{'BIOSUITE_BACKUP_STAGING':str(target)}),patch.object(self.adapter,'prepare_files',side_effect=inspect):
            backups.rehearse('native',source,output=lambda _:None)
            backups.restore('native',source,self.parent,output=lambda _:None)
        self.assertEqual(list(target.iterdir()),[])
    def test_staging_inside_data_is_refused_without_replacing_live_data(self):
        source=self.create();self.mutate()
        with patch.dict(os.environ,{'BIOSUITE_BACKUP_STAGING':str(self.data/'staging')}):
            with self.assertRaisesRegex(OperationError,'dentro'):
                backups.restore('native',source,self.parent,output=lambda _:None)
        self.assertEqual((self.data/'datasets/sample.dat').read_text(),'newer dataset')
        self.assertEqual(self.adapter.databases[DB],{'value':'newer'})
        self.assertTrue(self.adapter.active)
    def test_failed_snapshot_keeps_incomplete_folder_and_resumes(self):
        with patch.object(self.adapter,'snapshot_files',side_effect=OperationError('disk failure')):
            with self.assertRaises(OperationError): self.create()
        self.assertFalse(list(self.parent.glob('backup-*')))
        self.assertTrue(list(self.parent.glob('.incomplete-*')))
        self.assertTrue(self.adapter.active);self.assertFalse(self.adapter.journal.exists())
    def test_interrupted_maintenance_blocks_another_operation(self):
        self.adapter.journal.write_text('{}')
        with self.assertRaisesRegex(OperationError,'interrompida'):self.create()
        self.assertEqual(self.adapter.stopped,0)
    def test_destination_inside_source_is_refused(self):
        with self.assertRaisesRegex(OperationError,'dentro'):
            backups.create('native',self.data/'backups',output=lambda _:None)
    def test_stopped_installation_is_health_checked_and_left_stopped(self):
        source=self.create();self.adapter.active=False;self.mutate();starts=self.adapter.started
        backups.restore('native',source,self.parent,output=lambda _:None)
        self.assertGreater(self.adapter.started,starts);self.assertFalse(self.adapter.active)
    def test_rclone_upload_is_immutable_only_includes_backup_files_and_checks_readback(self):
        source=self.create()
        with patch('biosuite.backups.remotes',return_value=['private:']),patch('biosuite.backups.run_logged') as run:
            result=backups.upload(source,'private:copies',output=lambda _:None)
        first=run.call_args_list[0].args[0];second=run.call_args_list[1].args[0]
        self.assertEqual(first[:2],['rclone','copy']);self.assertIn('--immutable',first)
        self.assertIn('--include',first);self.assertNotIn('sync',first)
        self.assertIn('--download',second);self.assertTrue(result['readback_verified'])
        with patch('biosuite.backups.remotes',return_value=['private:']):
            with self.assertRaises(OperationError):backups._remote('private:../escape')


class ArchiveSafetyTests(unittest.TestCase):
    def test_rejects_traversal_devices_duplicate_entries_and_symlink_parents(self):
        cases=[('traversal',[('../escape','file','')]),('device',[('dev','device','')]),
               ('duplicate',[('same','file',''),('same','file','')]),
               ('link-parent',[('outside','symlink','/tmp'),('outside/escape','file','')]),
               ('hardlink',[('escape','hardlink','../outside')])]
        with tempfile.TemporaryDirectory() as folder:
            for label,items in cases:
                path=Path(folder)/label
                with tarfile.open(path,'w') as tar:
                    for name,kind,target in items:
                        member=tarfile.TarInfo(name)
                        if kind=='file':member.size=1;tar.addfile(member,io.BytesIO(b'x'))
                        else:
                            member.type={'device':tarfile.CHRTYPE,'symlink':tarfile.SYMTYPE,'hardlink':tarfile.LNKTYPE}[kind]
                            member.linkname=target;tar.addfile(member)
                with self.subTest(label=label),self.assertRaises(OperationError):inspect_tar(path)
    def test_safe_extraction_preserves_runtime_symlink_without_following_it(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=root/'archive.tar'
            with tarfile.open(path,'w') as tar:
                m=tarfile.TarInfo('bin/python');m.type=tarfile.SYMTYPE;m.linkname='/usr/bin/python3';tar.addfile(m)
                m=tarfile.TarInfo('data');m.size=4;m.mode=0o6777;m.mtime=1234567890;tar.addfile(m,io.BytesIO(b'data'))
            extract_tar(path,root/'stage')
            self.assertEqual(os.readlink(root/'stage/bin/python'),'/usr/bin/python3')
            self.assertEqual((root/'stage/data').read_bytes(),b'data')
            self.assertEqual((root/'stage/data').stat().st_mode & 0o7000,0)
            self.assertEqual(int((root/'stage/data').stat().st_mtime),1234567890)


class NativeMaintenanceGateTests(unittest.TestCase):
    def test_launcher_refuses_pending_maintenance_without_volatile_authorization(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);runtime=root/'run';base=root/'base';base.mkdir()
            launcher=base/'start'
            launcher.write_text('#!/usr/bin/env bash\nexport GALAXY_CONFIG_FILE=/etc/biosuite/galaxy.yml\nexec sh run.sh --skip-wheels\n')
            (base/'run.sh').write_text('exit 0\n')
            adapter=NativeBackend.__new__(NativeBackend);adapter.base=base;adapter.journal=base/'maintenance.json'
            with patch('biosuite.backup_backends.RUNTIME',runtime):adapter._guard_launcher()
            def run():return subprocess.run(['bash',str(launcher)],cwd=base,capture_output=True).returncode
            self.assertEqual(run(),0)
            adapter.journal.write_text('{}');self.assertEqual(run(),75)
            (runtime/'allow-start').write_text('authorized');self.assertEqual(run(),0)
            (runtime/'allow-start').unlink();self.assertEqual(run(),75)
    def test_unknown_launcher_is_not_rewritten(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'start').write_text('custom launcher')
            adapter=NativeBackend.__new__(NativeBackend);adapter.base=root;adapter.journal=root/'maintenance.json'
            with patch('biosuite.backup_backends.RUNTIME',root/'runtime'):
                with self.assertRaisesRegex(OperationError,'personalizado'):adapter._guard_launcher()
            self.assertEqual((root/'start').read_text(),'custom launcher')


class BackupCommandTests(unittest.TestCase):
    def test_mutating_cli_actions_require_explicit_confirmation(self):
        from biosuite.cli import main
        actions=[['create'],['restore','--source','/tmp/backup'],['rehearse','--source','/tmp/backup'],
                 ['upload','--source','/tmp/backup','--remote','test:copies'],
                 ['download','--remote','test:copies','--directory','/tmp/downloads']]
        with patch('biosuite.backups.backend') as factory,patch('biosuite.backups.run_logged') as run:
            for args in actions:
                with self.subTest(action=args[0]),contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
                    main(['backups',*args])
            factory.assert_not_called();run.assert_not_called()

    def test_docker_staging_preserves_target_password_and_source_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);base=root/'base';base.mkdir();(base/'db-password').write_text('NEW-FAKE-PASSWORD')
            config=root/'stage/data/config';config.mkdir(parents=True)
            old={'galaxy':{'data_dir':'/data','file_path':'/data/datasets','tool_dependency_dir':'/data/dependencies',
                           'database_connection':'postgresql://OLD-FAKE','install_database_connection':'postgresql://OLD-FAKE',
                           'id_secret':'source-identity'}}
            (config/'galaxy.yml').write_text(json.dumps(old))
            adapter=DockerBackend.__new__(DockerBackend);adapter.base=base
            adapter.prepare_files(root/'stage',{})
            new=json.loads((config/'galaxy.yml').read_text())['galaxy']
            self.assertEqual(new['id_secret'],'source-identity')
            self.assertIn('NEW-FAKE-PASSWORD',new['database_connection'])
            self.assertEqual(new['install_database_connection'],new['database_connection'])
