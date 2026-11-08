"""Somente em host/runner descartável com Docker. Instala Galaxy real (~minutos).

PYTHONPATH=src BIOSUITE_DOCKER_HOME=/tmp/biosuite-docker-smoke python3 tests/docker-smoke.py
Não remove volumes. Projeto e volumes têm os nomes fixos do BioSuite.
"""
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import time
from urllib.parse import urljoin, urlsplit
from urllib.request import urlopen

from biosuite import containers as c
from biosuite.native import NativeSettings
from biosuite.operations import capture, OperationError


class Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sources = []

    def handle_starttag(self, tag, attrs):
        if tag == 'script' and dict(attrs).get('src'):
            self.sources.append(dict(attrs)['src'])


def ready():
    for attempt in range(120):
        state = c.status()
        if state['api'] == 'respondeu' and state['interface'] == 'HTML entregue':
            return
        time.sleep(3)
    raise AssertionError('Galaxy Docker não ficou pronto; consulte logs do Compose.')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


settings = NativeSettings('admin@example.org', 8082)
c.install(settings)
base = 'http://127.0.0.1:8082'
with urlopen(base + '/') as response:
    html = response.read().decode()
parser = Scripts()
parser.feed(html)
scripts = [urljoin(base, src) for src in parser.sources if urlsplit(urljoin(base, src)).netloc == '127.0.0.1:8082']
assert scripts, 'HTML sem JavaScript local'
with urlopen(scripts[0]) as response:
    assert response.status == 200 and response.read(128)
with urlopen(base + '/api/tools') as response:
    tools = json.load(response)
assert isinstance(tools, list) and tools
capture(c.compose('exec', '-T', 'db', 'psql', '-U', 'biosuitegalaxy', '-d', 'biosuitegalaxy', '-Atc', 'SELECT count(*) FROM galaxy_user'))
config_cmd = c.compose('exec', '-T', 'galaxy', 'sha256sum', '/data/config/galaxy.yml')
config_before = capture(config_cmd)
password_before = digest(c.BASE / 'db-password')
capture(c.compose('exec', '-T', 'galaxy', 'runuser', '-u', 'galaxy', '--', 'sh', '-c', 'echo smoke-test > /data/datasets/biosuite-smoke-marker'))
c.service('stop')
c.service('start')
ready()
assert capture(config_cmd) == config_before
assert capture(c.compose('exec', '-T', 'galaxy', 'cat', '/data/datasets/biosuite-smoke-marker')).strip() == 'smoke-test'
c.install(settings)
assert digest(c.BASE / 'db-password') == password_before
assert capture(config_cmd) == config_before
try:
    c.install(NativeSettings('other@example.org', 8083))
except OperationError:
    pass
else:
    raise AssertionError('Configuração diferente foi aceita')
print('Docker Galaxy real: API, HTML, JS, ferramentas, schema, stop/start e reinstalação preservaram dados/configuração/senha; porta 8082.')
