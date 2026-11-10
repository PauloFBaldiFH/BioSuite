from pathlib import Path
import unittest
from unittest.mock import patch
from textual.widgets import Input, Select
from biosuite.panel import BioSuiteApp


class BackupPanelTests(unittest.IsolatedAsyncioTestCase):
    async def click(self, app, pilot, selector):
        app.screen.query_one(selector).scroll_visible(animate=False)
        await pilot.pause(); await pilot.click(selector); await pilot.pause()
        await app.workers.wait_for_complete()

    async def test_restore_cancel_and_confirm_captures_source_and_mode(self):
        app=BioSuiteApp()
        with patch('biosuite.backups.restore',return_value={'restored':True}) as restore:
            async with app.run_test(size=(110,40)) as pilot:
                app.show_page('backup')
                app.query_one('#backup-mode',Select).value='docker'
                app.query_one('#backup-source',Input).value='/tmp/snapshot'
                app.query_one('#backup-directory',Input).value='/tmp/safety'
                await self.click(app,pilot,'#backup-restore');restore.assert_not_called()
                await self.click(app,pilot,'#module-cancel');restore.assert_not_called()
                await self.click(app,pilot,'#backup-restore')
                await self.click(app,pilot,'#module-confirm-yes')
                self.assertEqual(restore.call_args.args[:3],('docker',Path('/tmp/snapshot'),Path('/tmp/safety')))

    async def test_create_does_not_run_on_navigation_and_populates_source_after_confirmation(self):
        app=BioSuiteApp()
        with patch('biosuite.backups.create',return_value=Path('/tmp/created')) as create:
            async with app.run_test(size=(80,24)) as pilot:
                app.show_page('backup');create.assert_not_called()
                await self.click(app,pilot,'#backup-create');create.assert_not_called()
                await self.click(app,pilot,'#module-confirm-yes')
                self.assertEqual(app.query_one('#backup-source',Input).value,'/tmp/created')

    async def test_busy_backup_blocks_navigation_and_quit(self):
        app=BioSuiteApp()
        async with app.run_test(size=(80,24)):
            app.show_page('backup');app.query_one('#backup-panel').busy=True
            app.show_page('install')
            self.assertEqual(app.current_page,'backup')
            app.action_quit();self.assertTrue(app.is_running)
            app.query_one('#backup-panel').busy=False
