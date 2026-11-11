"""Somente em VM descartável, com Galaxy nativo gerenciado, systemd e banco vazio."""
import os
from pathlib import Path
import pwd
import tempfile
from unittest.mock import patch
from biosuite import backups
from biosuite.backup_backends import NativeBackend, DATA, DB
from biosuite.backup_format import verify
from biosuite.operations import OperationError, capture

if os.environ.get('BIOSUITE_BACKUP_SMOKE') != '1':
    raise SystemExit('Defina BIOSUITE_BACKUP_SMOKE=1 somente em uma VM descartável.')
b=NativeBackend()
if any(int(b.sql('SELECT count(*) FROM '+table)) for table in ('dataset','galaxy_user','job')):
    raise SystemExit('Banco não está vazio; teste recusado.')
b.start()
b.sql("INSERT INTO dataset (id,state,deleted,purged,purgable,uuid,file_size,total_size,create_time,update_time) VALUES (900001,'ok',false,false,true,'00000000000000000000000000900001',5,5,now(),now())")
account=pwd.getpwnam(DB)
file=DATA/'datasets/000/900/dataset_900001.dat'
file.parent.mkdir(parents=True,exist_ok=True)
os.chown(file.parent,account.pw_uid,account.pw_gid)
os.chown(file.parent.parent,account.pw_uid,account.pw_gid)
def write(value):
    file.write_text(value);os.chmod(file,0o600);os.chown(file,account.pw_uid,account.pw_gid)
write('ACGT\n')
parent=Path(tempfile.mkdtemp(prefix='biosuite-native-backups-',dir=b.base))
source=backups.create('native',parent);verify(source)
assert backups.rehearse('native',source)['database_restore']=='verified'
write('CHANGED\n');b.sql('UPDATE dataset SET file_size=8 WHERE id=900001')
result=backups.restore('native',source,parent);verify(Path(result['safety_backup']))
assert file.read_text()=='ACGT\n'
assert b.sql('SELECT file_size FROM dataset WHERE id=900001').strip()=='5'
code="""from galaxy.config import GalaxyAppConfiguration
from galaxy.util.properties import load_app_properties
from galaxy.objectstore import build_object_store_from_config
from galaxy.model import Dataset
import uuid
props=load_app_properties(config_file='/etc/biosuite/galaxy.yml');props['root']='/opt/biosuite-galaxy/galaxy'
store=build_object_store_from_config(GalaxyAppConfiguration(**props))
obj=Dataset(id=900001,uuid=uuid.UUID('00000000000000000000000000900001'))
assert open(store.get_filename(obj)).read() == 'ACGT'+chr(10)
"""
capture(['runuser','-u',DB,'--','env','PYTHONPATH=/opt/biosuite-galaxy/galaxy/lib',
         '/opt/biosuite-galaxy/galaxy/.venv/bin/python','-c',code],cwd='/')
assert b.running()
write('LATEST\n');b.sql('UPDATE dataset SET file_size=7 WHERE id=900001')
with patch.object(NativeBackend,'promote',side_effect=OperationError('injected promotion failure')):
    try:backups.restore('native',source,parent)
    except OperationError as error:assert 'injected' in str(error)
    else:raise AssertionError('Falha injetada não ocorreu')
assert file.read_text()=='LATEST\n'
assert b.sql('SELECT file_size FROM dataset WHERE id=900001').strip()=='7'
assert b.running() and not b.journal.exists()
b.sql('DELETE FROM dataset WHERE id=900001');file.unlink();b.stop()
print('Backup/restauração/rollback nativos com PostgreSQL e systemd reais: OK. Backups privados em',parent)
