import unittest
from unittest.mock import Mock, patch

from textual.widgets import Input, RichLog, Static

from biosuite.panel import BioSuiteApp


class NativePanelTests(unittest.IsolatedAsyncioTestCase):
    async def test_install_requires_valid_settings_and_confirmation(self):
        app = BioSuiteApp()
        with patch('biosuite.native.install') as install, patch('biosuite.native.status', return_value={'api': 'respondeu'}):
            async with app.run_test(size=(110, 40)) as pilot:
                app.show_page('install')
                async def click(selector):
                    app.screen.query_one(selector).scroll_visible(animate=False)
                    await pilot.pause()
                    await pilot.click(selector)
                    await pilot.pause()
                    await app.workers.wait_for_complete()
                await click('#native-install')
                install.assert_not_called()
                self.assertIn('e-mail', str(app.query_one('#native-status', Static).render()))
                app.query_one('#native-email', Input).value = 'admin@example.org'
                await click('#native-install')
                install.assert_not_called()
                await click('#module-cancel')
                install.assert_not_called()
                await click('#native-install')
                await click('#module-confirm-yes')
                install.assert_called_once()
                self.assertIn('concluída', str(app.query_one('#native-status', Static).render()))
