#!/usr/bin/env bash
# Executar como root em um container descartável Ubuntu/Debian.
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
test_root=$(mktemp -d)
trap 'rm -rf -- "$test_root"' EXIT
args=(--source "$project_dir" --prefix "$test_root/app" --bin-dir "$test_root/bin" --no-launch)
# Simula download via pipe: o instalador não pode depender do seu próprio caminho.
cat "$project_dir/installer" | bash -s -- "${args[@]}"
first=$(readlink "$test_root/app/current")
"$test_root/bin/biosuite" doctor
"$test_root/bin/biosuite-config" --version
"$test_root/bin/biosuite" plan
PYTHONPATH="$project_dir/src" "$test_root/app/current/bin/python" -m unittest discover -s "$project_dir/tests" -v
# Reinstalação precisa validar outra versão e preservar a anterior.
bash "$project_dir/installer" "${args[@]}"
second=$(readlink "$test_root/app/current")
[[ "$first" != "$second" && -x "$first/bin/biosuite" ]]
"$test_root/bin/biosuite" --version
"$test_root/bin/biosuite-config" --version
bash "$project_dir/installer" --check
