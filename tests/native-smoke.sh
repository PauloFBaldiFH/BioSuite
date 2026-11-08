#!/usr/bin/env bash
# Somente em container/VM descartável como root. Instala Galaxy real.
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
bash "$project_dir/installer" --source "$project_dir" --no-launch
biosuite-config galaxy install --admin-email admin@example.org --yes --no-service
config_before=$(sha256sum /etc/biosuite/galaxy.yml)
setsid runuser -u biosuitegalaxy -- /opt/biosuite-galaxy/start >/tmp/biosuite-galaxy-smoke.log 2>&1 &
runner=$!
trap 'kill -- -"$runner" 2>/dev/null || true' EXIT
python3 - <<'PY'
from html.parser import HTMLParser
import json, time, urllib.request
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

base = 'http://127.0.0.1:8080'
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
scripts = [urljoin(base, src) for src in parser.sources if urlsplit(urljoin(base, src)).netloc == '127.0.0.1:8080']
assert scripts, 'HTML não referencia JavaScript local'
with urllib.request.urlopen(scripts[0], timeout=10) as response:
    assert response.status == 200 and response.read(128), 'JavaScript da interface não foi servido'
with urllib.request.urlopen(base + '/api/tools', timeout=10) as response:
    tools = json.load(response)
assert isinstance(tools, list) and tools, 'Catálogo básico do Galaxy vazio ou inválido'
print('Galaxy real: API, HTML, JavaScript e catálogo básico responderam.')
PY
runuser -u biosuitegalaxy -- psql -d biosuitegalaxy -Atc 'SELECT count(*) FROM galaxy_user'
biosuite-config galaxy status
# Reexecução deve preservar configuração e segredo interno, inclusive com porta ocupada pelo próprio Galaxy.
biosuite-config galaxy install --admin-email admin@example.org --yes --no-service
[[ "$(sha256sum /etc/biosuite/galaxy.yml)" == "$config_before" ]]
echo 'Reexecução preservou a configuração existente.'
