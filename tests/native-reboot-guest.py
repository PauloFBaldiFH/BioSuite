"""Somente dentro da VM descartável da CI; não reinicia a máquina por conta própria."""
import hashlib
import json
import os
from pathlib import Path
import pwd
import sys

from biosuite.backup_backends import DATA, DB, NativeBackend
from biosuite.backup_format import write_private
from biosuite.operations import capture

STATE = Path('/var/lib/biosuite-reboot-smoke')
CONFIG = Path('/etc/biosuite/galaxy.yml')
BOOT = Path('/proc/sys/kernel/random/boot_id')
DATASET = DATA / 'datasets/000/900/dataset_900002.dat'


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(phase):
    if (os.environ.get('BIOSUITE_REBOOT_SMOKE') != '1' or os.geteuid() != 0
            or not Path('/etc/biosuite-ci-disposable').is_file()):
        raise SystemExit('Teste permitido somente na VM descartável identificada pela CI.')
    adapter = NativeBackend()  # Também exige systemd como PID 1 e layout gerenciado.
    assert capture(['systemctl', 'is-enabled', 'biosuite-galaxy.service']).strip() == 'enabled'
    if phase == 'prepare':
        assert not STATE.exists(), 'Fixture de reboot já existe.'
        assert adapter.sql('SELECT count(*) FROM dataset').strip() == '0', 'Banco não está vazio.'
        assert not DATASET.exists(), 'Arquivo de teste já existe.'
        adapter.start()
        adapter.sql("INSERT INTO dataset (id,state,deleted,purged,purgable,uuid,file_size,total_size,create_time,update_time) VALUES (900002,'ok',false,false,true,'00000000000000000000000000900002',5,5,now(),now())")
        account = pwd.getpwnam(DB)
        DATASET.parent.mkdir(parents=True, exist_ok=True)
        for directory in (DATASET.parent, DATASET.parent.parent):
            os.chown(directory, account.pw_uid, account.pw_gid)
        DATASET.write_text('ACGT\n')
        os.chmod(DATASET, 0o600)
        os.chown(DATASET, account.pw_uid, account.pw_gid)
        STATE.mkdir(mode=0o700)
        write_private(STATE / 'state.json', {'boot_id': BOOT.read_text().strip(),
                      'config_sha256': checksum(CONFIG), 'dataset_sha256': checksum(DATASET)})
        os.sync()
        print('Serviço habilitado, dataset e configuração registrados antes do reboot.', flush=True)
    elif phase == 'verify':
        previous = json.loads((STATE / 'state.json').read_text())
        assert BOOT.read_text().strip() != previous['boot_id'], 'A VM não foi reiniciada.'
        # Não iniciar manualmente: a verificação deve comprovar o início automático.
        adapter.wait_healthy()
        assert adapter.running(), 'Galaxy não iniciou automaticamente.'
        assert checksum(CONFIG) == previous['config_sha256'], 'Configuração mudou no reboot.'
        assert checksum(DATASET) == previous['dataset_sha256'], 'Dataset mudou no reboot.'
        assert adapter.sql('SELECT file_size FROM dataset WHERE id=900002').strip() == '5'
        assert capture(['runuser', '-u', DB, '--', 'cat', str(DATASET)], cwd='/') == 'ACGT\n'
        adapter.sql('DELETE FROM dataset WHERE id=900002')
        DATASET.unlink()
        adapter.stop()
        print('Reboot real: novo boot_id, Galaxy automático, API/HTML, PostgreSQL, dataset e configuração preservados: OK.', flush=True)
    else:
        raise SystemExit('Use prepare ou verify.')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) == 2 else '')
