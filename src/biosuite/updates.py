"""Atualização do painel e manutenção APT, sem atualizar Galaxy implicitamente."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import sys
import tempfile

from biosuite.operations import OperationError, capture, lock, require_root, run_logged

REPOSITORY = 'https://github.com/PauloFBaldiFH/BioSuite.git'
APT_LOG = Path('/var/log/biosuite-install/apt.log')


@dataclass(frozen=True)
class PanelUpdate:
    commit: str
    prefix: Path
    bin_dir: Path
    current_commit: str | None


def panel_plan() -> PanelUpdate:
    receipt = Path(sys.executable).parent.parent / 'biosuite-install.json'
    try:
        data = json.loads(receipt.read_text())
        prefix, bin_dir = Path(data['prefix']), Path(data['bin_dir'])
    except (OSError, ValueError, KeyError, TypeError):
        raise OperationError('Esta instalação não tem recibo de atualização. Reexecute o bootstrap atual uma vez; '
                             'checkouts de desenvolvimento continuam sendo atualizados pelo Git.') from None
    if not prefix.is_absolute() or not bin_dir.is_absolute() or prefix == Path('/'):
        raise OperationError('Recibo de instalação inválido.')
    sha = capture(['git', 'ls-remote', REPOSITORY, 'refs/heads/main']).split()
    if len(sha) != 2 or not re.fullmatch(r'[0-9a-f]{40}', sha[0]) or sha[1] != 'refs/heads/main':
        raise OperationError('Não foi possível determinar o commit do canal main.')
    return PanelUpdate(sha[0], prefix, bin_dir, data.get('commit'))


def update_panel(plan: PanelUpdate, output=print):
    if not re.fullmatch(r'[0-9a-f]{40}', plan.commit):
        raise OperationError('Commit de atualização inválido.')
    log = plan.prefix / 'panel-update.log'
    with lock(plan.prefix / '.panel-update.lock'), tempfile.TemporaryDirectory(prefix='biosuite-update-') as folder:
        source = Path(folder)
        env = {**os.environ, 'GIT_TERMINAL_PROMPT': '0'}
        for command in (
            ['git', 'init', str(source)],
            ['git', '-C', str(source), 'remote', 'add', 'origin', REPOSITORY],
            ['git', '-C', str(source), 'fetch', '--depth', '1', 'origin', plan.commit],
            ['git', '-C', str(source), 'checkout', '--detach', 'FETCH_HEAD'],
        ):
            run_logged(command, log, output, env=env)
        if capture(['git', '-C', str(source), 'rev-parse', 'HEAD']).strip() != plan.commit:
            raise OperationError('O commit baixado não corresponde ao plano confirmado.')
        run_logged(['bash', str(source / 'installer'), '--source', str(source), '--prefix', str(plan.prefix),
                    '--bin-dir', str(plan.bin_dir), '--no-launch'], log, output, env=env)
    output('Painel atualizado. Saia e abra biosuite-config novamente. Galaxy e seus dados não foram atualizados.')


def apt_plan() -> str:
    return capture(['apt-get', '--simulate', 'upgrade'], timeout=120)


def apt(action: str, output=print) -> dict:
    if action not in ('update', 'upgrade'):
        raise OperationError('Ação APT inválida.')
    require_root()
    command = ['apt-get', '-o', 'DPkg::Lock::Timeout=120']
    if action == 'upgrade':
        command += ['-y', '-o', 'Dpkg::Options::=--force-confdef', '-o', 'Dpkg::Options::=--force-confold']
    command.append(action)
    with lock(Path('/run/lock/biosuite-os-update.lock')):
        run_logged(command, APT_LOG, output, env={**os.environ, 'DEBIAN_FRONTEND': 'noninteractive'})
    return {'action': action, 'completed': True, 'reboot_required': Path('/var/run/reboot-required').exists()}
