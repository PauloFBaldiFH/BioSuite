#!/usr/bin/env bash
# Instalação nativa inicial; nunca atualiza uma release nem substitui dados existentes.
set -euo pipefail
umask 027
BASE=/opt/biosuite-galaxy
DATA=/var/lib/biosuite-galaxy
CONFIG=/etc/biosuite/galaxy.yml
USER_NAME=biosuitegalaxy
RELEASE=v26.1.2
COMMIT=391641a4e121216de4764ffd12b8c666859460ea
email='' port=8080 no_service=0 yes=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --admin-email|--port)
            [[ $# -ge 2 ]] || { echo 'Valor ausente.' >&2; exit 2; }
            case "$1" in --admin-email) email=$2 ;; --port) port=$2 ;; esac
            shift 2 ;;
        --no-service) no_service=1; shift ;;
        --yes) yes=1; shift ;;
        *) echo "Opção desconhecida: $1" >&2; exit 2 ;;
    esac
done
[[ "$email" =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]] || { echo 'Informe um e-mail de administrador válido.' >&2; exit 2; }
[[ "$port" =~ ^[0-9]{4,5}$ ]] && ((10#$port >= 1024 && 10#$port <= 65535)) || { echo 'Porta inválida (1024–65535).' >&2; exit 2; }
[[ "$yes" == 1 ]] || { echo 'É necessário confirmar o plano com --yes.' >&2; exit 2; }
[[ "$EUID" == 0 ]] || { echo 'Abra o painel com sudo biosuite-config para instalar o sistema.' >&2; exit 1; }
. /etc/os-release
case "$ID:$VERSION_ID:$(uname -m)" in
    ubuntu:22.04:x86_64|ubuntu:24.04:x86_64|debian:12:x86_64|debian:13:x86_64) ;;
    *) echo 'Sistema fora da matriz Ubuntu 22.04/24.04 e Debian 12/13, x86_64.' >&2; exit 1 ;;
esac
if [[ "$no_service" == 0 && "$(cat /proc/1/comm)" != systemd ]]; then
    echo 'Systemd precisa estar ativo. --no-service prepara somente os arquivos, para execução manual/testes.' >&2
    exit 1
fi
if [[ -e "$BASE" && ! -f "$BASE/.biosuite-native" ]]; then
    echo "O caminho $BASE já existe e não pertence a este instalador." >&2; exit 1
fi
if [[ ! -f "$BASE/.biosuite-native" ]]; then
    for path in "$DATA" "$CONFIG" /etc/systemd/system/biosuite-galaxy.service; do
        [[ ! -e "$path" ]] || { echo "Recurso existente não será adotado: $path" >&2; exit 1; }
    done
    if getent passwd "$USER_NAME" >/dev/null; then
        echo "A conta $USER_NAME já existe. Não será modificada." >&2; exit 1
    fi
fi
mkdir -p "$BASE"
chmod 755 "$BASE"
exec 9>"$BASE/install.lock"
flock -n 9 || { echo 'Outra instalação está em andamento.' >&2; exit 1; }
[[ ! -f "$BASE/maintenance.json" ]] || { echo 'Manutenção pendente. Confira o diário antes de instalar.' >&2; exit 1; }
if [[ ! -f "$BASE/.biosuite-native" ]]; then
    printf '%s\n' "$COMMIT" >"$BASE/.biosuite-native"
fi
[[ "$(cat "$BASE/.biosuite-native")" == "$COMMIT" ]] || { echo 'Release diferente: atualização exige procedimento próprio.' >&2; exit 1; }
if [[ -f "$CONFIG" ]]; then
    python3 - "$CONFIG" "$email" "$port" <<'PY'
import json, sys
c = json.load(open(sys.argv[1]))
if c['galaxy']['admin_users'] != sys.argv[2] or c['gravity']['gunicorn']['bind'] != '127.0.0.1:' + sys.argv[3]:
    sys.exit('Configuração existente é diferente. Não será sobrescrita.')
if not 16 <= len(c['galaxy'].get('id_secret', '')) <= 56:
    sys.exit('O segredo interno existente é incompatível. Revise a configuração; ele não será alterado automaticamente.')
PY
fi
if [[ -f "$BASE/complete" ]]; then
    echo 'Galaxy já foi preparado por este instalador. Dados, configuração e release serão preservados.'
else
    python3 - "$BASE" "$DATA" "$port" <<'PY'
import os, shutil, socket, sys
if shutil.disk_usage(sys.argv[1]).free < 15 * 1024**3:
    sys.exit('A instalação base exige pelo menos 15 GiB livres; ferramentas e datasets precisam de espaço adicional.')
with socket.socket() as probe:
    try:
        probe.bind(('127.0.0.1', int(sys.argv[3])))
    except OSError:
        sys.exit('A porta escolhida já está em uso. A instalação não continuará.')
PY
    echo '[1/6] Instalando pré-requisitos do sistema e PostgreSQL...'
    apt-get update 9>&-
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        git ca-certificates python3 python3-venv python3-dev build-essential \
        postgresql postgresql-client libpq-dev libxml2-dev libxslt1-dev zlib1g-dev libffi-dev libssl-dev util-linux 9>&-
    python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else "Python 3.10+ é necessário")'
    if ! getent passwd "$USER_NAME" >/dev/null; then
        useradd --system --user-group --home-dir "$DATA" --shell /bin/bash "$USER_NAME"
    fi
    [[ "$(getent passwd "$USER_NAME" | cut -d: -f6)" == "$DATA" ]] || { echo 'Home da conta de serviço não corresponde ao esperado.' >&2; exit 1; }
    install -d -o "$USER_NAME" -g "$USER_NAME" -m 750 "$DATA" /var/log/biosuite-galaxy
    install -d -m 755 /etc/biosuite
    if [[ "$no_service" == 0 ]]; then
        systemctl start postgresql 9>&-
    else
        # Inicia somente o cluster local padrão nos testes sem systemd.
        pg_ctlcluster "$(pg_lsclusters --no-header | awk 'NR==1 {print $1}')" main start 9>&- || pg_isready
    fi
    echo '[2/6] Preparando banco PostgreSQL com autenticação local peer...'
    if [[ ! -f "$BASE/role-owned" ]]; then
        role_exists=$(runuser -u postgres -- psql --no-password -Atc "SELECT 1 FROM pg_roles WHERE rolname='biosuitegalaxy'")
        [[ "$role_exists" != 1 ]] || {
            echo 'A role PostgreSQL biosuitegalaxy já existe e não será adotada.' >&2; exit 1;
        }
        runuser -u postgres -- createuser --no-password --no-superuser --no-createdb --no-createrole "$USER_NAME"
        touch "$BASE/role-owned"
    fi
    if [[ ! -f "$BASE/database-owned" ]]; then
        database_exists=$(runuser -u postgres -- psql --no-password -Atc "SELECT 1 FROM pg_database WHERE datname='biosuitegalaxy'")
        [[ "$database_exists" != 1 ]] || {
            echo 'O banco biosuitegalaxy já existe e não será adotado.' >&2; exit 1;
        }
        runuser -u postgres -- createdb --no-password --owner "$USER_NAME" biosuitegalaxy
        touch "$BASE/database-owned"
    fi
    echo "[3/6] Obtendo Galaxy $RELEASE e verificando o commit..."
    if [[ ! -d "$BASE/galaxy/.git" ]]; then
        if [[ -d "$BASE/galaxy" && -n "$(find "$BASE/galaxy" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
            echo 'O diretório de código contém arquivos sem checkout válido. Revise-o antes de retomar.' >&2; exit 1
        fi
        install -d -o "$USER_NAME" -g "$USER_NAME" "$BASE/galaxy"
        runuser -u "$USER_NAME" -- env GIT_TERMINAL_PROMPT=0 git clone --depth 1 --branch "$RELEASE" \
            https://github.com/galaxyproject/galaxy.git "$BASE/galaxy"
    fi
    [[ "$(runuser -u "$USER_NAME" -- git -C "$BASE/galaxy" rev-parse HEAD)" == "$COMMIT" ]] || {
        echo 'O checkout não corresponde ao commit esperado. Nenhuma atualização automática será feita.' >&2; exit 1;
    }
    if [[ "$(runuser -u "$USER_NAME" -- git -C "$BASE/galaxy" rev-parse --abbrev-ref HEAD)" == HEAD ]]; then
        # O bootstrap upstream reconhece release_* como produção, sem dependências de desenvolvimento.
        runuser -u "$USER_NAME" -- git -C "$BASE/galaxy" switch -c release_26.1
    fi
    echo '[4/6] Configurando Galaxy, dados e execução local dos jobs...'
    if [[ ! -f "$CONFIG" ]]; then
        python3 - "$CONFIG" "$email" "$port" <<'PY'
import json, secrets, sys
from pathlib import Path
data = '/var/lib/biosuite-galaxy'
root = '/opt/biosuite-galaxy/galaxy'
config = {
 'gravity': {'galaxy_root': root, 'virtualenv': root + '/.venv', 'log_dir': '/var/log/biosuite-galaxy',
             'gunicorn': {'bind': '127.0.0.1:' + sys.argv[3], 'workers': 1}},
 'galaxy': {'database_connection': 'postgresql:///biosuitegalaxy?host=/var/run/postgresql',
            'install_database_connection': 'postgresql:///biosuitegalaxy?host=/var/run/postgresql',
            'data_dir': data, 'managed_config_dir': data + '/config',
            'file_path': data + '/datasets', 'new_file_path': data + '/tmp',
            'job_working_directory': data + '/jobs', 'tool_dependency_dir': data + '/dependencies',
            'tool_config_file': root + '/config/tool_conf.xml.sample',
            'shed_tool_config_file': data + '/config/shed_tool_conf.xml',
            'job_config_file': '/etc/biosuite/job_conf.xml',
            'conda_auto_init': True, 'conda_auto_install': True,
            'admin_users': sys.argv[2], 'id_secret': secrets.token_hex(16),
            'allow_user_creation': True, 'check_migrate_databases': False}}
with open(sys.argv[1], 'x') as stream:
    json.dump(config, stream, indent=2)
PY
        chown "$USER_NAME:$USER_NAME" "$CONFIG"
        chmod 600 "$CONFIG"
    fi
    if [[ ! -f /etc/biosuite/job_conf.xml ]]; then
        cat >/etc/biosuite/job_conf.xml <<'XML'
<?xml version="1.0"?>
<job_conf>
  <plugins><plugin id="local" type="runner" load="galaxy.jobs.runners.local:LocalJobRunner" workers="2"/></plugins>
  <destinations default="local"><destination id="local" runner="local"><param id="local_slots">1</param></destination></destinations>
</job_conf>
XML
        chmod 644 /etc/biosuite/job_conf.xml
    fi
    echo '[5/6] Instalando dependências fixadas e interface pré-compilada oficial...'
    # Índice adicional suportado pelo upstream; usa PyPI para todos os wheels, com TLS verificado.
    runuser -u "$USER_NAME" -- env GALAXY_CONFIG_FILE="$CONFIG" GALAXY_INSTALL_PREBUILT_CLIENT=1 \
        GALAXY_WHEELS_INDEX_URL=https://pypi.org/simple \
        bash -c 'cd /opt/biosuite-galaxy/galaxy; sh scripts/common_startup.sh'
    echo '[6/6] Aplicando migrações oficiais do Galaxy...'
    runuser -u "$USER_NAME" -- env GALAXY_CONFIG_FILE="$CONFIG" \
        bash -c 'set -e; cd /opt/biosuite-galaxy/galaxy; sh manage_db.sh --galaxy-config /etc/biosuite/galaxy.yml init; sh manage_db.sh --galaxy-config /etc/biosuite/galaxy.yml upgrade'
    runuser -u "$USER_NAME" -- psql --no-password -d biosuitegalaxy -Atc 'SELECT count(*) FROM galaxy_user'
    touch "$BASE/complete"
fi
python3 - "$BASE/state.json" "$port" <<'PY'
import json, sys
with open(sys.argv[1], 'w') as stream:
    json.dump({'version': '26.1.2', 'port': int(sys.argv[2])}, stream)
PY
chmod 644 "$BASE/state.json"
cat >"$BASE/start" <<'SH'
#!/bin/sh
set -e
cd /opt/biosuite-galaxy/galaxy
# BioSuite maintenance gate
if [[ -f /opt/biosuite-galaxy/maintenance.json && ! -f /run/biosuite-backup/allow-start ]]; then
    echo 'Manutenção pendente; consulte o diário BioSuite antes de iniciar Galaxy.' >&2
    exit 75
fi
export GALAXY_CONFIG_FILE=/etc/biosuite/galaxy.yml
exec sh run.sh --skip-wheels --skip-client-build --skip-tool-dependency-initialization
SH
chmod 755 "$BASE/start"
if [[ -f /etc/systemd/system/biosuite-galaxy.service ]] && ! grep -Fxq '# BioSuite managed service' /etc/systemd/system/biosuite-galaxy.service; then
    echo 'A unidade systemd existente não é gerenciada pelo BioSuite.' >&2; exit 1
fi
cat >/etc/systemd/system/biosuite-galaxy.service <<'UNIT'
# BioSuite managed service
[Unit]
Description=BioSuite Galaxy
Requires=postgresql.service
After=network.target postgresql.service
[Service]
Type=simple
User=biosuitegalaxy
Group=biosuitegalaxy
WorkingDirectory=/opt/biosuite-galaxy/galaxy
ExecStart=/opt/biosuite-galaxy/start
Restart=on-failure
RestartSec=10
TimeoutStopSec=120
KillMode=control-group
NoNewPrivileges=true
UMask=0027
[Install]
WantedBy=multi-user.target
UNIT
if [[ "$no_service" == 1 ]]; then
    echo 'Arquivos preparados; serviço NÃO iniciado. Para execução manual: runuser -u biosuitegalaxy -- /opt/biosuite-galaxy/start'
else
    systemctl daemon-reload
    systemctl enable --now biosuite-galaxy.service
    echo 'Aguardando resposta funcional da API e da interface do Galaxy...'
    python3 - "$port" <<'PY'
import json, sys, time, urllib.request
from urllib.error import URLError
base = 'http://127.0.0.1:' + sys.argv[1]
for attempt in range(120):
    try:
        with urllib.request.urlopen(base + '/api/version', timeout=4) as r:
            version = json.load(r)
        with urllib.request.urlopen(base + '/', timeout=4) as r:
            html = r.read(2 * 1024 * 1024).lower()
        if version.get('version_major') == '26.1' and b'<html' in html:
            print('Galaxy respondeu à API de versão e entregou a interface HTML.')
            break
    except (URLError, OSError, ValueError):
        pass
    time.sleep(3)
else:
    sys.exit('Galaxy não ficou saudável. Consulte: journalctl -u biosuite-galaxy.service e /var/log/biosuite-galaxy')
PY
fi
printf 'Release fixada: %s. Administrador: cadastre-se no Galaxy com o e-mail %s.\n' "$RELEASE" "$email"
printf 'Acesso local na porta %s. Nenhuma ferramenta científica ou publicação externa foi solicitada.\n' "$port"
