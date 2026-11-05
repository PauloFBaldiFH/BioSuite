"""Interface de terminal e comandos de diagnóstico."""

import argparse
import json
from pathlib import Path

from biosuite.preflight import inspect_machine, installation_plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='BioSuite — painel modular para Galaxy')
    parser.add_argument('--storage', type=Path, default=Path.cwd(),
                        help='Caminho onde os dados serão armazenados; usado para medir espaço')
    parser.add_argument('--version', action='version', version='BioSuite 0.2.0')
    commands = parser.add_subparsers(dest='command')
    commands.add_parser('doctor', help='Diagnóstico local em JSON; não certifica prontidão do Galaxy')
    commands.add_parser('plan', help='Prévia das etapas; não executa a instalação do Galaxy')
    commands.add_parser('panel', help='Abre o painel interativo (padrão)')
    args = parser.parse_args(argv)
    if args.command == 'doctor':
        print(json.dumps(inspect_machine(args.storage).as_dict(), ensure_ascii=False, indent=2))
    elif args.command == 'plan':
        print(installation_plan(inspect_machine(args.storage)))
    else:
        from biosuite.panel import BioSuiteApp
        BioSuiteApp(storage=args.storage).run()
    return 0
