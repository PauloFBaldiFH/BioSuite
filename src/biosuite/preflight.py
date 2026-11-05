"""Diagnóstico local de leitura; nenhum serviço é iniciado ou modificado."""

from dataclasses import asdict, dataclass
import os
from pathlib import Path
import platform
import shutil
import sys


@dataclass(frozen=True)
class Machine:
    system: str
    architecture: str
    distribution: str
    version: str
    python: str
    wsl: bool
    memory_gib: float | None
    free_gib: float
    storage_path: str
    systemd_active: bool
    commands: dict[str, bool]

    def as_dict(self) -> dict:
        return asdict(self)


def storage_parent(path: Path) -> Path:
    path = path.expanduser().absolute()
    while not path.exists():
        path = path.parent
    if not path.is_dir():
        path = path.parent
    return path


def inspect_machine(storage: Path) -> Machine:
    try:
        distro = platform.freedesktop_os_release()
    except OSError:
        distro = {}
    try:
        memory = next(
            int(line.split()[1]) / 1024**2
            for line in Path('/proc/meminfo').read_text().splitlines()
            if line.startswith('MemTotal:')
        )
    except (OSError, StopIteration, ValueError, IndexError):
        memory = None
    try:
        systemd = Path('/proc/1/comm').read_text().strip() == 'systemd'
    except OSError:
        systemd = False
    parent = storage_parent(storage)
    return Machine(
        system=platform.system(), architecture=platform.machine(),
        distribution=distro.get('ID', 'desconhecida'),
        version=distro.get('VERSION_ID', 'desconhecida'),
        python='.'.join(map(str, sys.version_info[:3])),
        wsl='microsoft' in platform.release().lower() or bool(os.getenv('WSL_DISTRO_NAME')),
        memory_gib=round(memory, 1) if memory is not None else None,
        free_gib=round(shutil.disk_usage(parent).free / 1024**3, 1),
        storage_path=str(parent), systemd_active=systemd,
        commands={name: shutil.which(name) is not None for name in
                  ('git', 'systemctl', 'psql', 'rclone', 'cloudflared')},
    )


def installation_plan(machine: Machine) -> str:
    target = (machine.system == 'Linux' and machine.distribution == 'ubuntu'
              and machine.version == '24.04' and machine.architecture == 'x86_64')
    observations = [
        'BIO SUITE • PLANO DE INSTALAÇÃO',
        '',
        'Prévia: a instalação do Galaxy ainda não está implementada.',
        'Nenhum comando deste plano será executado.',
        '',
        f'Alvo inicial: Ubuntu 24.04 x86_64 — {"corresponde" if target else "esta máquina está fora do alvo inicial"}.',
        f'Systemd como PID 1: {"sim" if machine.systemd_active else "não; revisar antes de instalar serviços"}.',
        f'RAM detectada: {machine.memory_gib if machine.memory_gib is not None else "desconhecida"} GiB.',
        f'Disco livre: {machine.free_gib} GiB em {machine.storage_path}.',
        'Recursos necessários dependem das ferramentas, datasets e bases escolhidas.',
        '',
        '1. Verificar sistema, recursos, portas e instalação existente.',
        '2. Selecionar e fixar uma release estável do Galaxy; validar seus requisitos.',
        '3. Apresentar pacotes, caminhos e alterações de serviços para confirmação.',
        '4. Preparar usuário de serviço, PostgreSQL e ambiente Python separado.',
        '5. Instalar e configurar Galaxy usando os mecanismos oficiais da release.',
        '6. Configurar dependências isoladas e limites de CPU/memória para jobs.',
        '7. Registrar serviço, iniciar e testar uma análise pequena.',
        '',
        'QIIME 2, IQ-TREE e bases científicas serão instalados apenas por escolha.',
        'Backups em nuvem e publicação por tunnel permanecem desativados até configuração.',
    ]
    return '\n'.join(observations)
