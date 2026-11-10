"""Somente em instância Docker BioSuite DESCARTÁVEL e vazia.

BIOSUITE_BACKUP_SMOKE=1 BIOSUITE_DOCKER_HOME=... PYTHONPATH=src python3 tests/backups-docker-smoke.py
Cria um dataset fictício, backup, mutação, restauração e falha injetada para rollback.
"""
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from biosuite import backups, containers
from biosuite.backup_backends import DockerBackend
from biosuite.backup_format import verify
from biosuite.operations import capture, OperationError

if os.environ.get('BIOSUITE_BACKUP_SMOKE') != '1' or not os.environ.get('BIOSUITE_DOCKER_HOME'):
    raise SystemExit('Teste restrito a instância descartável; defina BIOSUITE_BACKUP_SMOKE=1 e BIOSUITE_DOCKER_HOME.')

base = DockerBackend()
base.ensure_database()
if int(base.sql('SELECT count(*) FROM dataset')) or int(base.sql('SELECT count(*) FROM galaxy_user')) or int(base.sql('SELECT count(*) FROM job')):
    base.finish_database()
    raise SystemExit('A instância não está vazia; teste recusado.')
base.start()
base.sql("INSERT INTO dataset (id,state,deleted,purged,purgable,uuid,file_size,total_size,create_time,update_time) VALUES (900001,'ok',false,false,true,'00000000000000000000000000900001',5,5,now(),now())")

def write_dataset(value):
    code = 'from pathlib import Path;p=Path("/data/datasets/000/900/dataset_900001.dat");p.parent.mkdir(parents=True,exist_ok=True);p.write_text(' + repr(value) + ')'
    capture(containers.compose('exec','-T','galaxy','runuser','-u','galaxy','--','python3','-c',code))

def read_dataset():
    return capture(containers.compose('exec','-T','galaxy','cat','/data/datasets/000/900/dataset_900001.dat'))

write_dataset('ACGT\n')
parent=Path(tempfile.mkdtemp(prefix='biosuite-real-backups-'))
print('Cópias de teste em:',parent,flush=True)
source=backups.create('docker',parent)
verify(source)
assert DockerBackend().running()
print('Backup real e checksums: OK',flush=True)
result=backups.rehearse('docker',source)
assert result['database_restore']=='verified'
write_dataset('CHANGED\n');DockerBackend().sql('UPDATE dataset SET file_size=8 WHERE id=900001')
capture(containers.compose('exec','-T','galaxy','touch','/data/datasets/after-backup-only.dat'))
result=backups.restore('docker',source,parent)
verify(Path(result['safety_backup']))
assert read_dataset()=='ACGT\n'
assert DockerBackend().sql('SELECT file_size FROM dataset WHERE id=900001').strip()=='5'
capture(containers.compose('exec','-T','galaxy','test','!','-e','/data/datasets/after-backup-only.dat'))
code = """from galaxy.config import GalaxyAppConfiguration
from galaxy.util.properties import load_app_properties
from galaxy.objectstore import build_object_store_from_config
from galaxy.model import Dataset
import uuid
config=GalaxyAppConfiguration(**load_app_properties(config_file='/data/config/galaxy.yml'))
store=build_object_store_from_config(config)
obj=Dataset(id=900001,uuid=uuid.UUID('00000000000000000000000000900001'))
assert open(store.get_filename(obj)).read() == 'ACGT'+chr(10)
"""
b=DockerBackend()
capture(['docker','run','--rm','--network','none','--user','1000:1000','--volumes-from',b.container+':ro',
         '--entrypoint','env',b.image,'PYTHONPATH=/galaxy/lib','/galaxy/.venv/bin/python','-c',code])
assert DockerBackend().running()
print('Restauração real: registro PostgreSQL + arquivo recuperados; arquivo posterior removido; API/HTML saudáveis.',flush=True)
# Uma falha antes de promover arquivos deve desfazer as renomeações reais dos bancos.
write_dataset('LATEST\n');DockerBackend().sql('UPDATE dataset SET file_size=7 WHERE id=900001')
with patch.object(DockerBackend,'promote',side_effect=OperationError('injected promotion failure')):
    try:
        backups.restore('docker',source,parent)
    except OperationError as error:
        assert 'injected' in str(error)
    else:
        raise AssertionError('Falha injetada não foi propagada')
assert read_dataset()=='LATEST\n'
assert DockerBackend().sql('SELECT file_size FROM dataset WHERE id=900001').strip()=='7'
assert DockerBackend().running()
assert not (containers.BASE/'maintenance.json').exists()
assert DockerBackend().sql("SELECT count(*) FROM pg_database WHERE datname LIKE 'biosuite_verify_%' OR datname LIKE 'biosuite_old_%'").strip()=='0'
print('Rollback PostgreSQL real preservou o estado anterior e reabriu Galaxy. Nenhum banco temporário ficou pendente.',flush=True)
# Deixa a instância novamente vazia, sem apagar backups completos.
DockerBackend().sql('DELETE FROM dataset WHERE id=900001')
capture(containers.compose('exec','-T','galaxy','rm','/data/datasets/000/900/dataset_900001.dat'))
containers.service('stop')
