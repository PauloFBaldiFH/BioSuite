import unittest
from unittest.mock import Mock, patch

from textual.widgets import Input, Select, Static

from biosuite.galaxy import Repository
from biosuite.modules import ModulePanel
from biosuite.panel import BioSuiteApp


class ModulePanelTests(unittest.IsolatedAsyncioTestCase):
    async def test_connect_confirm_cancel_install_and_uninstall(self):
        repo = Repository('abc123', 'iqtree', 'iuc', '123456abcdef',
                          'toolshed.g2.bx.psu.edu', 'Installed', False, False)
        client = Mock(url='http://localhost:8080')
        client.connect.return_value = []
        client.install.return_value = [repo]
        client.uninstall.return_value = []
        app = BioSuiteApp()
        with patch('biosuite.modules.GalaxyClient', return_value=client):
            async with app.run_test(size=(110, 40)) as pilot:
                app.show_page('tools')
                panel = app.query_one(ModulePanel)
                client.connect.assert_not_called()
                app.query_one('#module-key', Input).value = 'test-key'

                async def click(selector):
                    app.screen.query_one(selector).scroll_visible(animate=False)
                    await pilot.pause()
                    await pilot.click(selector)
                    await pilot.pause()
                    await app.workers.wait_for_complete()

                await click('#module-connect')
                client.connect.assert_called_once()
                self.assertEqual(app.query_one('#module-key', Input).value, '')
                app.query_one('#module-preset', Select).value = 'iqtree'
                await pilot.pause()
                app.query_one('#module-revision', Input).value = repo.revision
                await click('#module-install')
                client.install.assert_not_called()
                await click('#module-cancel')
                client.install.assert_not_called()
                await click('#module-install')
                await click('#module-confirm-yes')
                client.install.assert_called_once()
                self.assertEqual(panel.repositories, [repo])
                panel.selected = repo
                await click('#module-uninstall')
                client.uninstall.assert_not_called()
                await pilot.press('escape')
                client.uninstall.assert_not_called()
                await click('#module-uninstall')
                await click('#module-confirm-yes')
                client.uninstall.assert_called_once_with(repo)

    async def test_unconnected_action_explains_prerequisite(self):
        app = BioSuiteApp()
        async with app.run_test(size=(80, 24)) as pilot:
            app.show_page('tools')
            app.query_one('#module-refresh').scroll_visible(animate=False)
            await pilot.pause()
            await pilot.click('#module-refresh')
            self.assertIn('Conecte primeiro', str(app.query_one('#module-status', Static).render()))
