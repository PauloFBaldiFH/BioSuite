#!/usr/bin/env bash
# Somente em container/VM descartável como root. Instala Galaxy real.
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
port=${BIOSUITE_SMOKE_PORT:-8080}
systemd_mode=${BIOSUITE_SMOKE_SYSTEMD:-0}
[[ "$systemd_mode" == 0 || "$systemd_mode" == 1 ]] || { echo 'BIOSUITE_SMOKE_SYSTEMD deve ser 0 ou 1.' >&2; exit 2; }
runner=''
service_requested=0
cleanup() {
    code=$?
    trap - EXIT
    if [[ "$code" != 0 ]]; then
        for log in /var/log/biosuite-install/galaxy.log /tmp/biosuite-galaxy-smoke.log; do
            [[ ! -f "$log" ]] || tail -n 100 "$log" >&2
        done
    fi
    if [[ -n "$runner" ]]; then
        kill -- -"$runner" 2>/dev/null || true
    elif [[ "$service_requested" == 1 && -f /opt/biosuite-galaxy/complete ]]; then
        biosuite-config galaxy stop >/dev/null 2>&1 || true
    fi
    exit "$code"
}
trap cleanup EXIT
if [[ "$systemd_mode" == 1 && "$(cat /proc/1/comm)" != systemd ]]; then
    echo 'O teste systemd exige uma VM descartável com systemd como PID 1.' >&2
    exit 1
fi
bash "$project_dir/installer" --source "$project_dir" --no-launch
install_args=(galaxy install --admin-email admin@example.org --port "$port" --yes)
[[ "$systemd_mode" == 1 ]] || install_args+=(--no-service)
[[ "$systemd_mode" == 0 ]] || service_requested=1
biosuite-config "${install_args[@]}"
config_before=$(sha256sum /etc/biosuite/galaxy.yml)
if [[ "$systemd_mode" == 0 ]]; then
    # --no-service não gerencia processos numa instalação já preparada.
    # Um container reiniciado precisa do PostgreSQL iniciado explicitamente.
    if ! pg_isready >/dev/null; then
        pg_version=$(pg_lsclusters --no-header | awk '$2 == "main" {print $1; exit}')
        [[ -n "$pg_version" ]] || { echo 'Cluster PostgreSQL main ausente.' >&2; exit 1; }
        pg_ctlcluster "$pg_version" main start
    fi
    setsid runuser -u biosuitegalaxy -- /opt/biosuite-galaxy/start >/tmp/biosuite-galaxy-smoke.log 2>&1 &
    runner=$!
fi
check_http() {
BIOSUITE_SMOKE_PORT="$port" python3 - <<'PY'
from html.parser import HTMLParser
import json, os, time, urllib.request
from urllib.parse import urljoin, urlsplit
from urllib.error import URLError

class Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sources = []
    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            src = dict(attrs).get('src')
            if src:
                self.sources.append(src)

base = 'http://127.0.0.1:' + os.environ['BIOSUITE_SMOKE_PORT']
for attempt in range(120):
    try:
        with urllib.request.urlopen(base + '/api/version', timeout=5) as response:
            version = json.load(response)
        if version.get('version_major') == '26.1':
            break
    except (URLError, OSError, ValueError):
        pass
    time.sleep(3)
else:
    raise SystemExit('Galaxy não respondeu à API em 360 segundos. Consulte /tmp/biosuite-galaxy-smoke.log')
with urllib.request.urlopen(base + '/', timeout=10) as response:
    html = response.read().decode()
parser = Scripts()
parser.feed(html)
assert '<html' in html.lower(), 'Interface HTML ausente'
scripts = [urljoin(base, src) for src in parser.sources if urlsplit(urljoin(base, src)).netloc == urlsplit(base).netloc]
assert scripts, 'HTML não referencia JavaScript local'
with urllib.request.urlopen(scripts[0], timeout=10) as response:
    assert response.status == 200 and response.read(128), 'JavaScript da interface não foi servido'
with urllib.request.urlopen(base + '/api/tools', timeout=10) as response:
    tools = json.load(response)
assert isinstance(tools, list) and tools, 'Catálogo básico do Galaxy vazio ou inválido'
print('Galaxy real: API, HTML, JavaScript e catálogo básico responderam.')
PY
}
check_http
runuser -u biosuitegalaxy -- sh -c 'printf biosuite-native-smoke > /var/lib/biosuite-galaxy/datasets/biosuite-smoke-marker'
if [[ "$systemd_mode" == 1 ]]; then
    biosuite-config galaxy stop
    systemctl is-active --quiet biosuite-galaxy.service && exit 1
    biosuite-config galaxy start
    check_http
fi
runuser -u biosuitegalaxy -- psql -d biosuitegalaxy -Atc 'SELECT count(*) FROM galaxy_user'
biosuite-config galaxy status
# Reexecução deve preservar configuração e segredo interno, inclusive com porta ocupada pelo próprio Galaxy.
biosuite-config "${install_args[@]}"
[[ "$(sha256sum /etc/biosuite/galaxy.yml)" == "$config_before" ]]
[[ "$(cat /var/lib/biosuite-galaxy/datasets/biosuite-smoke-marker)" == biosuite-native-smoke ]]
if command -v systemd-analyze >/dev/null; then
    systemd-analyze verify /etc/systemd/system/biosuite-galaxy.service
else
    echo 'Verificação estática systemd não executada: systemd-analyze ausente.'
fi
printf 'Reexecução preservou configuração e dados; porta %s; systemd=%s.\n' "$port" "$systemd_mode"
