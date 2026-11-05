#!/usr/bin/env bash
# Instala somente o painel BioSuite no checkout local; não altera serviços.
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if ! command -v python3 >/dev/null 2>&1; then
    echo 'Python 3.10+ é necessário. No Ubuntu: sudo apt install python3 python3-venv' >&2
    exit 1
fi
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else "Python 3.10+ é necessário.")'
if [[ ! -d "$project_dir/.venv" ]]; then
    if ! python3 -m venv "$project_dir/.venv"; then
        echo 'Não foi possível criar o ambiente Python. No Ubuntu, instale python3-venv e tente novamente.' >&2
        exit 1
    fi
fi
if [[ ! -x "$project_dir/.venv/bin/python" ]]; then
    echo 'O diretório .venv existe, mas não contém um Python utilizável. Verifique-o antes de continuar.' >&2
    exit 1
fi
"$project_dir/.venv/bin/python" -m pip install --disable-pip-version-check "$project_dir"
"$project_dir/.venv/bin/biosuite" --help
printf '\nPainel instalado. Abra com: %q\n' "$project_dir/.venv/bin/biosuite"
printf 'Este bootstrap não instala Galaxy, PostgreSQL ou ferramentas científicas.\n'
