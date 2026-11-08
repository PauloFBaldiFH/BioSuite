"""Cadastro e conexão no broker BioSuite da zona koha.nexus."""
import asyncio
import json
from pathlib import Path

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Button, Input, Label, RichLog, Static

from biosuite.connection import BrokerClient, DEFAULT_BROKER, prepare_connector, stop_connector
from biosuite.modules import ConfirmModule
from biosuite.operations import OperationError


class ConnectionPanel(Vertical):
    DEFAULT_CSS = '''
    ConnectionPanel { height: auto; }
    ConnectionPanel Input, ConnectionPanel Button { margin-bottom: 1; }
    #connection-log { height: 14; border: round #24445c; }
    #connection-status { height: auto; padding: 1; color: #fbbf24; }
    '''

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.busy = False

    def compose(self) -> ComposeResult:
        yield Static('Endereço gratuito para quem usa o BioSuite, sob koha.nexus. '
                     'Exige publicar a adaptação BioSuite do broker na mesma conta Cloudflare; '
                     'o Worker original do Koha permanece separado. Nenhuma chave administrativa Cloudflare é solicitada neste painel. '
                     'Cloudflare tem limites de upload; datasets grandes podem exigir transferência alternativa.')
        yield Label('Broker BioSuite')
        yield Input(DEFAULT_BROKER, id='connection-url')
        yield Input(placeholder='Instituição ou laboratório', id='connection-institution')
        yield Input(placeholder='E-mail de contato', id='connection-email')
        yield Input(placeholder='Nome desejado (ex.: laboratorio); o broker aplica bio-', id='connection-slug')
        yield Label('Porta local do Galaxy (nativo ou publicada pelo Docker)')
        yield Input('8080', type='integer', id='connection-port')
        yield Button('Verificar broker', id='connection-capabilities')
        yield Button('Solicitar endereço', id='connection-start', variant='primary')
        yield Button('Consultar aprovação / estado', id='connection-poll')
        yield Button('Concluir cadastro aprovado', id='connection-enroll')
        yield Button('Encerrar solicitação recusada/expirada', id='connection-reset')
        yield Button('Preparar conector cloudflared', id='connection-prepare')
        yield Button('Ativar túnel', id='connection-activate')
        yield Button('Desativar túnel local', id='connection-stop')
        yield Input(str(Path.home() / 'biosuite-address-recovery.json'), id='connection-recovery')
        yield Button('Exportar recuperação privada', id='connection-export')
        yield Button('Importar recuperação', id='connection-import')
        yield Static('Nenhuma publicação foi solicitada.', id='connection-status')
        yield RichLog(id='connection-log', wrap=True, markup=False)

    def on_button_pressed(self, event: Button.Pressed):
        event.stop()
        if self.busy:
            return
        action = event.button.id.removeprefix('connection-')
        try:
            client = BrokerClient(self.query_one('#connection-url', Input).value)
            args = ()
            if action == 'start':
                try:
                    args = tuple(self.query_one('#connection-' + field, Input).value.strip()
                                 for field in ('institution', 'email', 'slug')) + (int(self.query_one('#connection-port', Input).value),)
                except ValueError:
                    raise OperationError('Informe uma porta numérica.') from None
                message = ('Solicitar um endereço público para o Galaxy neste broker?\n'
                           f'{client.url}\nNome: bio-{args[2]} (o broker pode ajustar se ocupado)\nPorta local: {args[3]}\n\n'
                           'O cadastro provisiona DNS/túnel no serviço central. A conexão local só começa após Ativar túnel. '
                           'Mantenha a autenticação do Galaxy configurada.')
            elif action == 'reset':
                message = 'Consultar o broker e encerrar a solicitação local apenas se recusada ou expirada? A identidade será preservada.'
            elif action == 'prepare':
                message = 'Instalar cloudflared pelo repositório APT oficial e chave de assinatura obtida por HTTPS? Exige administrador.'
            elif action == 'enroll':
                message = 'Concluir o cadastro aprovado e provisionar o endereço/túnel no broker?\n'
                message += json.dumps(client.public_state(), ensure_ascii=False, indent=2)
            elif action == 'activate':
                message = 'Iniciar a conexão pública desta instalação? Confira o endereço aprovado e a porta local. '
                message += 'A credencial limitada deste túnel fica em arquivo privado e no mecanismo de credenciais do systemd.'
            elif action == 'stop':
                message = 'Desativar apenas o túnel local? O endereço continua reservado no broker.'
            elif action in ('export', 'import'):
                args = (Path(self.query_one('#connection-recovery', Input).value),)
                message = ('Exportar a chave privada de recuperação para o arquivo informado? Guarde-o fora do servidor.' if action == 'export'
                           else 'Importar a identidade do arquivo informado? Uma configuração existente não será sobrescrita.')
            else:
                self.run_action(action, client)
                return
            self.app.push_screen(ConfirmModule(message),
                                 lambda yes: self.run_action(action, client, *args) if yes else None)
        except (OperationError, ValueError) as error:
            self.query_one('#connection-status', Static).update(Text(str(error)))

    @work(group='connection')
    async def run_action(self, action, client, *args):
        if self.busy:
            return
        self.busy = True
        for widget in self.query('Button, Input'):
            widget.disabled = True
        status = self.query_one('#connection-status', Static)
        output = self.query_one(RichLog)
        output.clear()
        status.update('Operação em andamento…')
        try:
            if action == 'prepare':
                def line(text):
                    self.app.call_from_thread(output.write, Text(text))
                await asyncio.to_thread(prepare_connector, line)
                result = 'Conector preparado; nenhuma publicação é iniciada automaticamente.'
            elif action == 'stop':
                result = await asyncio.to_thread(stop_connector)
            else:
                method = {'capabilities': client.capabilities, 'start': client.start, 'poll': client.poll,
                          'enroll': client.enroll, 'activate': client.activate, 'reset': client.reset_pending,
                          'export': client.export_recovery, 'import': client.import_recovery}[action]
                result = await asyncio.to_thread(method, *args)
            output.write(Text(result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=2)))
            status.update('Operação concluída. Estado do cadastro e estado do conector são verificações separadas.')
        except (OperationError, OSError, ValueError) as error:
            status.update(Text(str(error)))
        finally:
            self.busy = False
            for widget in self.query('Button, Input'):
                widget.disabled = False
