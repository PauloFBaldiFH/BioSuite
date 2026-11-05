"""Cliente da API oficial do Galaxy; não executa pacotes no host do painel."""

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import build_opener, HTTPRedirectHandler, Request

TOOL_SHED = 'https://toolshed.g2.bx.psu.edu'


class GalaxyError(Exception):
    """Erro seguro para mostrar no terminal, sem corpo de resposta ou credencial."""


def validate_url(value: str) -> str:
    value = value.strip().rstrip('/')
    try:
        parsed = urlsplit(value)
        parsed.port
        loopback = parsed.hostname == 'localhost'
        try:
            loopback = loopback or ipaddress.ip_address(parsed.hostname or '').is_loopback
        except ValueError:
            pass
        if (not parsed.hostname or parsed.username or parsed.password or parsed.query
                or parsed.fragment or any(ord(c) < 33 for c in value)
                or parsed.scheme not in ('http', 'https')
                or (parsed.scheme == 'http' and not loopback)):
            raise ValueError
    except ValueError:
        raise GalaxyError('URL inválida: use HTTPS, ou HTTP apenas em localhost/loopback. Não inclua credenciais ou parâmetros.') from None
    return value


@dataclass(frozen=True)
class ToolSpec:
    name: str
    owner: str
    revision: str

    def validate(self):
        if not all(re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}', v) for v in (self.name, self.owner)):
            raise GalaxyError('Informe nome e proprietário válidos do repositório no Tool Shed.')
        if not re.fullmatch(r'(?:[0-9a-f]{12}|[0-9a-f]{40})', self.revision):
            raise GalaxyError('Informe a revisão Mercurial exata do Tool Shed (12 ou 40 caracteres hexadecimais).')


@dataclass(frozen=True)
class Repository:
    id: str
    name: str
    owner: str
    revision: str
    shed: str
    status: str
    deleted: bool
    uninstalled: bool

    @property
    def display_status(self) -> str:
        if self.uninstalled:
            return 'Desinstalado'
        if self.deleted:
            return 'Desativado'
        return {'Installed': 'Instalado', 'Error': 'Falhou'}.get(self.status, self.status)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Nunca encaminhar a chave para outro host, nem repetir POST por redirecionamento.
        return None


class GalaxyClient:
    def __init__(self, url: str, api_key: str, timeout: float = 60):
        self.url = validate_url(url)
        if not api_key.strip() or any(ord(c) < 33 or ord(c) > 126 for c in api_key.strip()):
            raise GalaxyError('Informe uma chave de API válida de um administrador do Galaxy.')
        self._key = api_key.strip()
        self.timeout = timeout
        self._opener = build_opener(NoRedirect())

    def _request(self, method: str, path: str, payload=None, *, public=False):
        data = None if payload is None else json.dumps(payload).encode()
        headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
        if not public:
            headers['x-api-key'] = self._key
        req = Request((TOOL_SHED if public else self.url) + path, data=data, method=method, headers=headers)
        try:
            with self._opener.open(req, timeout=self.timeout) as response:
                raw = response.read(8 * 1024 * 1024 + 1)
            if len(raw) > 8 * 1024 * 1024:
                raise GalaxyError('Resposta do Galaxy maior que o limite suportado.')
            result = json.loads(raw)
        except HTTPError as error:
            if error.code in (401, 403):
                message = 'Acesso negado. Verifique a chave e a permissão de administrador no Galaxy.'
            elif 300 <= error.code < 400:
                message = 'Galaxy redirecionou a requisição. Informe a URL final correta; a chave não foi encaminhada.'
            else:
                message = f'Galaxy respondeu HTTP {error.code}. Consulte os logs do servidor.'
            raise GalaxyError(message) from None
        except (URLError, TimeoutError, socket.timeout, OSError):
            raise GalaxyError('Falha de conexão ou timeout. O Galaxy pode continuar a operação; atualize o estado antes de tentar novamente.') from None
        except (ValueError, UnicodeError):
            raise GalaxyError('A resposta não é JSON válido da API do Galaxy.') from None
        if isinstance(result, dict) and (result.get('status') == 'error' or result.get('err_msg')):
            raise GalaxyError('Galaxy informou uma falha. Consulte os logs do servidor e atualize a lista.')
        return result

    def revisions(self, name: str, owner: str) -> list[str]:
        ToolSpec(name, owner, '0' * 12).validate()
        result = self._request('GET', '/api/repositories/get_ordered_installable_revisions?'
                               + urlencode({'name': name, 'owner': owner}), public=True)
        if not isinstance(result, list) or not result or not all(
                isinstance(v, str) and re.fullmatch(r'(?:[0-9a-f]{12}|[0-9a-f]{40})', v) for v in result):
            raise GalaxyError('Nenhuma revisão instalável válida foi encontrada no Tool Shed.')
        return result

    def connect(self) -> list[Repository]:
        user = self._request('GET', '/api/users/current')
        if not isinstance(user, dict) or not user.get('id'):
            raise GalaxyError('Não foi possível autenticar a conta no Galaxy.')
        return self.repositories()

    def repositories(self) -> list[Repository]:
        result = self._request('GET', '/api/tool_shed_repositories')
        if not isinstance(result, list):
            raise GalaxyError('Formato inesperado da lista de repositórios do Galaxy.')
        try:
            return [Repository(str(r['id']), r['name'], r['owner'], r['changeset_revision'],
                               r['tool_shed'], r['status'], bool(r['deleted']), bool(r['uninstalled']))
                    for r in result]
        except (KeyError, TypeError):
            raise GalaxyError('Registro de ferramenta incompatível com a API esperada.') from None

    @contextmanager
    def _mutation_lock(self):
        root = Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'biosuite/locks'
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = root / (hashlib.sha256(self.url.encode()).hexdigest() + '.lock')
        with path.open('a') as stream:
            os.chmod(path, 0o600)
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise GalaxyError('Outra operação BioSuite está em andamento neste Galaxy.') from None
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def install(self, spec: ToolSpec) -> list[Repository]:
        spec.validate()
        with self._mutation_lock():
            for repo in self.repositories():
                if (repo.name == spec.name and repo.owner == spec.owner and repo.revision == spec.revision
                        and repo.shed.rstrip('/') in (TOOL_SHED, TOOL_SHED.removeprefix('https://'))
                        and not repo.uninstalled and not repo.deleted):
                    raise GalaxyError('Esta revisão já está registrada no Galaxy. Atualize e confira seu estado antes de solicitar outra instalação.')
            self._request('POST', '/api/tool_shed_repositories/install_repository_revision', {
                'tool_shed_url': TOOL_SHED, 'name': spec.name, 'owner': spec.owner,
                'changeset_revision': spec.revision,
                'new_tool_panel_section_label': 'BioSuite',
                'install_repository_dependencies': True,
                'install_resolver_dependencies': True,
                'install_tool_dependencies': False,
            })
            return self.repositories()

    def uninstall(self, selected: Repository) -> list[Repository]:
        if not re.fullmatch(r'[A-Za-z0-9_-]+', selected.id):
            raise GalaxyError('Identificador de repositório inválido.')
        with self._mutation_lock():
            current = next((r for r in self.repositories() if r.id == selected.id), None)
            if current != selected:
                raise GalaxyError('O repositório mudou desde a seleção. Atualize e confirme novamente.')
            if current.uninstalled or current.status not in ('Installed', 'Error', 'Deactivated'):
                raise GalaxyError('Estado incompatível com remoção. Aguarde uma instalação em andamento e atualize.')
            self._request('DELETE', '/api/tool_shed_repositories/' + quote(selected.id, safe='')
                          + '?' + urlencode({'remove_from_disk': 'true'}))
            return self.repositories()
