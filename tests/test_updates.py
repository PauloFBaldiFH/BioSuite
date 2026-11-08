import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from biosuite import updates
from biosuite.cli import main
from biosuite.operations import OperationError


class UpdatesTests(unittest.TestCase):
    def test_plan_uses_saved_installation_and_exact_main_commit(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            env = root / 'releases/current'
            (env / 'bin').mkdir(parents=True)
            (env / 'biosuite-install.json').write_text(json.dumps({'prefix': str(root), 'bin_dir': str(root / 'bin'), 'commit': 'b' * 40}))
            with patch('biosuite.updates.sys.executable', str(env / 'bin/python')), \
                 patch('biosuite.updates.capture', return_value='a' * 40 + '\trefs/heads/main\n'):
                plan = updates.panel_plan()
            self.assertEqual(plan.commit, 'a' * 40)
            self.assertEqual(plan.current_commit, 'b' * 40)
            self.assertEqual(plan.prefix, root)

    def test_wrong_downloaded_commit_never_executes_installer(self):
        with tempfile.TemporaryDirectory() as folder:
            plan = updates.PanelUpdate('a' * 40, Path(folder), Path(folder) / 'bin', None)
            with patch('biosuite.updates.run_logged') as run, patch('biosuite.updates.capture', return_value='b' * 40):
                with self.assertRaisesRegex(OperationError, 'não corresponde'):
                    updates.update_panel(plan)
            self.assertFalse(any(call.args[0][0] == 'bash' for call in run.call_args_list))

    def test_apt_plan_is_simulated_and_upgrade_does_not_full_upgrade_or_reboot(self):
        with patch('biosuite.updates.capture', return_value='upgrade preview') as capture:
            self.assertEqual(updates.apt_plan(), 'upgrade preview')
            self.assertIn('--simulate', capture.call_args.args[0])
        with patch('biosuite.updates.require_root'), patch('biosuite.updates.lock', return_value=contextlib.nullcontext()), \
             patch('biosuite.updates.run_logged') as run:
            updates.apt('upgrade')
            command = run.call_args.args[0]
            self.assertEqual(command[-1], 'upgrade')
            self.assertNotIn('dist-upgrade', command)
            self.assertNotIn('autoremove', command)
            self.assertNotIn('reboot', command)
            self.assertIn('Dpkg::Options::=--force-confold', command)

    def test_upgrade_cli_requires_confirmation(self):
        with patch('biosuite.updates.apt') as apt:
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(['updates', 'apt-upgrade'])
            apt.assert_not_called()
