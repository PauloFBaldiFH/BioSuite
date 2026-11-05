"""Contratos do bootstrap; instalações reais também são exercitadas na matriz Linux."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / 'installer'


class InstallerTests(unittest.TestCase):
    def test_distribution_matrix(self):
        for distro, version, expected in [
            ('ubuntu', '22.04', 0), ('ubuntu', '24.04', 0),
            ('debian', '12', 0), ('debian', '13', 0),
            ('debian', '11', 1), ('ubuntu', '20.04', 1),
            ('linuxmint', '24.04', 1), ('fedora', '42', 1),
        ]:
            with self.subTest(distro=distro, version=version):
                result = subprocess.run(
                    ['bash', '-c', 'source "$1"; biosuite_supported_os "$2" "$3"',
                     'test', str(INSTALLER), distro, version], capture_output=True, text=True)
                self.assertEqual(result.returncode, expected, result.stderr)

    def test_help_works_without_installation(self):
        result = subprocess.run(['bash', str(INSTALLER), '--help'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--no-launch', result.stdout)

    def test_missing_option_value_fails(self):
        result = subprocess.run(['bash', str(INSTALLER), '--prefix'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('Valor ausente', result.stderr)

    def test_invalid_ref_fails_before_network(self):
        result = subprocess.run(['bash', str(INSTALLER), '--ref', '../other'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)

    def test_failed_update_keeps_previous_installation(self):
        # Falha controlada na criação do venv, sem rede ou APT.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            prefix = root / 'app'
            old = prefix / 'releases' / 'old'
            old.mkdir(parents=True)
            (old / 'sentinel').write_text('preserve')
            (prefix / 'current').symlink_to(old)
            tools = root / 'tools'
            tools.mkdir()
            python = tools / 'python3'
            # Resolve o Python real por argumento; nenhuma interpolação em shell.
            python.write_text('#!/bin/bash\n'
                              'if [[ "$1" == -m && "$2" == venv ]]; then exit 41; fi\n'
                              'if [[ "$1" == -c && "$2" == "import venv, ensurepip" ]]; then exit 0; fi\n'
                              'exec "$BIOSUITE_TEST_PYTHON" "$@"\n')
            python.chmod(0o755)
            (tools / 'dpkg-query').write_text('#!/bin/bash\nprintf "install ok installed\\n"\n')
            (tools / 'dpkg-query').chmod(0o755)
            # Use as funções já carregadas para isolar a matriz de hosts do teste.
            script = ('source "$1"; biosuite_supported_os() { return 0; }; '
                      'biosuite_main --no-launch --source "$2" --prefix "$3" --bin-dir "$4"')
            result = subprocess.run(
                ['bash', '-c', script, 'test', str(INSTALLER), str(ROOT), str(prefix), str(root / 'bin')],
                env={**os.environ, 'PATH': str(tools) + ':' + os.environ['PATH'],
                     'BIOSUITE_TEST_PYTHON': sys.executable}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 41, result.stdout + result.stderr)
            self.assertEqual((prefix / 'current').resolve(), old)
            self.assertEqual((old / 'sentinel').read_text(), 'preserve')
            self.assertEqual(list((prefix / 'releases').iterdir()), [old])
            self.assertFalse((prefix / '.install-lock').exists())
