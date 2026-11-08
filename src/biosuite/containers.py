"""Deploy Galaxy/PostgreSQL com Compose e volumes persistentes próprios."""
from importlib.resources import files
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import time
from urllib.request import urlopen

from biosuite.native import NativeSettings, RELEASE
from biosuite.operations import OperationError, capture, lock, require_root, run_logged

BASE = Path(os.environ.get('BIOSUITE_DOCKER_HOME', '/opt/biosuite-docker' if os.geteuid() == 0
                           else str(Path.home() / '.local/share/biosuite/docker')))
LOG = BASE / 'docker.log'
PROJECT = 'biosuite-galaxy'


def compose(*args):
    return ['docker', 'compose', '--project-name', PROJECT, '--file', str(BASE / 'compose.json'), *args]


def installation_summary(settings: NativeSettings):
    settings.validate()
    return (f'Galaxy {RELEASE} em Docker + PostgreSQL\nAdministrador: {settings.email}\n'
            f'Porta de testes: 127.0.0.1:{settings.port} → container 8080\n\n'
            'Exige Docker Engine + plugin Compose. Use Preparar Docker se estiverem ausentes.\n'
            'Cria imagem própria a partir do commit oficial fixado, rede e volumes persistentes separados. '
            'O build inicial baixa dependências e pode demorar. Não remove containers ou volumes existentes. '
            'O banco não publica portas para o host. Ferramentas científicas permanecem sob demanda.')


def prepare(output=print):
    require_root()
    run_logged(['bash', str(files('biosuite').joinpath('assets/install-docker.sh'))], LOG, output)


def _manifest():
    try:
        value = json.loads((BASE / 'state.json').read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def install(settings: NativeSettings, output=print):
    settings.validate()
    capture(['docker', 'compose', 'version'])
    capture(['docker', 'info', '--format', '{{.ServerVersion}}'])
    if BASE.exists() and not (BASE / '.biosuite-docker').is_file():
        raise OperationError('O diretório Docker já existe e não é gerenciado pelo BioSuite.')
    BASE.mkdir(parents=True, exist_ok=True, mode=0o700)
    with lock(BASE / 'install.lock'):
        current = _manifest()
        if current and (current.get('port') != settings.port or current.get('email') != settings.email):
            raise OperationError('A configuração existente é diferente. Não será sobrescrita.')
        if not current:
            for volume in ('biosuite-galaxy_data', 'biosuite-galaxy_postgres'):
                if capture(['docker', 'volume', 'ls', '--filter', 'name=^' + volume + '$', '--format', '{{.Name}}']).strip():
                    raise OperationError('Um volume com o nome reservado já existe. Não será adotado.')
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', settings.port))
            (BASE / '.biosuite-docker').write_text(RELEASE)
            build = BASE / 'build'
            build.mkdir(exist_ok=True)
            for name in ('Dockerfile', 'entrypoint.py', 'build-config.json'):
                shutil.copyfile(files('biosuite').joinpath('assets/docker/' + name), build / name)
            password = BASE / 'db-password'
            with password.open('x') as stream:
                stream.write(secrets.token_urlsafe(36))
            os.chmod(password, 0o600)
            ca = Path('/etc/ssl/certs/ca-certificates.crt')
            document = {
                'services': {
                    'db': {'image': 'postgres:17-bookworm@sha256:665dc7b37ac52a17e298511414c21d23ffa4e6a6ef6225b3e5d59c7afb35e994', 'restart': 'unless-stopped',
                           'environment': {'POSTGRES_USER': 'biosuitegalaxy', 'POSTGRES_DB': 'biosuitegalaxy',
                                           'POSTGRES_PASSWORD_FILE': '/run/secrets/db_password'},
                           'secrets': ['db_password'], 'volumes': ['postgres:/var/lib/postgresql/data'],
                           'healthcheck': {'test': ['CMD-SHELL', 'pg_isready -U biosuitegalaxy -d biosuitegalaxy'], 'interval': '5s', 'retries': 30}},
                    'galaxy': {'image': 'biosuite-galaxy:' + RELEASE, 'init': True, 'restart': 'unless-stopped',
                               'build': {'context': str(build), 'secrets': ['proxy_ca']},
                               'depends_on': {'db': {'condition': 'service_healthy'}},
                               'environment': {'GALAXY_ADMIN_EMAIL': settings.email, 'SSL_CERT_FILE': '/run/secrets/proxy_ca',
                                               'REQUESTS_CA_BUNDLE': '/run/secrets/proxy_ca', 'PIP_CERT': '/run/secrets/proxy_ca'},
                               'ports': [f'127.0.0.1:{settings.port}:8080'], 'volumes': ['data:/data'],
                               'secrets': ['db_password', 'proxy_ca']}},
                'volumes': {'data': {}, 'postgres': {}},
                'secrets': {'db_password': {'file': str(password)}, 'proxy_ca': {'file': str(ca)}}}
            (BASE / 'compose.json').write_text(json.dumps(document, indent=2))
            (BASE / 'state.json').write_text(json.dumps({'email': settings.email, 'port': settings.port, 'version': RELEASE}))
        for name in ('Dockerfile', 'entrypoint.py', 'build-config.json'):
            shutil.copyfile(files('biosuite').joinpath('assets/docker/' + name), BASE / 'build' / name)
        run_logged(compose('build'), LOG, output)
        run_logged(compose('up', '-d'), LOG, output)
        for attempt in range(120):
            state = status()
            if state['api'] == 'respondeu' and state['interface'] == 'HTML entregue':
                output('Galaxy Docker respondeu à API e à interface. Volumes persistentes mantidos.')
                return
            time.sleep(3)
        raise OperationError('Containers foram criados, mas Galaxy não ficou saudável. Consulte logs e estado.')


def status():
    manifest = _manifest()
    result = {'managed': bool(manifest), 'mode': 'docker', 'port': manifest.get('port'),
              'api': 'não verificada', 'interface': 'não verificada'}
    if not manifest:
        return result
    try:
        result['containers'] = capture(compose('ps', '--all', '--format', 'json'))
        base = f'http://127.0.0.1:{manifest["port"]}'
        with urlopen(base + '/api/version', timeout=3) as response:
            result['api'] = 'respondeu' if json.load(response).get('version_major') == '26.1' else 'versão inesperada'
        with urlopen(base + '/', timeout=3) as response:
            result['interface'] = 'HTML entregue' if b'<html' in response.read(2 * 1024 * 1024).lower() else 'resposta inesperada'
    except (OperationError, OSError, ValueError):
        result['api'] = 'sem resposta válida'
    return result


def service(action, output=print):
    if action not in ('start', 'stop', 'restart') or not _manifest():
        raise OperationError('Ação inválida ou instalação Docker não detectada.')
    with lock(BASE / 'install.lock'):
        run_logged(compose(action), LOG, output)
    return status()


def logs():
    if not _manifest():
        raise OperationError('Instalação Docker não detectada.')
    return capture(compose('logs', '--tail', '100', '--no-color'))
