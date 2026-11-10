"""Executado em helper sem rede, montando somente o volume gerenciado."""
import os
from pathlib import Path
import re
import shutil
import sys

action, token = sys.argv[1:]
if action not in ('apply', 'undo', 'undo-if-present', 'commit') or not re.fullmatch('[a-f0-9]{16}', token):
    raise SystemExit('Operação inválida')
root = Path('/data')
old = root / ('.biosuite-old-' + token)

def remove(path):
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()

if action == 'apply':
    old.mkdir(mode=0o700)
    moved, created = [], []
    try:
        for path in list(root.iterdir()):
            if path != old:
                path.rename(old / path.name)
                moved.append(path.name)
        for source in Path('/restore').iterdir():
            target = root / source.name
            created.append(target)
            if source.is_symlink():
                os.symlink(os.readlink(source), target)
            elif source.is_dir():
                shutil.copytree(source, target, symlinks=True)
            else:
                shutil.copy2(source, target, follow_symlinks=False)
        for parent, dirs, files in os.walk(root, followlinks=False):
            if Path(parent) == old or old in Path(parent).parents:
                dirs[:] = []
                continue
            os.chown(parent, 1000, 1000)
            for name in dirs + files:
                if Path(parent) / name != old:
                    os.chown(Path(parent) / name, 1000, 1000, follow_symlinks=False)
    except BaseException:
        for path in created:
            if path.exists() or path.is_symlink():
                remove(path)
        for name in moved:
            (old / name).rename(root / name)
        old.rmdir()
        raise
elif action in ('undo', 'undo-if-present'):
    if action == 'undo-if-present' and not old.exists():
        raise SystemExit(0)
    if not old.is_dir() or old.is_symlink():
        raise SystemExit('Rollback ausente')
    for path in root.iterdir():
        if path != old:
            remove(path)
    for path in list(old.iterdir()):
        path.rename(root / path.name)
    old.rmdir()
else:
    if old.is_symlink():
        raise SystemExit('Rollback inválido')
    shutil.rmtree(old)
