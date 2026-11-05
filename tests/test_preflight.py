import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from biosuite.cli import main
from biosuite.preflight import Machine, inspect_machine, installation_plan, storage_parent


class PreflightTests(unittest.TestCase):
    def test_nonexistent_storage_uses_existing_parent(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(storage_parent(Path(folder) / 'new' / 'data'), Path(folder))
            machine = inspect_machine(Path(folder) / 'new' / 'data')
            self.assertGreater(machine.free_gib, 0)
            self.assertFalse((Path(folder) / 'new').exists())

    def test_unsupported_host_is_reported_without_readiness_claim(self):
        machine = Machine('Windows', 'ARM64', 'unknown', 'unknown', '3.12',
                          False, None, 15, '/data', False, {})
        plan = installation_plan(machine)
        self.assertIn('fora do alvo inicial', plan)
        self.assertIn('ainda não está implementada', plan)
        self.assertIn('nenhum', plan.lower())

    def test_debian_and_ubuntu_are_in_panel_matrix(self):
        for distro, version in [('debian', '12'), ('debian', '13'),
                               ('ubuntu', '22.04'), ('ubuntu', '24.04')]:
            with self.subTest(distro=distro, version=version):
                machine = Machine('Linux', 'x86_64', distro, version, '3.12',
                                  False, 8, 40, '/data', True, {})
                plan = installation_plan(machine)
                self.assertIn('corresponde à matriz do painel', plan)
                self.assertIn('Galaxy ainda requer validação própria', plan)

    def test_doctor_returns_machine_json(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(['doctor']), 0)
        self.assertIn('free_gib', json.loads(output.getvalue()))

    def test_panel_dependency_not_imported_by_doctor(self):
        with patch.dict('sys.modules', {'biosuite.panel': None}):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['doctor']), 0)
