"""Initialize instance configuration and run Galaxy as an unprivileged user."""
import json
import os
from pathlib import Path
import secrets
import subprocess
from urllib.parse import quote

data = Path('/data')
for path in [data] + [data / name for name in ('config', 'datasets', 'tmp', 'jobs', 'dependencies', 'logs')]:
    path.mkdir(exist_ok=True)
    os.chown(path, 1000, 1000)
config = data / 'config/galaxy.yml'
if not config.exists():
    password = Path('/run/secrets/db_password').read_text().strip()
    document = {
        'gravity': {'galaxy_root': '/galaxy', 'virtualenv': '/galaxy/.venv', 'log_dir': '/data/logs',
                    'gunicorn': {'bind': '0.0.0.0:8080', 'workers': 1}},
        'galaxy': {'database_connection': 'postgresql://biosuitegalaxy:' + quote(password, safe='') + '@db/biosuitegalaxy',
                   'data_dir': '/data', 'managed_config_dir': '/data/config', 'file_path': '/data/datasets',
                   'new_file_path': '/data/tmp', 'job_working_directory': '/data/jobs',
                   'tool_dependency_dir': '/data/dependencies', 'tool_config_file': '/galaxy/config/tool_conf.xml.sample',
                   'admin_users': os.environ['GALAXY_ADMIN_EMAIL'], 'id_secret': secrets.token_hex(16),
                   'conda_auto_init': True, 'conda_auto_install': True, 'allow_user_creation': True}}
    with config.open('x') as stream:
        json.dump(document, stream, indent=2)
    os.chmod(config, 0o600)
    os.chown(config, 1000, 1000)
os.environ['GALAXY_CONFIG_FILE'] = str(config)
for command in ('init', 'upgrade'):
    subprocess.run(['runuser', '-u', 'galaxy', '--', 'sh', 'manage_db.sh', '--galaxy-config', str(config), command], check=True)
os.execvp('runuser', ['runuser', '-u', 'galaxy', '--', 'sh', 'run.sh', '--skip-wheels', '--skip-client-build', '--skip-tool-dependency-initialization'])
