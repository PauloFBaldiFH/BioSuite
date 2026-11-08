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
    parser.add_argument('--version', action='version', version='BioSuite 0.5.0')
    commands = parser.add_subparsers(dest='command')
    commands.add_parser('doctor', help='Diagnóstico local em JSON; não certifica prontidão do Galaxy')
    commands.add_parser('plan', help='Prévia das etapas; não executa a instalação do Galaxy')
    commands.add_parser('panel', help='Abre o painel interativo (padrão)')
    galaxy = commands.add_parser('galaxy', help='Instala e gerencia Galaxy nativo ou Docker')
    galaxy_commands = galaxy.add_subparsers(dest='galaxy_command', required=True)
    for name in ('install', 'plan'):
        sub = galaxy_commands.add_parser(name)
        sub.add_argument('--admin-email', required=True)
        sub.add_argument('--port', type=int, default=8080)
        sub.add_argument('--mode', choices=('native', 'docker'), default='native')
        if name == 'install':
            sub.add_argument('--yes', action='store_true', help='Confirma as alterações do plano')
            sub.add_argument('--no-service', action='store_true', help='Somente preparação para execução manual/testes')
    for name in ('status', 'start', 'stop', 'restart', 'logs'):
        galaxy_commands.add_parser(name).add_argument('--mode', choices=('native', 'docker'), default='native')
    galaxy_commands.add_parser('prepare-docker').add_argument('--yes', action='store_true')
    maintenance = commands.add_parser('updates', help='Atualizações do painel e do sistema operacional')
    maintenance_commands = maintenance.add_subparsers(dest='update_command', required=True)
    for name in ('check-panel', 'apt-plan', 'apt-update'):
        maintenance_commands.add_parser(name)
    maintenance_commands.add_parser('apt-upgrade').add_argument('--yes', action='store_true')
    update = maintenance_commands.add_parser('panel')
    update.add_argument('--commit', required=True)
    update.add_argument('--yes', action='store_true')
    connection = commands.add_parser('connection', help='Endereço gratuito pelo broker BioSuite/koha.nexus')
    connection.add_argument('--broker', default='https://biosuite-broker.koha.nexus')
    connection_commands = connection.add_subparsers(dest='connection_command', required=True)
    connection_commands.add_parser('capabilities')
    connection_commands.add_parser('poll')
    for name in ('enroll', 'activate', 'prepare', 'stop', 'reset'):
        connection_commands.add_parser(name).add_argument('--yes', action='store_true')
    request = connection_commands.add_parser('request')
    request.add_argument('--institution', required=True)
    request.add_argument('--email', required=True)
    request.add_argument('--slug', required=True)
    request.add_argument('--port', type=int, default=8080)
    request.add_argument('--yes', action='store_true')
    for name in ('export', 'import'):
        sub = connection_commands.add_parser(name)
        sub.add_argument('--file', type=Path, required=True)
        sub.add_argument('--yes', action='store_true')
    args = parser.parse_args(argv)
    if args.command == 'doctor':
        print(json.dumps(inspect_machine(args.storage).as_dict(), ensure_ascii=False, indent=2))
    elif args.command == 'plan':
        print(installation_plan(inspect_machine(args.storage)))
    elif args.command == 'galaxy':
        from biosuite import containers, native
        from biosuite.operations import OperationError
        import subprocess
        try:
            action = args.galaxy_command
            provider = containers if getattr(args, 'mode', 'native') == 'docker' else native
            if action == 'prepare-docker':
                if not args.yes:
                    parser.error('Use --yes para confirmar a instalação dos pré-requisitos Docker.')
                containers.prepare()
                return 0
            if action in ('plan', 'install'):
                settings = native.NativeSettings(args.admin_email, args.port)
                print(provider.installation_summary(settings))
                if action == 'install':
                    if not args.yes:
                        parser.error('Revise o plano e use --yes para confirmar a instalação.')
                    if args.mode == 'docker':
                        if args.no_service:
                            parser.error('--no-service se aplica somente ao modo nativo.')
                        containers.install(settings)
                    else:
                        native.install(settings, no_service=args.no_service)
            elif action == 'logs':
                print(provider.logs())
            else:
                result = provider.status() if action == 'status' else provider.service(action)
                print(json.dumps(result, ensure_ascii=False, indent=2))
        except (native.NativeError, OperationError, OSError, subprocess.TimeoutExpired) as error:
            print(str(error), file=sys.stderr)
            return 1
    elif args.command == 'updates':
        from biosuite import updates
        from biosuite.operations import OperationError
        try:
            action = args.update_command
            if action == 'check-panel':
                plan = updates.panel_plan()
                print(f'Canal main: {plan.commit}\nInstalado: {plan.current_commit or "origem local"}')
            elif action == 'panel':
                if not args.yes:
                    parser.error('Confirme com --yes após verificar o commit.')
                plan = updates.panel_plan()
                if plan.commit != args.commit:
                    raise OperationError('O canal mudou desde a consulta. Verifique novamente antes de atualizar.')
                updates.update_panel(plan)
            elif action == 'apt-plan':
                print(updates.apt_plan())
            else:
                if action == 'apt-upgrade' and not args.yes:
                    parser.error('Revise apt-plan e confirme com --yes.')
                print(json.dumps(updates.apt('upgrade' if action == 'apt-upgrade' else 'update')))
        except (OperationError, OSError) as error:
            print(str(error), file=sys.stderr)
            return 1
    elif args.command == 'connection':
        from biosuite.connection import BrokerClient, prepare_connector, stop_connector
        from biosuite.operations import OperationError
        try:
            action = args.connection_command
            if action not in ('capabilities', 'poll') and not args.yes:
                parser.error('Esta ação exige confirmação explícita com --yes.')
            client = BrokerClient(args.broker)
            if action == 'request':
                result = client.start(args.institution, args.email, args.slug, args.port)
            elif action == 'prepare':
                prepare_connector()
                result = 'Conector preparado.'
            elif action == 'stop':
                result = stop_connector()
            elif action == 'export':
                result = client.export_recovery(args.file)
            elif action == 'import':
                result = client.import_recovery(args.file)
            else:
                result = getattr(client, 'reset_pending' if action == 'reset' else action)()
            print(result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=2))
        except (OperationError, OSError, ValueError) as error:
            print(str(error), file=sys.stderr)
            return 1
    else:
        from biosuite.panel import BioSuiteApp
        BioSuiteApp(storage=args.storage).run()
    return 0
