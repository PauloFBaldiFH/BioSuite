"""Cliente do broker BioSuite, compatível com as assinaturas Ed25519 do Nexus."""
import base64
from contextlib import contextmanager
from functools import wraps
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import tempfile
import time
import threading
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from biosuite.galaxy import GalaxyError, NoRedirect, validate_url
from biosuite.operations import OperationError, capture, lock, require_root, run_logged

DEFAULT_BROKER = 'https://biosuite-broker.koha.nexus'
ROOT = Path('/etc/biosuite/connection') if os.geteuid() == 0 else Path.home() / '.config/biosuite/connection'
UNIT = 'biosuite-cloudflared.service'
SERVICE_DIR = Path('/etc/systemd/system')


def serialized(method):
    @wraps(method)
    def guarded(self, *args, **kwargs):
        with self.guard():
            return method(self, *args, **kwargs)
    return guarded


class BrokerClient:
    def __init__(self, broker=DEFAULT_BROKER, root: Path = ROOT):
        try:
            self.url = validate_url(broker)
        except GalaxyError as error:
            raise OperationError(str(error)) from None
        if self.url.split('://', 1)[1].count('/'):
            raise OperationError('Informe somente a origem HTTPS do broker, sem subcaminho.')
        self.root = root
        self.key = root / 'identity.pem'
        self.file = root / 'state.json'
        self.opener = build_opener(NoRedirect())
        self._mutex = threading.RLock()
        self._depth = 0

    @contextmanager
    def guard(self):
        with self._mutex:
            if self._depth:
                yield
            else:
                self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
                with lock(self.root / 'operation.lock'):
                    self._depth = 1
                    try:
                        yield
                    finally:
                        self._depth = 0

    def state(self):
        try:
            value = json.loads(self.file.read_text())
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def save(self, value):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.root / 'state.tmp'
        with temporary.open('w') as stream:
            json.dump(value, stream)
        os.chmod(temporary, 0o600)
        temporary.replace(self.file)

    def identity(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not self.key.exists():
            # A chave nunca sai desta máquina, exceto por exportação de recuperação explícita.
            result = subprocess.run(['openssl', 'genpkey', '-algorithm', 'ed25519', '-out', str(self.key)],
                                    stdin=subprocess.DEVNULL, capture_output=True)
            if result.returncode:
                raise OperationError('Não foi possível gerar a identidade Ed25519. Verifique OpenSSL.')
            os.chmod(self.key, 0o600)
        public = subprocess.run(['openssl', 'pkey', '-in', str(self.key), '-pubout', '-outform', 'DER'],
                                stdin=subprocess.DEVNULL, capture_output=True)
        prefix = bytes.fromhex('302a300506032b6570032100')
        if public.returncode or not public.stdout.startswith(prefix) or len(public.stdout) != 44:
            raise OperationError('A identidade local não é uma chave Ed25519 válida.')
        return base64.b64encode(public.stdout[-32:]).decode()

    def sign(self, library_id, method, path, body=b''):
        if not re.fullmatch(r'[A-Za-z0-9-]{1,64}', library_id):
            raise OperationError('Identificador da instalação inválido.')
        timestamp = str(int(time.time()))
        nonce = secrets.token_urlsafe(18)
        message = '\n'.join(['KEI-SIG-v1', method.upper(), path, timestamp, nonce, hashlib.sha256(body).hexdigest()]).encode()
        with tempfile.NamedTemporaryFile(dir=self.root) as stream:
            stream.write(message)
            stream.flush()
            result = subprocess.run(['openssl', 'pkeyutl', '-sign', '-rawin', '-inkey', str(self.key), '-in', stream.name],
                                    stdin=subprocess.DEVNULL, capture_output=True)
        if result.returncode or len(result.stdout) != 64:
            raise OperationError('Não foi possível assinar a requisição ao broker.')
        return {'X-KEI-Library': library_id, 'X-KEI-Timestamp': timestamp, 'X-KEI-Nonce': nonce,
                'X-KEI-Signature': base64.b64encode(result.stdout).decode()}

    def request(self, method, path, payload=None, *, signed=False):
        body = b'' if payload is None else json.dumps(payload, separators=(',', ':')).encode()
        headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
        if signed:
            state = self.state()
            if state.get('broker') != self.url or not state.get('library_id'):
                raise OperationError('Não existe cadastro concluído para este broker.')
            headers.update(self.sign(state['library_id'], method, path, body))
        req = Request(self.url + path, data=None if method == 'GET' else body, headers=headers, method=method)
        try:
            with self.opener.open(req, timeout=30) as response:
                raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError
            if result.get('error'):
                raise OperationError('O broker informou uma falha. Consulte aprovação e estado antes de repetir.')
            return result
        except HTTPError as error:
            raise OperationError(f'Broker respondeu HTTP {error.code}. Confira aprovação, estado e configuração; '
                                 'a requisição não foi repetida automaticamente.') from None
        except (OSError, URLError, ValueError):
            raise OperationError('Não foi possível consultar o broker. Se uma alteração foi enviada, '
                                 'confira seu estado antes de reenviar.') from None

    def capabilities(self):
        result = self.request('GET', '/v1/capabilities')
        if result.get('application') != 'galaxy' or result.get('origin_port_configurable') is not True:
            raise OperationError('Este broker ainda não contém a adaptação Galaxy. O Worker Koha original não será usado como se fosse compatível.')
        return result

    @serialized
    def start(self, institution, email, slug, port):
        if not 3 <= len(institution.strip()) <= 200 or not re.fullmatch(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', email):
            raise OperationError('Informe instituição e e-mail válidos.')
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,48}[a-z0-9]', slug) or not 1024 <= port <= 65535:
            raise OperationError('Informe um nome DNS simples (3–50 caracteres) e porta entre 1024 e 65535.')
        if self.state():
            raise OperationError('Já existe uma solicitação ou identidade nesta configuração. Consulte o estado ou recupere o cadastro existente.')
        self.capabilities()
        self.identity()
        response = self.request('POST', '/v1/device/start', {
            'institution_name': institution, 'contact_email': email, 'requested_name': slug,
            'services': ['galaxy'], 'origin_port': port})
        if not isinstance(response.get('device_code'), str):
            raise OperationError('Broker não retornou um código de cadastro válido.')
        self.save({'broker': self.url, 'device_code': response['device_code'], 'port': port,
                   'status': response.get('status'), 'user_code': response.get('user_code'),
                   'verification_uri': response.get('verification_uri'), 'hostnames': response.get('hostnames', {})})
        return self.public_state()

    @serialized
    def poll(self):
        state = self.state()
        if state.get('broker') != self.url:
            raise OperationError('Selecione o broker usado nesta solicitação.')
        if state.get('library_id'):
            response = self.request('GET', '/v1/library', signed=True)
        else:
            if not state.get('device_code'):
                raise OperationError('Nenhuma solicitação para consultar.')
            response = self.request('POST', '/v1/device/poll', {'device_code': state['device_code']})
        state.update({k: response[k] for k in ('status', 'hostnames') if k in response})
        self.save(state)
        return self.public_state()

    @serialized
    def reset_pending(self):
        state = self.state()
        if state.get('library_id') or state.get('enrollment_sent'):
            raise OperationError('Cadastro concluído ou matrícula enviada exige recuperação, não reinício.')
        self.poll()
        if self.state().get('status') not in ('denied', 'expired'):
            raise OperationError('A solicitação ainda não foi recusada ou expirada pelo broker.')
        self.file.unlink()
        return 'Solicitação local encerrada; a identidade foi preservada. Você pode solicitar outro endereço.'

    @serialized
    def enroll(self):
        state = self.state()
        if state.get('library_id'):
            return self.poll()
        if state.get('status') != 'approved' or not state.get('device_code'):
            raise OperationError('Consulte a aprovação antes de concluir o cadastro.')
        if state.get('enrollment_sent'):
            raise OperationError('Uma matrícula já foi enviada sem resposta confirmada. Use a recuperação pelo administrador do broker; não recrie a identidade.')
        state['enrollment_sent'] = True
        self.save(state)
        response = self.request('POST', '/v1/enroll', {'device_code': state['device_code'], 'public_key': self.identity()})
        if not isinstance(response.get('library_id'), str):
            raise OperationError('Resposta de cadastro inválida. Consulte o administrador para recuperar a identidade.')
        state.update({'library_id': response['library_id'], 'job_id': response.get('job_id'),
                      'hostnames': response.get('hostnames', {}), 'status': 'provisioning'})
        state.pop('device_code', None)
        self.save(state)
        return self.public_state()

    def public_state(self):
        state = self.state()
        return {k: state[k] for k in ('broker', 'library_id', 'status', 'port', 'user_code', 'verification_uri', 'hostnames') if k in state}

    @serialized
    def export_recovery(self, destination: Path):
        state = self.state()
        if not state.get('library_id'):
            raise OperationError('Conclua o cadastro antes de exportar recuperação.')
        with destination.expanduser().open('x') as stream:
            os.chmod(stream.name, 0o600)
            json.dump({'format': 'biosuite-address-v1', 'state': state, 'private_key': self.key.read_text()}, stream)
        return 'Recuperação salva em arquivo privado. Guarde-o fora desta máquina; o conteúdo não será mostrado no painel.'

    @serialized
    def import_recovery(self, source: Path):
        if self.state():
            raise OperationError('Uma configuração existente não será sobrescrita.')
        with source.expanduser().open('rb') as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise OperationError('Arquivo de recuperação inválido.')
        try:
            document = json.loads(raw)
            state, pem = document['state'], document['private_key']
            if document['format'] != 'biosuite-address-v1' or validate_url(state['broker']) != self.url or not re.fullmatch(r'[A-Za-z0-9-]{1,64}', state['library_id']):
                raise ValueError
            if not isinstance(pem, str) or not pem.startswith('-----BEGIN PRIVATE KEY-----'):
                raise ValueError
        except (GalaxyError, ValueError, KeyError, TypeError):
            raise OperationError('Arquivo de recuperação incompatível com este broker.') from None
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.key.open('x') as stream:
            stream.write(pem)
        os.chmod(self.key, 0o600)
        self.identity()
        self.save(state)
        return self.poll()

    @serialized
    def activate(self):
        require_root()
        if self.state().get('status') != 'active':
            raise OperationError('Consulte o broker até a instalação estar ativa antes de iniciar o túnel.')
        binary = shutil.which('cloudflared')
        if binary not in ('/usr/bin/cloudflared', '/usr/local/bin/cloudflared'):
            raise OperationError('Prepare o conector cloudflared primeiro.')
        if '--token-file' not in capture([binary, 'tunnel', 'run', '--help']):
            raise OperationError('Esta versão do cloudflared não suporta token em arquivo. Atualize pelo repositório oficial.')
        response = self.request('GET', '/v1/tunnel-token', signed=True)
        token = response.get('tunnel_token')
        if not isinstance(token, str) or not token or '\n' in token:
            raise OperationError('O broker não retornou um token de túnel válido.')
        token_file = self.root / 'tunnel.token'
        token_file.write_text(token)
        os.chmod(token_file, 0o600)
        unit = SERVICE_DIR / UNIT
        if unit.exists() and '# BioSuite tunnel' not in unit.read_text():
            raise OperationError('A unidade existente não pertence ao BioSuite.')
        unit.write_text('[Unit]\nDescription=BioSuite Cloudflare Tunnel\nAfter=network-online.target\nWants=network-online.target\n'
                        '[Service]\n# BioSuite tunnel\nDynamicUser=yes\nLoadCredential=tunnel-token:' + str(token_file) + '\n'
                        'ExecStart=' + binary + ' --no-autoupdate tunnel run --token-file %d/tunnel-token\n'
                        'Restart=on-failure\nRestartSec=5\nNoNewPrivileges=yes\nProtectHome=yes\nProtectSystem=strict\n'
                        '[Install]\nWantedBy=multi-user.target\n')
        capture(['systemctl', 'daemon-reload'])
        capture(['systemctl', 'enable', UNIT])
        capture(['systemctl', 'restart', UNIT])
        return {'connector': capture(['systemctl', 'is-active', UNIT]).strip(), **self.public_state()}


def prepare_connector(output=print):
    from importlib.resources import files
    require_root()
    run_logged(['bash', str(files('biosuite').joinpath('assets/install-cloudflared.sh'))],
               Path('/var/log/biosuite-install/cloudflared.log'), output)


def stop_connector():
    require_root()
    capture(['systemctl', 'disable', '--now', UNIT])
    return 'Conector local desativado. O cadastro e o endereço não foram liberados.'
