"""Interface de terminal e comandos de diagnóstico."""

import argparse
import json
from pathlib import Path
import sys

from biosuite.preflight import inspect_machine, installation_plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='BioSuite — painel modular para Galaxy')
    parser.add_argument('--storage', type=Path, default=Path.cwd(),
                        help='Caminho onde os dados serão armazenados; usado para medir espaço')
    parser.add_argument('--version', action='version', version='BioSuite 0.4.0')
    commands = parser.add_subparsers(dest='command')
    commands.add_parser('doctor', help='Diagnóstico local em JSON; não certifica prontidão do Galaxy')
    commands.add_parser('plan', help='Prévia das etapas; não executa a instalação do Galaxy')
    commands.add_parser('panel', help='Abre o painel interativo (padrão)')
    galaxy = commands.add_parser('galaxy', help='Instala e gerencia o Galaxy nativo')
    galaxy_commands = galaxy.add_subparsers(dest='galaxy_command', required=True)
    for name in ('install', 'plan'):
        sub = galaxy_commands.add_parser(name)
        sub.add_argument('--admin-email', required=True)
        sub.add_argument('--port', type=int, default=8080)
        if name == 'install':
            sub.add_argument('--yes', action='store_true', help='Confirma as alterações do plano')
            sub.add_argument('--no-service', action='store_true', help='Somente preparação para execução manual/testes')
    for name in ('status', 'start', 'stop', 'restart', 'logs'):
        galaxy_commands.add_parser(name)
    args = parser.parse_args(argv)
    if args.command == 'doctor':
        print(json.dumps(inspect_machine(args.storage).as_dict(), ensure_ascii=False, indent=2))
    elif args.command == 'plan':
        print(installation_plan(inspect_machine(args.storage)))
    elif args.command == 'galaxy':
        from biosuite import native
        import subprocess
        try:
            action = args.galaxy_command
            if action in ('plan', 'install'):
                settings = native.NativeSettings(args.admin_email, args.port)
                print(native.installation_summary(settings))
                if action == 'install':
                    if not args.yes:
                        parser.error('Revise o plano e use --yes para confirmar a instalação.')
                    native.install(settings, no_service=args.no_service)
            elif action == 'logs':
                print(native.logs())
            else:
                result = native.status() if action == 'status' else native.service(action)
                print(json.dumps(result, ensure_ascii=False, indent=2))
        except (native.NativeError, OSError, subprocess.TimeoutExpired) as error:
            print(str(error), file=sys.stderr)
            return 1
    else:
        from biosuite.panel import BioSuiteApp
        BioSuiteApp(storage=args.storage).run()
    return 0
