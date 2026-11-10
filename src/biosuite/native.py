"""Instalação e controle do Galaxy nativo gerenciado pelo BioSuite."""

from dataclasses import dataclass
from importlib.resources import files
import json
import os
from pathlib import Path
import re
import subprocess
import time
from urllib.request import urlopen

RELEASE = '26.1.2'
BASE = Path('/opt/biosuite-galaxy')
CONFIG = Path('/etc/biosuite/galaxy.yml')
UNIT = 'biosuite-galaxy.service'
LOG = Path('/var/log/biosuite-install/galaxy.log')


class NativeError(Exception):
    pass


@dataclass(frozen=True)
class NativeSettings:
    email: str
    port: int = 8080

    def validate(self):
        if not re.fullmatch(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', self.email):
            raise NativeError('Informe o e-mail que será usado pelo administrador no Galaxy.')
        if not 1024 <= self.port <= 65535:
            raise NativeError('Escolha uma porta entre 1024 e 65535.')


def installation_summary(settings: NativeSettings) -> str:
    settings.validate()
    return (f'Galaxy {RELEASE} nativo + PostgreSQL\n'
            f'Administrador: {settings.email}\nAcesso: somente local, porta {settings.port}\n\n'
            'Instalará pacotes via APT, criará o usuário biosuitegalaxy e o banco biosuitegalaxy.\n'
            'Código: /opt/biosuite-galaxy\nDados: /var/lib/biosuite-galaxy\n'
            'Configuração: /etc/biosuite/galaxy.yml\nServiço: biosuite-galaxy.service\n\n'
            'Exige administrador, systemd ativo e pelo menos 15 GiB livres para a base. '
            'Ferramentas, bases e datasets precisam de recursos adicionais.\n'
            'Não substitui instalações existentes nem atualiza releases automaticamente. '
            'Coleções científicas e publicação externa não são instaladas.\n\n'
            'Ao terminar, cadastre-se no Galaxy com o e-mail informado para obter acesso administrativo.')


def _require_root():
    if os.geteuid() != 0:
        raise NativeError('Esta ação altera o sistema. Abra o painel com sudo biosuite-config '
                          '(ou sudo e o caminho completo do comando instalado).')


def install(settings: NativeSettings, output=print, *, no_service=False):
    settings.validate()
    _require_root()
    script = files('biosuite').joinpath('assets/install-galaxy.sh')
    command = ['bash', str(script), '--admin-email', settings.email, '--port', str(settings.port), '--yes']
    if no_service:
        command.append('--no-service')
    LOG.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with LOG.open('a') as sink:
        os.chmod(LOG, 0o600)
        offset = sink.tell()
        sink.write(f'\n--- Galaxy {RELEASE}: instalação solicitada ---\n')
        sink.flush()
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=sink,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        # Arquivo persistente: perder o terminal não fecha o stdout do instalador.
        with LOG.open() as stream:
            stream.seek(offset)
            while True:
                line = stream.readline()
                if line:
                    output(line.rstrip('\n'))
                elif process.poll() is not None:
                    break
                else:
                    time.sleep(0.1)
        code = process.wait()
    if code:
        raise NativeError(f'Instalação interrompida com código {code}. Consulte {LOG}. '
                          'Arquivos e dados existentes foram mantidos; revise a falha antes de tentar novamente.')


def _manifest():
    try:
        value = json.loads((BASE / 'state.json').read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def status() -> dict:
    manifest = _manifest()
    result = {'managed': (BASE / '.biosuite-native').is_file(),
              'prepared': (BASE / 'complete').is_file(), 'version': manifest.get('version'),
              'port': manifest.get('port'), 'service': 'não verificado', 'api': 'não verificada',
              'interface': 'não verificada'}
    if not result['managed']:
        result['service'] = 'instalação BioSuite não detectada'
        return result
    try:
        probe = subprocess.run(['systemctl', 'is-active', UNIT], capture_output=True, text=True, timeout=10)
        result['service'] = probe.stdout.strip() or 'systemd indisponível'
    except (OSError, subprocess.TimeoutExpired):
        result['service'] = 'systemd indisponível'
    port = manifest.get('port')
    if isinstance(port, int) and 1024 <= port <= 65535:
        try:
            with urlopen(f'http://127.0.0.1:{port}/api/version', timeout=3) as response:
                version = json.load(response)
            result['api'] = 'respondeu' if isinstance(version, dict) and version.get('version_major') == '26.1' else 'versão inesperada'
            with urlopen(f'http://127.0.0.1:{port}/', timeout=3) as response:
                page = response.read(2 * 1024 * 1024).lower()
            result['interface'] = 'HTML entregue' if b'<html' in page else 'resposta inesperada'
        except (OSError, ValueError):
            result['api'] = 'sem resposta válida'
    return result


def _service(action: str) -> dict:
    if action not in ('start', 'stop', 'restart'):
        raise NativeError('Ação de serviço inválida.')
    _require_root()
    if not (BASE / 'complete').is_file():
        raise NativeError('A instalação gerenciada do Galaxy ainda não foi concluída.')
    try:
        result = subprocess.run(['systemctl', action, UNIT], capture_output=True, text=True, timeout=150)
    except subprocess.TimeoutExpired:
        raise NativeError('Systemd excedeu o tempo de espera. Consulte o estado e os logs antes de repetir a ação.') from None
    if result.returncode:
        raise NativeError('Systemd não concluiu a ação. Consulte os logs do serviço.')
    return status()


def service(action: str) -> dict:
    from biosuite.operations import lock, OperationError
    _require_root()
    try:
        with lock(BASE / 'install.lock'):
            if (BASE / 'maintenance.json').exists():
                raise NativeError('Manutenção pendente. Confira o diário antes de controlar o serviço.')
            return _service(action)
    except OperationError as error:
        raise NativeError(str(error)) from None


def logs() -> str:
    parts = []
    if LOG.exists():
        try:
            with LOG.open('rb') as stream:
                stream.seek(max(0, LOG.stat().st_size - 24000))
                parts.append(stream.read().decode(errors='replace'))
        except PermissionError:
            parts.append('Logs da instalação exigem acesso de administrador.')
    try:
        result = subprocess.run(['journalctl', '-u', UNIT, '-n', '100', '--no-pager'],
                                capture_output=True, text=True, timeout=10)
        parts.append(result.stdout if result.returncode == 0 else 'Journal do serviço indisponível.')
    except (OSError, subprocess.TimeoutExpired):
        parts.append('Journal do serviço indisponível.')
    return '\n'.join(parts)
