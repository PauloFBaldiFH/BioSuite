"""Backups consistentes, ensaio de restauração, rollback e cópia rclone."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import tempfile

from biosuite.backup_backends import backend, DB
from biosuite.backup_format import extract_tar, inspect_tar, seal, sync_directory, verify, write_private
from biosuite.native import RELEASE
from biosuite.operations import OperationError, capture, lock, run_logged


def _reporter(callback):
    def report(message):
        try:
            callback(message)
        except (OSError, RuntimeError):
            # Perder o terminal não pode alterar o resultado da recuperação.
            pass
    return report


def timestamp():
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def default_directory(mode):
    from biosuite import containers
    return Path('/var/backups/biosuite') if mode == 'native' else containers.BASE / 'backups'


def _destination(parent, adapter):
    parent = Path(parent).expanduser().resolve()
    roots = getattr(adapter, 'roots', {})
    for source in roots.values():
        if parent == source or source in parent.parents:
            raise OperationError('O destino de backup não pode ficar dentro dos arquivos copiados.')
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    return parent


def _staging_parent(adapter):
    # /tmp pode ser tmpfs (padrão no Debian 13); dados científicos precisam de disco.
    return _destination(os.environ.get('BIOSUITE_BACKUP_STAGING') or adapter.base, adapter)


def list_local(directory):
    parent = Path(directory).expanduser()
    if not parent.is_dir():
        return []
    rows = []
    for path in sorted(parent.glob('backup-*'), reverse=True)[:200]:
        manifest = path / 'manifest.json'
        if path.is_symlink() or not path.is_dir() or manifest.is_symlink() or not manifest.is_file() or manifest.stat().st_size > 65536:
            continue
        try:
            info = json.loads(manifest.read_text())
            if info.get('format') != 'biosuite-backup-v1':
                continue
            rows.append({'path':str(path.resolve()),'mode':info['mode'],'created_utc':info['created_utc'],
                         'galaxy_release':info['galaxy_release'],'integrity':'not_checked'})
        except (ValueError, KeyError, TypeError):
            continue
    return rows


def _snapshot(adapter, parent, output):
    parent = _destination(parent, adapter)
    name = 'backup-' + timestamp() + '-' + secrets.token_hex(4)
    pending = parent / ('.incomplete-' + name)
    pending.mkdir(mode=0o700)
    try:
        if shutil.disk_usage(parent).free < adapter.estimate() + 512 * 1024 * 1024:
            raise OperationError('Espaço insuficiente para o backup completo.')
        output('Copiando PostgreSQL com Galaxy parado…')
        metadata = {'mode': adapter.mode, 'created_utc': datetime.now(timezone.utc).isoformat(),
                    'galaxy_release': RELEASE, 'pg_major': adapter.pg_major(),
                    'database_bytes': int(adapter.sql('SELECT pg_database_size(current_database())')),
                    'port': adapter.port}
        adapter.dump(pending / 'database.dump')
        inventory = json.loads(adapter.sql("SELECT coalesce(json_agg(json_build_object('name',name,'owner',owner,'revision',installed_changeset_revision,'status',status)), '[]'::json) FROM tool_shed_repository"))
        write_private(pending / 'inventory.json', inventory)
        metadata['repository_count'] = len(inventory)
        output('Copiando dados, configurações e ferramentas; esta etapa pode demorar…')
        adapter.snapshot_files(pending, metadata)
        for path in pending.glob('*.tar'):
            if path.name != 'image.tar':
                inspect_tar(path, data=path.name == 'data.tar')
        output('Conferindo checksums dos arquivos…')
        seal(pending, metadata)
        verify(pending)
        final = parent / name
        pending.rename(final)
        sync_directory(parent)
        output('Backup completo: ' + str(final))
        return final
    except BaseException:
        # Uma pasta incompleta nunca recebe nome de backup completo.
        output('Cópia incompleta mantida para diagnóstico: ' + str(pending))
        raise


@contextmanager
def maintenance(mode, output=print):
    initial = backend(mode)
    with lock(initial.lock):
        adapter = backend(mode)
        if adapter.journal.exists():
            raise OperationError('Existe uma manutenção interrompida. Confira o diário privado: ' + str(adapter.journal))
        was_running = adapter.running()
        write_private(adapter.journal, {'operation': 'backup', 'phase': 'preparing', 'was_running': was_running})
        stopped = False
        keep_stopped = False
        try:
            adapter.ensure_database()
            adapter.assert_idle()
            if was_running:
                output('Parando Galaxy para obter um ponto consistente…')
                stopped = True
                adapter.stop()
            adapter.assert_idle()
            state = {'keep_stopped': False, 'was_running': was_running}
            yield adapter, state
            keep_stopped = state['keep_stopped']
        except BaseException:
            # O restaurador registra keep_stopped no diário antes de qualquer mutação.
            try:
                keep_stopped = json.loads(adapter.journal.read_text()).get('keep_stopped', False)
            except (OSError, ValueError):
                keep_stopped = True
            raise
        finally:
            if not keep_stopped:
                if stopped and was_running:
                    output('Reabrindo Galaxy…')
                    adapter.start()
                adapter.finish_database()
                adapter.journal.unlink(missing_ok=True)
            else:
                output('Galaxy mantido parado; confira o diário e o backup de segurança antes de retomar.')


def create(mode, directory=None, output=print):
    output = _reporter(output)
    with maintenance(mode, output) as (adapter, _):
        return _snapshot(adapter, directory or default_directory(mode), output)


def _stage(folder, adapter, work, output):
    for source in getattr(adapter, 'roots', {}).values():
        if work == source or source in work.parents:
            raise OperationError('Staging temporário não pode ficar dentro dos dados da instalação.')
    info = verify(folder)
    if info['mode'] != adapter.mode or info['galaxy_release'] != RELEASE or info['pg_major'] != adapter.pg_major():
        raise OperationError('Modo, release Galaxy ou versão principal PostgreSQL incompatível.')
    adapter.compatible(info)
    sizes = {name: inspect_tar(Path(folder) / name, data=name == 'data.tar') for name in info['payloads'] if name.endswith('.tar') and name != 'image.tar'}
    adapter.check_space(info, sizes)
    required = sum(sizes.values())
    required = required * 3 + info['database_bytes'] * 2 + info['payloads'].get('image.tar', {}).get('bytes', 0) * 2
    if shutil.disk_usage(work).free < required + 512 * 1024 * 1024:
        raise OperationError(f'São necessários aproximadamente {required / 1024**3 + 0.5:.1f} GiB livres no staging para uma restauração segura.')
    output('Verificando e extraindo cópia isolada…')
    for name in info['payloads']:
        shutil.copyfile(Path(folder) / name, work / name)
        os.chmod(work / name, 0o600)
    write_private(work / 'manifest.json', info)
    verify(work)  # Também detecta alteração concorrente do backup durante a cópia.
    for name in info['payloads']:
        if name.endswith('.tar') and name != 'image.tar':
            extract_tar(work / name, work / name.removesuffix('.tar'))
            (work / name).unlink()
    adapter.prepare_files(work, info)
    return info


def _rehearse(adapter, work, output):
    name = 'biosuite_verify_' + secrets.token_hex(8)
    adapter.temp_database(name)
    try:
        output('Restaurando dump em banco temporário; o banco ativo não será substituído nesta etapa…')
        adapter.restore_dump(work / 'database.dump', name)
    except BaseException:
        adapter.drop_database(name)
        raise
    return name


def rehearse(mode, folder, output=print):
    """Valida arquivos e restaura SQL em outro banco, sem parar/substituir Galaxy."""
    output = _reporter(output)
    initial = backend(mode)
    with lock(initial.lock):
        adapter = backend(mode)
        if adapter.journal.exists():
            raise OperationError('Resolva a manutenção pendente antes do ensaio.')
        adapter.ensure_database()
        try:
            with tempfile.TemporaryDirectory(prefix='.biosuite-rehearsal-', dir=_staging_parent(adapter)) as temporary:
                work = Path(temporary)
                info = _stage(folder, adapter, work, output)
                name = _rehearse(adapter, work, output)
                adapter.drop_database(name)
            return {'integrity': 'verified', 'database_restore': 'verified', 'mode': mode,
                    'galaxy_release': info['galaxy_release'], 'live_data_changed': False}
        finally:
            adapter.finish_database()


def restore(mode, folder, safety_directory=None, output=print):
    output = _reporter(output)
    folder = Path(folder).expanduser().resolve()
    with maintenance(mode, output) as (adapter, state):
        # Todos os testes precedem a substituição do destino.
        with tempfile.TemporaryDirectory(prefix='.biosuite-restore-', dir=_staging_parent(adapter)) as temporary:
            work = Path(temporary)
            info = _stage(folder, adapter, work, output)
            verified_db = _rehearse(adapter, work, output)
            old_db = 'biosuite_old_' + secrets.token_hex(8)
            token = secrets.token_hex(8)
            moves = None
            attempted_files = False
            committed = False
            old_renamed = new_renamed = False
            safety = None
            try:
                output('Criando backup de segurança obrigatório antes da substituição…')
                safety = _snapshot(adapter, safety_directory or default_directory(mode), output)
                write_private(adapter.journal, {'operation': 'restore', 'keep_stopped': True,
                              'phase': 'promoting', 'safety_backup': str(safety),
                              'old_database': old_db, 'verified_database': verified_db, 'token': token,
                              'was_running': state['was_running']})
                adapter.rename_database(DB, old_db)
                old_renamed = True
                adapter.rename_database(verified_db, DB)
                new_renamed = True
                attempted_files = True
                moves = adapter.promote(work, token, info)
                output('Iniciando temporariamente para conferir Galaxy após a restauração…')
                adapter.start()
                adapter.stop()
                # Após este ponto, falhas de notificação/limpeza nunca desfazem dados já validados.
                cleanup = adapter.base / ('cleanup-' + token + '.json')
                write_private(cleanup, {'old_database': old_db, 'token': token, 'safety_backup': str(safety)})
                write_private(adapter.journal, {'operation': 'restore', 'phase': 'complete', 'keep_stopped': False,
                              'was_running': state['was_running'], 'old_database': old_db, 'token': token,
                              'safety_backup': str(safety)})
                committed = True
                try:
                    adapter.discard(moves)
                    adapter.drop_database(old_db)
                    cleanup.unlink()
                except Exception:
                    output('Restauração válida; limpeza do rollback pendente. Consulte: ' + str(cleanup))
                moves = None
                old_renamed = False
                output('Restauração concluída; backup anterior preservado: ' + str(safety))
                return {'restored': True, 'safety_backup': str(safety), 'mode': mode}
            except BaseException:
                if committed:
                    output('Dados restaurados e validados; limpeza posterior interrompida. Consulte o registro cleanup em ' + str(adapter.base))
                    raise
                rollback_ok = True
                try:
                    adapter.stop()
                    if attempted_files:
                        adapter.recover_files(token)
                    if new_renamed:
                        adapter.rename_database(DB, verified_db)
                    if old_renamed:
                        adapter.rename_database(old_db, DB)
                    adapter.drop_database(verified_db)
                except BaseException:
                    rollback_ok = False
                write_private(adapter.journal, {'operation': 'restore', 'phase': 'rolled_back' if rollback_ok else 'recovery_required',
                              'keep_stopped': not rollback_ok, 'was_running': state['was_running'], 'safety_backup': str(safety),
                              'old_database': old_db, 'verified_database': verified_db, 'token': token})
                output('Rollback concluído.' if rollback_ok else 'Rollback incompleto. Não inicie Galaxy; use o backup de segurança e o diário.')
                raise


def remotes():
    return [line for line in capture(['rclone', 'listremotes']).splitlines() if line.endswith(':')]


def _remote(value):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*:[A-Za-z0-9_./-]*', value) or '..' in value.partition(':')[2].split('/') or '//' in value:
        raise OperationError('Informe um remote rclone configurado e um caminho simples, sem .. ou credenciais.')
    name = value.split(':', 1)[0] + ':'
    if name not in remotes():
        raise OperationError('Remote não encontrado no rclone deste usuário.')
    return value.rstrip('/')


def upload(folder, remote, output=print):
    output = _reporter(output)
    folder = Path(folder).expanduser().resolve()
    info = verify(folder)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,160}', folder.name):
        raise OperationError('Nome da pasta de backup inválido para transporte.')
    args = [part for name in ['manifest.json', *info['payloads']] for part in ('--include', '/' + name)]
    base = _remote(remote)
    target = base + ('' if base.endswith(':') else '/') + folder.name
    log = folder / 'rclone-upload.log'
    run_logged(['rclone', 'copy', str(folder), target, '--immutable', *args], log, output)
    run_logged(['rclone', 'check', str(folder), target, '--one-way', '--download', *args], log, output)
    return {'copied': True, 'readback_verified': True, 'destination': target}


def download(remote, directory, output=print):
    output = _reporter(output)
    remote = _remote(remote)
    parent = Path(directory).expanduser().resolve()
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    pending = Path(tempfile.mkdtemp(prefix='.incoming-', dir=parent))
    log = pending / 'rclone-download.log'
    includes = ['manifest.json', 'database.dump', 'data.tar', 'code.tar', 'config.tar', 'image.tar', 'inventory.json']
    args = [part for name in includes for part in ('--include', '/' + name)]
    run_logged(['rclone', 'copy', remote, str(pending), '--immutable', *args], log, output)
    verify(pending)
    final = parent / ('backup-downloaded-' + timestamp() + '-' + secrets.token_hex(4))
    pending.rename(final)
    return {'downloaded': str(final), 'integrity': 'verified', 'database_restore': 'not_tested'}
