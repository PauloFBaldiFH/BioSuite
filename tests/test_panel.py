from pathlib import Path
import unittest

from textual.widgets import Button, Static

from biosuite.panel import BioSuiteApp


class PanelTests(unittest.IsolatedAsyncioTestCase):
    async def test_navigation_and_keyboard_actions(self):
        app = BioSuiteApp(storage=Path.cwd())
        async with app.run_test(size=(110, 40)) as pilot:
            self.assertIn('Bem-vindo', str(app.query_one('#page-title', Static).render()))
            await pilot.click('#install')
            self.assertIn('PLANO', str(app.query_one('#page-body', Static).render()))
            await pilot.click('#tools')
            self.assertIn('IQ-TREE', str(app.query_one('#page-body', Static).render()))
            await pilot.click('#backup')
            self.assertTrue(app.query_one('#backup-panel').display)
            self.assertIn('Nenhuma cópia', str(app.query_one('#backup-status', Static).render()))
            await pilot.click('#connection')
            self.assertIn('Nenhum tunnel', str(app.query_one('#page-body', Static).render()))
            await pilot.press('d')
            self.assertIn('free_gib', str(app.query_one('#page-body', Static).render()))
            await pilot.press('p')
            self.assertIn('PLANO', str(app.query_one('#page-body', Static).render()))

    async def test_navigation_on_small_terminal(self):
        app = BioSuiteApp()
        async with app.run_test(size=(80, 24)) as pilot:
            app.query_one('#doctor', Button).scroll_visible(animate=False)
            await pilot.pause()
            await pilot.click('#doctor')
            self.assertIn('Diagnóstico', str(app.query_one('#page-title', Static).render()))
            await pilot.press('d')
            self.assertIn('Diagnóstico', str(app.query_one('#page-title', Static).render()))
