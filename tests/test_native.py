import contextlib
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from biosuite import native
from biosuite.cli import main


class NativeTests(unittest.TestCase):
    def test_settings_and_plan(self):
        plan = native.installation_summary(native.NativeSettings('admin@example.org', 8081))
        self.assertIn('26.1.2', plan)
        self.assertIn('8081', plan)
        self.assertIn('/var/lib/biosuite-galaxy', plan)
        for email, port in [('invalid', 8080), ('admin@example.org', 0), ('admin@example.org', 65536)]:
            with self.subTest(email=email, port=port), self.assertRaises(native.NativeError):
                native.NativeSettings(email, port).validate()

    def test_unprivileged_install_does_not_launch_commands(self):
        with patch('biosuite.native.os.geteuid', return_value=1000), patch('biosuite.native.subprocess.Popen') as process:
            with self.assertRaisesRegex(native.NativeError, 'sudo biosuite-config'):
                native.install(native.NativeSettings('admin@example.org'))
            process.assert_not_called()

    def test_installer_requires_confirmation_before_system_operations(self):
        script = Path(__file__).resolve().parents[1] / 'src/biosuite/assets/install-galaxy.sh'
        result = subprocess.run(['bash', str(script), '--admin-email', 'admin@example.org'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('--yes', result.stderr)

    def test_process_output_is_persisted_and_nonzero_exit_is_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder) / 'logs/galaxy.log'
            def start(command, **kwargs):
                kwargs['stdout'].write('etapa de teste\n')
                kwargs['stdout'].flush()
                return Mock(poll=Mock(return_value=42), wait=Mock(return_value=42))
            with patch('biosuite.native.os.geteuid', return_value=0), patch.object(native, 'LOG', log), \
                 patch('biosuite.native.subprocess.Popen', side_effect=start) as process:
                lines = []
                with self.assertRaisesRegex(native.NativeError, 'código 42'):
                    native.install(native.NativeSettings('admin@example.org'), lines.append)
                self.assertIn('etapa de teste', lines)
                self.assertIn('etapa de teste', log.read_text())
                self.assertEqual(log.stat().st_mode & 0o777, 0o600)
                self.assertTrue(process.call_args.kwargs['start_new_session'])
                self.assertIn('--yes', process.call_args.args[0])

    def test_missing_installation_is_not_reported_as_ready(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(native, 'BASE', Path(folder)):
            state = native.status()
            self.assertFalse(state['managed'])
            self.assertFalse(state['prepared'])
            self.assertEqual(state['api'], 'não verificada')

    def test_service_rejects_arbitrary_commands(self):
        with patch('biosuite.native.subprocess.run') as process:
            with self.assertRaises(native.NativeError):
                native.service('start; echo bad')
            process.assert_not_called()

    def test_cli_install_requires_explicit_confirmation(self):
        with patch('biosuite.native.install') as install:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(['galaxy', 'install', '--admin-email', 'admin@example.org'])
            install.assert_not_called()
