"""Formato privado de backup, checksums e extração sem travessia de caminhos."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile

from biosuite.operations import OperationError

FORMAT = 'biosuite-backup-v1'
PAYLOADS = {'native': {'database.dump', 'data.tar', 'code.tar', 'config.tar', 'inventory.json'},
            'docker': {'database.dump', 'data.tar', 'image.tar', 'inventory.json'}}


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_private(path, value):
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', prefix='.' + path.name + '.', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def seal(folder, metadata):
    entries = {}
    for name in sorted(PAYLOADS[metadata['mode']]):
        path = folder / name
        os.chmod(path, 0o600)
        entries[name] = {'sha256': digest(path), 'bytes': path.stat().st_size}
        with path.open('rb') as stream:
            os.fsync(stream.fileno())
    write_private(folder / 'manifest.json', {'format': FORMAT, **metadata, 'payloads': entries})


def verify(folder):
    folder = Path(folder).expanduser().resolve()
    manifest = folder / 'manifest.json'
    if manifest.is_symlink() or manifest.stat().st_size > 65536:
        raise OperationError('Manifesto inválido.')
    try:
        info = json.loads(manifest.read_text())
        mode = info['mode']
        if not isinstance(info.get('database_bytes'), int) or info['database_bytes'] < 0 or not isinstance(info.get('pg_major'), int) or not isinstance(info.get('galaxy_release'), str):
            raise ValueError
        if info['format'] != FORMAT or set(info['payloads']) != PAYLOADS[mode]:
            raise ValueError
        for name, entry in info['payloads'].items():
            path = folder / name
            if path.is_symlink() or not path.is_file() or path.stat().st_size != entry['bytes'] or digest(path) != entry['sha256']:
                raise OperationError('Checksum ou tamanho inválido: ' + name)
    except (KeyError, TypeError, ValueError):
        raise OperationError('Formato de backup inválido ou não suportado.') from None
    return info


def _name(name):
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or '\\' in name or '\x00' in name:
        raise OperationError('Arquivo contém caminho inseguro.')
    return path


def _inspect_tar(path, *, data=False):
    size = 0
    seen = set()
    links = set()
    members = []
    regular = set()
    with tarfile.open(path, 'r:') as archive:
        for member in archive:
            name = _name(member.name)
            if name == PurePosixPath('.') and member.isdir():
                continue
            if name == PurePosixPath('.') or str(name) in seen or not (member.isdir() or member.isfile() or member.issym() or member.islnk()):
                raise OperationError('Arquivo contém entrada duplicada ou tipo inseguro.')
            if data and name.parts and name.parts[0] == 'datasets' and member.issym():
                raise OperationError('Symlink em datasets exige backup externo próprio.')
            seen.add(str(name))
            if member.issym() or member.islnk():
                links.add(name)
            if member.islnk():
                _name(member.linkname)
            if member.isfile():
                regular.add(name)
            members.append((name, member))
            size += member.size
    # Ordem das entradas não pode permitir escrita através de um link.
    for name, member in members:
        if any(parent in links for parent in name.parents):
            raise OperationError('Arquivo tenta escrever através de um link.')
        if member.islnk():
            target = _name(member.linkname)
            if target not in regular:
                raise OperationError('Hardlink não aponta para um arquivo regular do backup.')
    return size


def inspect_tar(path, *, data=False):
    try:
        return _inspect_tar(path, data=data)
    except (tarfile.TarError, EOFError):
        raise OperationError('Arquivo tar inválido ou truncado.') from None


def extract_tar(path, destination):
    inspect_tar(path)
    destination = Path(destination)
    destination.mkdir(mode=0o700)
    links = []
    timestamps = []
    with tarfile.open(path, 'r:') as archive:
        for member in archive:
            name = _name(member.name)
            if name == PurePosixPath('.'):
                continue
            target = destination.joinpath(*name.parts)
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
            if member.isdir():
                target.mkdir(exist_ok=True, mode=0o750)
            elif member.isfile():
                with archive.extractfile(member) as source, target.open('xb') as output:
                    shutil.copyfileobj(source, output, 1024 * 1024)
                os.chmod(target, member.mode & 0o750)
            else:
                links.append((target, member))
            if not member.issym():
                timestamps.append((target, member.mtime))
    # Links só são criados depois de todas as escritas. Nunca são seguidos.
    for target, member in links:
        if member.issym():
            os.symlink(member.linkname, target)
        else:
            os.link(destination.joinpath(*_name(member.linkname).parts), target)
    for target, modified in sorted(timestamps, key=lambda item: len(item[0].parts), reverse=True):
        os.utime(target, (modified, modified), follow_symlinks=False)


def archive_tree(source, target, names=None):
    with tarfile.open(target, 'w', dereference=False) as archive:
        for name in (names if names is not None else sorted(p.name for p in Path(source).iterdir())):
            archive.add(Path(source) / name, arcname=name, recursive=True)
    inspect_tar(target)
