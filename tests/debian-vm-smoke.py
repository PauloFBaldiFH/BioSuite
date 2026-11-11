"""Controlador no runner: testa e reinicia somente o guest Debian da CI."""
import os
from pathlib import Path
import shlex
import subprocess
import time


def remote(command, timeout=60, check=True):
    result = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5',
                             '-o', 'ConnectionAttempts=1', 'debian', command],
                            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            timeout=timeout)
    if result.stdout:
        print(result.stdout, end='', flush=True)
    if check and result.returncode:
        raise RuntimeError(f'Comando no guest falhou: código {result.returncode}')
    return result


def main():
    if os.environ.get('BIOSUITE_DEBIAN_VM_SMOKE') != '1' or os.environ.get('GITHUB_ACTIONS') != 'true':
        raise SystemExit('Controlador reservado ao runner descartável GitHub da CI.')
    project = shlex.quote(str(Path.cwd()))
    prefix = f'cd {project} && '
    remote('test -f /etc/biosuite-ci-disposable && test "$(cat /proc/1/comm)" = systemd')
    remote(prefix + 'BIOSUITE_SMOKE_SYSTEMD=1 BIOSUITE_SMOKE_PORT=8087 bash tests/native-smoke.sh', timeout=3000)
    print('::notice title=Debian VM::Instalação nativa, stop/start e reexecução: OK.', flush=True)
    remote(prefix + 'PYTHONPATH=src BIOSUITE_BACKUP_SMOKE=1 python3 tests/backups-native-smoke.py', timeout=3000)
    print('::notice title=Debian VM::Backup, restauração de dataset e rollback: OK.', flush=True)
    guest = prefix + 'PYTHONPATH=src BIOSUITE_REBOOT_SMOKE=1 python3 tests/native-reboot-guest.py '
    remote(guest + 'prepare', timeout=600)
    old_boot = remote('cat /proc/sys/kernel/random/boot_id').stdout.strip()
    # Agendamento permite ao SSH terminar antes da queda; nunca reinicia o runner host.
    remote('systemd-run --unit=biosuite-ci-reboot --on-active=3s /usr/bin/systemctl reboot')
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        time.sleep(3)
        try:
            result = remote('cat /proc/sys/kernel/random/boot_id', timeout=15, check=False)
        except subprocess.TimeoutExpired:
            continue  # SSH pode desaparecer enquanto o kernel reinicia.
        if result.returncode == 0 and result.stdout.strip() and result.stdout.strip() != old_boot:
            break
    else:
        raise RuntimeError('A VM não retornou com um novo boot_id em 240 segundos.')
    remote(guest + 'verify', timeout=600)
    print('::notice title=Debian VM::Reboot real e início automático com dados preservados: OK.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as failure:
        detail = (type(failure).__name__ + ': ' + str(failure)).replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
        print('::error title=Controlador Debian VM::' + detail, flush=True)
        # Dados fictícios, sem credenciais de produção; resumir também nas anotações públicas.
        try:
            result = remote("journalctl -u biosuite-galaxy.service -n 25 --no-pager; tail -n 25 /var/log/biosuite-install/galaxy.log /var/log/biosuite-install/backups.log", check=False)
            text = result.stdout[-10000:].replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
            print('::error title=Integração Debian VM::' + text, flush=True)
        except Exception as error:
            print('Diagnóstico do guest indisponível:', type(error).__name__, flush=True)
        raise
