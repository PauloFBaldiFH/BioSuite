import unittest
from unittest.mock import Mock, patch

from textual.widgets import Input, Select

from biosuite.panel import BioSuiteApp


class MaintenancePanelTests(unittest.IsolatedAsyncioTestCase):
    async def click(self, app, pilot, selector):
        app.screen.query_one(selector).scroll_visible(animate=False)
        await pilot.pause()
        await pilot.click(selector)
        await pilot.pause()
        await app.workers.wait_for_complete()

    async def test_apt_upgrade_cancel_and_confirm(self):
        app=BioSuiteApp()
        with patch('biosuite.updates.apt_plan',return_value='1 pacote será atualizado'), \
             patch('biosuite.updates.apt',return_value={'completed':True}) as apt:
            async with app.run_test(size=(110,40)) as pilot:
                app.show_page('updates')
                await self.click(app,pilot,'#update-apt-plan')
                apt.assert_not_called()
                await self.click(app,pilot,'#module-cancel')
                apt.assert_not_called()
                await self.click(app,pilot,'#update-apt-plan')
                await self.click(app,pilot,'#module-confirm-yes')
                self.assertEqual(apt.call_args.args[0],'upgrade')

    async def test_docker_choice_preserves_custom_port_and_does_not_call_native(self):
        app=BioSuiteApp()
        with patch('biosuite.containers.install') as docker, patch('biosuite.containers.status',return_value={}), \
             patch('biosuite.native.install') as native:
            async with app.run_test(size=(110,40)) as pilot:
                app.show_page('install')
                app.query_one('#install-mode',Select).value='docker'
                app.query_one('#native-email',Input).value='lab@example.org'
                app.query_one('#native-port',Input).value='8087'
                await self.click(app,pilot,'#native-install')
                docker.assert_not_called()
                await self.click(app,pilot,'#module-confirm-yes')
                self.assertEqual(docker.call_args.args[0].port,8087)
                native.assert_not_called()

    async def test_subdomain_request_requires_confirmation(self):
        app=BioSuiteApp()
        client=Mock(url='https://biosuite-broker.koha.nexus')
        client.start.return_value={'status':'pending'}
        with patch('biosuite.connection_panel.BrokerClient',return_value=client):
            async with app.run_test(size=(110,40)) as pilot:
                app.show_page('connection')
                for field,value in [('institution','BioSuite Lab'),('email','lab@example.org'),('slug','laboratorio'),('port','8087')]:
                    app.query_one('#connection-'+field,Input).value=value
                await self.click(app,pilot,'#connection-start')
                client.start.assert_not_called()
                await self.click(app,pilot,'#module-cancel')
                client.start.assert_not_called()
                await self.click(app,pilot,'#connection-start')
                await self.click(app,pilot,'#module-confirm-yes')
                self.assertEqual(client.start.call_args.args[-1],8087)
