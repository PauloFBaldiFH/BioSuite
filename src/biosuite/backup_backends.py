"""Adaptadores de manutenção; somente instalações BioSuite com armazenamento local."""
import json
import os
from pathlib import Path
import platform
import pwd
import re
import shutil
import subprocess
import shlex
import time
import tempfile
import xml.etree.ElementTree as ET

from biosuite import containers, native
from biosuite.backup_format import archive_tree, sync_directory, write_private
from biosuite.operations import OperationError, capture, require_root

DATA = Path('/var/lib/biosuite-galaxy')
CONFIG = Path('/etc/biosuite')
DB = 'biosuitegalaxy'
RUNTIME = Path('/run/biosuite-backup')


def transfer(command, *, source=None, target=None, log=None, cwd=None):
    """Fluxos binários grandes nunca passam pelo terminal ou pela memória inteira."""
    log = Path(log)
    log.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with log.open('ab') as errors:
        os.chmod(log, 0o600)
        with (Path(source).open('rb') if source else open(os.devnull, 'rb')) as stdin:
            with (Path(target).open('wb') if target else open(os.devnull, 'wb')) as stdout:
                if target:
                    os.chmod(target, 0o600)
                result = subprocess.run(command, stdin=stdin, stdout=stdout, stderr=errors, cwd=cwd)
    if result.returncode:
        raise OperationError('Etapa de backup/restauração falhou. Consulte o log privado: ' + str(log))


def host_identity():
    release = platform.freedesktop_os_release()
    return {'distribution': release.get('ID'), 'version': release.get('VERSION_ID'), 'architecture': platform.machine()}


def owned_tree(path, uid, gid):
    for root, dirs, files in os.walk(path, followlinks=False):
        os.chown(root, uid, gid)
        for name in dirs + files:
            os.chown(Path(root) / name, uid, gid, follow_symlinks=False)


def tree_bytes(path):
    total = 0
    for root, _, names in os.walk(path, followlinks=False):
        for name in names:
            item = Path(root) / name
            if not item.is_symlink() and item.is_file():
                total += item.stat().st_size
    return total


def local_data_config(config, data, code):
    galaxy = config['galaxy']
    expected = {'data_dir': str(data), 'file_path': str(data / 'datasets'),
                'tool_dependency_dir': str(data / 'dependencies')}
    if any(galaxy.get(key) != value for key, value in expected.items()):
        raise OperationError('Caminhos de dados fora do layout local suportado.')
    if any(galaxy.get(key) for key in ('object_store_config', 'object_store_config_file', 'distributed_object_store_config_file',
                                     'library_import_dir', 'user_library_import_dir', 'dependency_resolvers_config_file')):
        raise OperationError('Configuração de armazenamento/dependências externa exige backup próprio.')
    if any((code / 'config' / name).exists() for name in ('object_store_conf.xml', 'object_store_conf.yml')):
        raise OperationError('Object store personalizado não suportado neste backup.')


class Backend:
    def sql(self, statement, database=DB, admin=False):
        return capture(self.pg('psql', database, admin=admin) + ['-v', 'ON_ERROR_STOP=1', '-Atc', statement], cwd='/' if self.mode == 'native' else None)

    def check_space(self, info, sizes):
        pass

    def pg_major(self):
        return int(self.sql('SHOW server_version_num')) // 10000

    def assert_idle(self):
        count = int(self.sql("SELECT count(*) FROM job WHERE state IS NULL OR state NOT IN ('ok','error','deleted','deleted_new')"))
        if count:
            raise OperationError(f'Existem {count} jobs pendentes/não terminados. Conclua ou cancele-os no Galaxy antes da manutenção.')
        repositories = int(self.sql("SELECT count(*) FROM tool_shed_repository WHERE status IS NULL OR status NOT IN ('Installed','Uninstalled','Error','Deactivated','Never installed')"))
        if repositories:
            raise OperationError('Há ferramentas em instalação/remoção. Aguarde o Tool Shed antes da manutenção.')
        external = int(self.sql('SELECT count(*) FROM dataset WHERE external_filename IS NOT NULL OR object_store_id IS NOT NULL'))
        if external:
            raise OperationError('Datasets externos/object stores personalizados exigem uma política própria de backup.')

    def temp_database(self, name):
        self.sql(f'CREATE DATABASE "{name}" OWNER {DB}', database='postgres', admin=True)

    def drop_database(self, name):
        if not re.fullmatch(r'biosuite_(verify|old)_[a-f0-9]{16}', name):
            raise OperationError('Nome de banco temporário inválido.')
        self.sql(f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='{name}' AND pid <> pg_backend_pid()", database='postgres', admin=True)
        self.sql(f'DROP DATABASE IF EXISTS "{name}"', database='postgres', admin=True)

    def rename_database(self, source, target):
        allowed = lambda name: name == DB or re.fullmatch(r'biosuite_(verify|old)_[a-f0-9]{16}', name)
        if not allowed(source) or not allowed(target):
            raise OperationError('Nome de banco inválido.')
        self.sql(f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='{source}' AND pid <> pg_backend_pid()", database='postgres', admin=True)
        self.sql(f'ALTER DATABASE "{source}" RENAME TO "{target}"', database='postgres', admin=True)

    def dump(self, target):
        transfer(self.pg('pg_dump', DB) + ['--format=custom', '--no-owner', '--no-privileges'], target=target, log=self.log, cwd='/' if self.mode == 'native' else None)

    def restore_dump(self, source, database):
        transfer(self.pg('pg_restore', database) + ['--exit-on-error', '--no-owner', '--no-privileges', '--single-transaction'], source=source, log=self.log, cwd='/' if self.mode == 'native' else None)
        self.sql('SELECT count(*) FROM galaxy_user', database=database)
        self.sql('SELECT count(*) FROM dataset', database=database)
        self.sql('SELECT count(*) FROM tool_shed_repository', database=database)

    def wait_healthy(self):
        from urllib.request import urlopen
        for attempt in range(120):
            try:
                with urlopen(f'http://127.0.0.1:{self.port}/api/version', timeout=3) as response:
                    if json.load(response).get('version_major') == '26.1':
                        with urlopen(f'http://127.0.0.1:{self.port}/', timeout=3) as page:
                            if b'<html' in page.read(2 * 1024 * 1024).lower():
                                return
            except (OSError, ValueError):
                pass
            time.sleep(2)
        raise OperationError('Galaxy não respondeu após a manutenção. Consulte os logs.')

    def ensure_database(self):
        self.pg_major()

    def finish_database(self):
        pass


class NativeBackend(Backend):
    mode = 'native'

    def __init__(self):
        require_root()
        if not (native.BASE / 'complete').is_file() or not (native.BASE / '.biosuite-native').is_file():
            raise OperationError('Instalação nativa gerenciada não foi concluída.')
        if Path('/proc/1/comm').read_text().strip() != 'systemd':
            raise OperationError('A manutenção nativa exige systemd ativo para parar todos os processos do Galaxy.')
        self.base = native.BASE
        self.lock = self.base / 'install.lock'
        self.journal = self.base / 'maintenance.json'
        self.log = Path('/var/log/biosuite-install/backups.log')
        self.roots = {'data': DATA, 'code': self.base / 'galaxy'}
        config = json.loads((CONFIG / 'galaxy.yml').read_text())
        galaxy = config['galaxy']
        local_data_config(config, DATA, self.roots['code'])
        expected = {'data_dir': str(DATA), 'file_path': str(DATA / 'datasets'),
                    'tool_dependency_dir': str(DATA / 'dependencies'),
                    'database_connection': 'postgresql:///biosuitegalaxy?host=/var/run/postgresql',
                    'install_database_connection': 'postgresql:///biosuitegalaxy?host=/var/run/postgresql'}
        if any(galaxy.get(k) != v for k, v in expected.items()) or galaxy.get('object_store_config_file') or galaxy.get('distributed_object_store_config_file'):
            raise OperationError('Configuração fora do armazenamento local padrão suportado pelo backup.')
        if any(p.is_symlink() for p in (CONFIG / 'galaxy.yml', CONFIG / 'job_conf.xml', DATA, self.roots['code'])):
            raise OperationError('Raízes/configurações por symlink não são suportadas.')
        plugins = ET.parse(CONFIG / 'job_conf.xml').findall('.//plugin')
        if not plugins or any(p.get('load') != 'galaxy.jobs.runners.local:LocalJobRunner' for p in plugins):
            raise OperationError('Executores remotos exigem uma janela de manutenção própria.')
        for key, value in galaxy.items():
            if value and key.endswith(('_dir', '_file', '_path')) and isinstance(value, str):
                path = Path(value)
                path = path if path.is_absolute() else self.roots['code'] / path
                path = path.resolve()
                if not (path == CONFIG / 'job_conf.xml' or any(root == path or root in path.parents for root in self.roots.values())):
                    raise OperationError('Configuração aponta para arquivo externo não coberto pelo backup: ' + key)
        self.port = json.loads((self.base / 'state.json').read_text())['port']

    def _guard_launcher(self):
        if RUNTIME.is_symlink():
            raise OperationError('Diretório runtime incompatível.')
        created = not RUNTIME.exists()
        RUNTIME.mkdir(mode=0o755, exist_ok=True)
        if created:
            os.chmod(RUNTIME, 0o755)
        if RUNTIME.stat().st_uid != os.geteuid() or RUNTIME.stat().st_mode & 0o777 != 0o755:
            raise OperationError('Diretório runtime deve pertencer ao administrador e ter modo 755.')
        launcher = self.base / 'start'
        if launcher.is_symlink():
            raise OperationError('Launcher por symlink não será alterado.')
        text = launcher.read_text()
        if '# BioSuite maintenance gate' in text:
            return
        marker = 'export GALAXY_CONFIG_FILE=/etc/biosuite/galaxy.yml'
        if text.count(marker) != 1 or 'exec sh run.sh --skip-wheels' not in text:
            raise OperationError('Launcher personalizado exige revisão antes do backup.')
        guard = ('# BioSuite maintenance gate\n'
                 'if [[ -f ' + shlex.quote(str(self.journal)) + ' && ! -f ' + shlex.quote(str(RUNTIME / 'allow-start')) + ' ]]; then\n'
                 '    echo "Manutenção pendente; consulte o diário BioSuite antes de iniciar Galaxy." >&2\n'
                 '    exit 75\nfi\n')
        with tempfile.NamedTemporaryFile(mode='w', dir=self.base, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text.replace(marker, guard + marker))
            stream.flush();os.fsync(stream.fileno())
        try:
            os.chmod(temporary, 0o755)
            temporary.replace(launcher)
            sync_directory(self.base)
        finally:
            temporary.unlink(missing_ok=True)

    def ensure_database(self):
        self._guard_launcher()
        super().ensure_database()

    def pg(self, binary, database, admin=False):
        return ['runuser', '-u', 'postgres' if admin else DB, '--', binary, '--no-password', '--dbname', database]

    def running(self):
        result = capture(['systemctl', 'show', native.UNIT, '--property=ActiveState', '--value']).strip()
        if result not in ('active', 'inactive', 'failed'):
            raise OperationError('Serviço em transição; aguarde antes da manutenção.')
        return result == 'active'

    def stop(self):
        capture(['systemctl', 'stop', native.UNIT], timeout=180)
        if self.running():
            raise OperationError('O serviço ainda está ativo.')

    def start(self):
        flag = RUNTIME / 'allow-start'
        self._guard_launcher()
        if self.journal.exists():
            write_private(flag, {'authorized_by_controller': True})
        try:
            capture(['systemctl', 'reset-failed', native.UNIT])
            capture(['systemctl', 'start', native.UNIT], timeout=180)
            self.wait_healthy()
        finally:
            flag.unlink(missing_ok=True)

    def snapshot_files(self, folder, metadata):
        if any(p.is_symlink() for p in (DATA / 'datasets').rglob('*')):
            raise OperationError('Links em datasets podem apontar para dados não copiados; use armazenamento local regular.')
        archive_tree(DATA, folder / 'data.tar')
        archive_tree(self.roots['code'], folder / 'code.tar')
        archive_tree(CONFIG, folder / 'config.tar', ['galaxy.yml', 'job_conf.xml'])
        metadata['host'] = host_identity()

    def estimate(self):
        return tree_bytes(DATA) + tree_bytes(self.roots['code']) + int(self.sql('SELECT pg_database_size(current_database())'))

    def check_space(self, info, sizes):
        for key, path in self.roots.items():
            if shutil.disk_usage(path.parent).free < sizes[key + '.tar'] + 128 * 1024 * 1024:
                raise OperationError('Espaço insuficiente no filesystem de ' + str(path))
        database_path = self.sql('SHOW data_directory', admin=True).strip()
        if shutil.disk_usage(database_path).free < info['database_bytes'] * 2 + 128 * 1024 * 1024:
            raise OperationError('Espaço insuficiente no filesystem PostgreSQL.')

    def compatible(self, metadata):
        if any(path.is_mount() for path in self.roots.values()):
            raise OperationError('Restauração nativa exige diretórios comuns, sem ponto de montagem direto em dados/código. Use um destino compatível ou monte o disco no diretório pai.')
        if metadata.get('host') != host_identity():
            raise OperationError('A restauração nativa exige a mesma distribuição, versão e arquitetura do backup.')

    def prepare_files(self, stage, metadata):
        if set(p.name for p in (stage / 'config').iterdir()) != {'galaxy.yml', 'job_conf.xml'} or any(p.is_symlink() or not p.is_file() for p in (stage / 'config').iterdir()):
            raise OperationError('Configurações inesperadas no backup.')
        config = json.loads((stage / 'config/galaxy.yml').read_text())
        local_data_config(config, DATA, self.roots['code'])
        if config['galaxy'].get('database_connection') != 'postgresql:///biosuitegalaxy?host=/var/run/postgresql' or config['galaxy'].get('install_database_connection') != config['galaxy'].get('database_connection'):
            raise OperationError('Banco externo no backup nativo não suportado.')
        plugins = ET.parse(stage / 'config/job_conf.xml').findall('.//plugin')
        if not plugins or any(p.get('load') != 'galaxy.jobs.runners.local:LocalJobRunner' for p in plugins):
            raise OperationError('Backup com executor fora do modo local suportado.')
        config['gravity']['gunicorn']['bind'] = f'127.0.0.1:{self.port}'
        write_private(stage / 'config/galaxy.yml', config)
        if set(p.name for p in (stage / 'config').iterdir()) != {'galaxy.yml', 'job_conf.xml'} or any(p.is_symlink() for p in (stage / 'config').iterdir()):
            raise OperationError('Configurações inesperadas no backup.')

    def promote(self, stage, token, metadata):
        account = pwd.getpwnam(DB)
        moves = []
        try:
            paths = [(stage / key, value) for key, value in self.roots.items()]
            paths += [(stage / 'config' / name, CONFIG / name) for name in ('galaxy.yml', 'job_conf.xml')]
            for source, target in paths:
                new = target.with_name(target.name + '.biosuite-new-' + token)
                old = target.with_name(target.name + '.biosuite-old-' + token)
                if new.exists() or old.exists() or new.is_symlink() or old.is_symlink():
                    raise OperationError('Caminho de staging já existe.')
                if source.is_dir():
                    shutil.copytree(source, new, symlinks=True)
                    owned_tree(new, account.pw_uid, account.pw_gid)
                else:
                    shutil.copyfile(source, new)
                    os.chmod(new, 0o600 if target.name == 'galaxy.yml' else 0o644)
                    os.chown(new, account.pw_uid, account.pw_gid)
                moves.append((target, new, old))
                target.rename(old)
                new.rename(target)
        except BaseException:
            self.undo(moves)
            raise
        return moves

    def recover_files(self, token):
        paths = list(self.roots.values()) + [CONFIG / name for name in ('galaxy.yml', 'job_conf.xml')]
        self.undo([(path, path.with_name(path.name + '.biosuite-new-' + token),
                    path.with_name(path.name + '.biosuite-old-' + token)) for path in paths])

    def undo(self, moves):
        for target, new, old in reversed(moves):
            if old.exists():
                if target.is_dir() and not target.is_symlink():
                    shutil.rmtree(target)
                elif target.exists() or target.is_symlink():
                    target.unlink()
                old.rename(target)
            if new.is_dir():
                shutil.rmtree(new)
            elif new.exists():
                new.unlink()

    def discard(self, moves):
        for _, _, old in moves:
            if old.is_dir():
                shutil.rmtree(old)
            elif old.exists():
                old.unlink()


class DockerBackend(Backend):
    mode = 'docker'

    def __init__(self):
        self.base = containers.BASE
        if not (self.base / '.biosuite-docker').is_file() or not containers._manifest():
            raise OperationError('Instalação Docker gerenciada não detectada.')
        self.lock = self.base / 'install.lock'
        self.journal = self.base / 'maintenance.json'
        self.log = self.base / 'backups.log'
        self.port = containers._manifest()['port']
        self.container = capture(containers.compose('ps', '--all', '--quiet', 'galaxy')).strip()
        self.db_container = capture(containers.compose('ps', '--all', '--quiet', 'db')).strip()
        if not self.container or not self.db_container or '\n' in self.container:
            raise OperationError('Containers gerenciados não estão preparados.')
        self.image = capture(['docker', 'inspect', '--format', '{{.Image}}', self.container]).strip()
        self.db_was_running = self._running(self.db_container)
        self.roots = {'data': Path(capture(['docker', 'volume', 'inspect', '--format', '{{.Mountpoint}}', 'biosuite-galaxy_data']).strip())}
        mounts = json.loads(capture(['docker', 'inspect', '--format', '{{json .Mounts}}', self.container]))
        data = [m for m in mounts if m['Destination'] == '/data']
        if any(m['Destination'] not in ('/data','/run/secrets/db_password','/run/secrets/proxy_ca') for m in mounts):
            raise OperationError('Volumes adicionais exigem backup próprio antes da manutenção.')
        if len(data) != 1 or data[0].get('Name') != 'biosuite-galaxy_data':
            raise OperationError('Volume de dados fora do padrão gerenciado.')

    def _running(self, container):
        return capture(['docker', 'inspect', '--format', '{{.State.Running}}', container]).strip() == 'true'

    def pg(self, binary, database, admin=False):
        return containers.compose('exec', '-T', 'db', binary, '--username', DB, '--no-password', '--dbname', database)

    def ensure_database(self):
        if not self.db_was_running:
            capture(['docker', 'start', self.db_container])
        for attempt in range(30):
            try:
                self.pg_major()
                return
            except OperationError:
                time.sleep(2)
        raise OperationError('PostgreSQL Docker indisponível.')

    def finish_database(self):
        if not self.db_was_running:
            capture(['docker', 'stop', self.db_container], timeout=120)

    def running(self):
        return self._running(self.container)

    def stop(self):
        capture(['docker', 'stop', '--timeout', '120', self.container], timeout=150)
        if self.running():
            raise OperationError('Galaxy Docker ainda está ativo.')

    def start(self):
        capture(containers.compose('up', '-d', '--no-deps', 'galaxy'), timeout=180)
        self.container = capture(containers.compose('ps', '--all', '--quiet', 'galaxy')).strip()
        self.wait_healthy()

    def snapshot_files(self, folder, metadata):
        self._validate_data_config()
        transfer(['docker', 'run', '--rm', '--network', 'none', '--volumes-from', self.container + ':ro',
                  '--entrypoint', 'tar', self.image, '-C', '/data', '-cf', '-', '.'], target=folder / 'data.tar', log=self.log)
        image = capture(['docker', 'commit', self.container]).strip()
        if not re.fullmatch(r'sha256:[a-f0-9]{64}', image):
            raise OperationError('Docker não retornou uma imagem válida.')
        try:
            transfer(['docker', 'image', 'save', image], target=folder / 'image.tar', log=self.log)
        finally:
            capture(['docker', 'image', 'rm', image])
        metadata['image_id'] = image
        metadata['architecture'] = platform.machine()

    def _validate_data_config(self):
        with tempfile.TemporaryDirectory(prefix='biosuite-config-') as folder:
            target = Path(folder) / 'galaxy.json'
            capture(['docker', 'cp', self.container + ':/data/config/galaxy.yml', str(target)])
            config = json.loads(target.read_text())
            # Caminhos absolutos são os do container, não do host.
            galaxy = config['galaxy']
            from urllib.parse import quote
            expected_db = 'postgresql://biosuitegalaxy:' + quote((self.base / 'db-password').read_text().strip(), safe='') + '@db/biosuitegalaxy'
            if galaxy.get('database_connection') != expected_db or galaxy.get('install_database_connection') not in (None, expected_db):
                raise OperationError('Banco fora do PostgreSQL gerenciado no Compose.')
            if galaxy.get('job_config_file'):
                raise OperationError('Configuração de jobs personalizada exige manutenção própria.')
            capture(['docker', 'cp', self.container + ':/galaxy/config', str(Path(folder) / 'code-config')])
            for name in ('object_store_conf.xml','object_store_conf.yml','job_conf.xml'):
                if (Path(folder) / 'code-config' / name).exists():
                    raise OperationError('Configuração de armazenamento/jobs personalizada exige backup próprio.')
            if any(galaxy.get(k) != v for k, v in {'data_dir':'/data', 'file_path':'/data/datasets', 'tool_dependency_dir':'/data/dependencies'}.items()) or any(galaxy.get(k) for k in ('object_store_config', 'object_store_config_file', 'distributed_object_store_config_file', 'library_import_dir')):
                raise OperationError('Backup Docker limitado ao armazenamento local padrão.')

    def estimate(self):
        size = int(capture(['docker', 'image', 'inspect', '--format', '{{.Size}}', self.image]).strip())
        size += int(capture(['docker', 'inspect', '--size', '--format', '{{.SizeRw}}', self.container]).strip())
        data = capture(['docker', 'run', '--rm', '--network', 'none', '--volumes-from', self.container + ':ro', '--entrypoint', 'du', self.image, '--apparent-size', '-sb', '/data'])
        return size + int(data.split()[0]) + int(self.sql('SELECT pg_database_size(current_database())'))

    def check_space(self, info, sizes):
        free = capture(containers.compose('exec', '-T', 'db', 'df', '-Pk', '/var/lib/postgresql/data')).splitlines()[-1].split()[3]
        if int(free) * 1024 < info['database_bytes'] * 2 + 128 * 1024 * 1024:
            raise OperationError('Espaço insuficiente no volume PostgreSQL.')

    def compatible(self, metadata):
        if metadata.get('architecture') != platform.machine() or not re.fullmatch(r'sha256:[a-f0-9]{64}', metadata.get('image_id', '')):
            raise OperationError('Imagem ou arquitetura incompatível.')

    def prepare_files(self, stage, metadata):
        config_dir = stage / 'data/config'
        config_file = config_dir / 'galaxy.yml'
        if config_dir.is_symlink() or config_file.is_symlink() or not config_file.is_file():
            raise OperationError('Configuração Docker inválida no backup.')
        config = json.loads(config_file.read_text())
        from urllib.parse import quote
        password = (self.base / 'db-password').read_text().strip()
        if any(config['galaxy'].get(k) != v for k,v in {'data_dir':'/data','file_path':'/data/datasets','tool_dependency_dir':'/data/dependencies'}.items()):
            raise OperationError('Layout de dados do backup Docker não suportado.')
        config['galaxy']['database_connection'] = 'postgresql://biosuitegalaxy:' + quote(password, safe='') + '@db/biosuitegalaxy'
        if config['galaxy'].get('install_database_connection'):
            config['galaxy']['install_database_connection'] = config['galaxy']['database_connection']
        write_private(stage / 'data/config/galaxy.yml', config)

    def _files(self, action, stage, token):
        from importlib.resources import files
        script = files('biosuite').joinpath('assets/docker-restore.py').read_text()
        command = ['docker', 'run', '--rm', '--network', 'none', '--mount', 'type=volume,src=biosuite-galaxy_data,dst=/data']
        if stage:
            command += ['--mount', f'type=bind,src={stage / "data"},dst=/restore,readonly']
        capture(command + ['--entrypoint', 'python3', self.image, '-c', script, action, token], timeout=3600)

    def promote(self, stage, token, metadata):
        transfer(['docker', 'image', 'load'], source=stage / 'image.tar', log=self.log)
        image = metadata['image_id']
        if capture(['docker', 'image', 'inspect', '--format', '{{.Id}}', image]).strip() != image:
            raise OperationError('Imagem carregada diferente da confirmada.')
        original = (self.base / 'compose.json').read_bytes()
        before = self.base / ('compose-before-' + token + '.json')
        before.write_bytes(original)
        os.chmod(before, 0o600)
        self._files('apply', stage, token)
        try:
            compose = json.loads(original)
            current_env = json.loads(capture(['docker', 'inspect', '--format', '{{json .Config.Env}}', self.container]))
            current_env = dict(value.split('=', 1) for value in current_env if '=' in value)
            environment = compose['services']['galaxy'].setdefault('environment', {})
            for key in ('HTTP_PROXY','HTTPS_PROXY','NO_PROXY','ALL_PROXY','http_proxy','https_proxy','no_proxy','all_proxy'):
                environment[key] = current_env.get(key, '')
            compose['services']['galaxy']['image'] = image
            compose['services']['galaxy'].pop('build', None)
            write_private(self.base / 'compose.json', compose)
        except BaseException:
            self._files('undo', None, token)
            raise
        return (token, original)

    def recover_files(self, token):
        before = self.base / ('compose-before-' + token + '.json')
        if before.is_file():
            self._files('undo-if-present', None, token)
            (self.base / 'compose.json').write_bytes(before.read_bytes())
            before.unlink()

    def undo(self, move):
        token, original = move
        self._files('undo', None, token)
        (self.base / 'compose.json').write_bytes(original)

    def discard(self, move):
        self._files('commit', None, move[0])
        (self.base / ('compose-before-' + move[0] + '.json')).unlink(missing_ok=True)


def backend(mode):
    try:
        if mode == 'native':
            return NativeBackend()
        if mode == 'docker':
            return DockerBackend()
    except (OSError, ValueError, KeyError, ET.ParseError):
        raise OperationError('Configuração gerenciada indisponível ou fora do layout suportado. Consulte diagnóstico e documentação.') from None
    raise OperationError('Modo de backup inválido.')
