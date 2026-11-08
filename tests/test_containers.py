import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from biosuite import containers
from biosuite.native import NativeSettings
from biosuite.operations import OperationError


class ContainerTests(unittest.TestCase):
    def test_custom_host_port_and_volumes_are_persistent_without_password_in_environment(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(containers, 'BASE', Path(folder) / 'app'), \
             patch.object(containers, 'LOG', Path(folder) / 'log'), patch('biosuite.containers.capture', return_value=''), \
             patch('biosuite.containers.run_logged') as run, \
             patch('biosuite.containers.status', return_value={'api': 'respondeu', 'interface': 'HTML entregue'}):
            containers.install(NativeSettings('admin@example.org', 18881), output=lambda _: None)
            config = json.loads((containers.BASE / 'compose.json').read_text())
            self.assertEqual(config['services']['galaxy']['ports'], ['127.0.0.1:18881:8080'])
            self.assertNotIn('ports', config['services']['db'])
            self.assertNotIn('POSTGRES_PASSWORD', config['services']['db']['environment'])
            self.assertIn('POSTGRES_PASSWORD_FILE', config['services']['db']['environment'])
            self.assertEqual((containers.BASE / 'db-password').stat().st_mode & 0o777, 0o600)
            before = (containers.BASE / 'db-password').read_bytes()
            containers.install(NativeSettings('admin@example.org', 18881), output=lambda _: None)
            self.assertEqual((containers.BASE / 'db-password').read_bytes(), before)
            self.assertFalse(any('-v' in call.args[0] or 'down' in call.args[0] for call in run.call_args_list))

    def test_unmanaged_directory_is_not_adopted(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(containers, 'BASE', Path(folder)), \
             patch('biosuite.containers.capture', return_value=''):
            with self.assertRaisesRegex(OperationError, 'não é gerenciado'):
                containers.install(NativeSettings('admin@example.org'))
