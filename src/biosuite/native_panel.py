"""Ações nativas com confirmação e saída persistente do instalador."""

import asyncio
import json

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, Label, RichLog, Select, Static

from biosuite import containers, native
from biosuite.operations import OperationError
from biosuite.modules import ConfirmModule


class NativePanel(Vertical):
    DEFAULT_CSS = '''
    NativePanel { height: auto; }
    NativePanel Horizontal { height: auto; }
    NativePanel Button { margin: 0 1 1 0; }
    NativePanel Input { margin-bottom: 1; }
    #native-log { height: 16; border: round #24445c; }
    #native-status { padding: 1; color: #fbbf24; }
    '''

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.busy = False

    def compose(self) -> ComposeResult:
        yield Label('Instalação do Galaxy + PostgreSQL')
        yield Select([('Nativo no Linux', 'native'), ('Docker com volumes persistentes', 'docker')],
                     value='native', allow_blank=False, id='install-mode')
        yield Input(placeholder='E-mail do administrador do Galaxy', id='native-email')
        yield Label('Porta de testes (padrão 8080; edite se necessário)')
        yield Input('8080', type='integer', placeholder='Porta local', id='native-port')
        with Horizontal():
            yield Button('Ver plano', id='native-plan')
            yield Button('Instalar Galaxy', id='native-install', variant='primary')
        with Horizontal():
            yield Button('Estado', id='native-status-button')
            yield Button('Iniciar', id='native-start')
        with Horizontal():
            yield Button('Parar', id='native-stop')
            yield Button('Reiniciar', id='native-restart')
        yield Button('Consultar logs', id='native-logs')
        yield Button('Preparar Docker', id='native-prepare-docker')
        yield Static('Nenhuma instalação foi solicitada. Ações de sistema exigem sudo biosuite-config.', id='native-status')
        yield RichLog(id='native-log', wrap=True, markup=False)

    def settings(self):
        try:
            value = native.NativeSettings(self.query_one('#native-email', Input).value.strip(),
                                          int(self.query_one('#native-port', Input).value))
        except ValueError:
            raise native.NativeError('Informe uma porta numérica.') from None
        value.validate()
        return value

    def message(self, text):
        self.query_one('#native-status', Static).update(Text(text))

    def provider(self):
        return containers if self.query_one('#install-mode', Select).value == 'docker' else native

    def on_button_pressed(self, event: Button.Pressed):
        event.stop()
        if self.busy:
            return
        action = event.button.id.removeprefix('native-')
        provider = self.provider()
        try:
            if action == 'plan':
                self.query_one(RichLog).clear().write(Text(provider.installation_summary(self.settings())))
            elif action == 'install':
                settings = self.settings()
                self.app.push_screen(ConfirmModule(provider.installation_summary(settings) + '\n\nConfirmar instalação?'),
                                     lambda yes: self.run_action('install', settings, provider) if yes else None)
            elif action == 'prepare-docker':
                self.app.push_screen(ConfirmModule('Preparar Docker Engine e plugin Compose usando o repositório oficial '
                                                   'com chave APT verificada. Exige administrador. '
                                                   'Uma instalação Docker existente não será substituída. Confirmar?'),
                                     lambda yes: self.run_action('prepare-docker', provider=containers) if yes else None)
            elif action in ('stop', 'restart'):
                self.app.push_screen(ConfirmModule('Esta ação interrompe o Galaxy e pode afetar jobs em andamento. '
                                                   f'Confirmar {"parada" if action == "stop" else "reinicialização"}?'),
                                     lambda yes: self.run_action(action, provider=provider) if yes else None)
            else:
                self.run_action(action, provider=provider)
        except native.NativeError as error:
            self.message(str(error))

    @work(group='native')
    async def run_action(self, action, settings=None, provider=None):
        if self.busy:
            return
        self.busy = True
        provider = provider or self.provider()
        for widget in self.query('Input, Button, Select'):
            widget.disabled = True
        output = self.query_one(RichLog)
        output.clear()
        self.message('Operação em andamento. A instalação também é registrada em log persistente.')
        try:
            if action == 'install':
                def line(text):
                    self.app.call_from_thread(output.write, Text(text))
                await asyncio.to_thread(provider.install, settings, line)
                result = await asyncio.to_thread(provider.status)
            elif action == 'prepare-docker':
                def line(text):
                    self.app.call_from_thread(output.write, Text(text))
                await asyncio.to_thread(containers.prepare, line)
                result = 'Pré-requisitos Docker preparados.'
            elif action == 'status-button':
                result = await asyncio.to_thread(provider.status)
            elif action == 'logs':
                result = await asyncio.to_thread(provider.logs)
            else:
                result = await asyncio.to_thread(provider.service, action)
            output.write(Text(result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=2)))
            self.message('Consulta/operação concluída. Confira o estado da API e da interface nos resultados.')
        except (native.NativeError, OperationError, OSError, TimeoutError) as error:
            self.message(str(error))
        finally:
            self.busy = False
            for widget in self.query('Input, Button, Select'):
                widget.disabled = False
