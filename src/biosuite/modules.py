"""Gestão interativa de repositórios em um Galaxy existente."""

import asyncio
import os

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Label, Select, Static

from biosuite.galaxy import GalaxyClient, GalaxyError, Repository, ToolSpec

# Identidades conferidas nos .shed.yml dos projetos oficiais; nenhuma revisão é presumida.
PRESETS = {
    'iqtree': ('iqtree', 'iuc'),
    'qiime2': ('suite_qiime2__feature_table', 'q2d2'),
}


class ConfirmModule(ModalScreen[bool]):
    DEFAULT_CSS = '''
    ConfirmModule { align: center middle; background: #000000 70%; }
    #module-confirm { width: 76; max-width: 95%; height: auto; max-height: 95%;
                      border: round #5eead4; padding: 1 2; background: #101e30; overflow-y: auto; }
    #module-confirm Horizontal { height: auto; margin-top: 1; }
    '''
    BINDINGS = [('escape', 'cancel', 'Cancelar')]

    def __init__(self, message: str):
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id='module-confirm'):
            yield Static(Text(self.message))
            with Horizontal():
                yield Button('Cancelar', id='module-cancel')
                yield Button('Confirmar', id='module-confirm-yes', variant='warning')

    def on_mount(self):
        self.query_one('#module-cancel', Button).focus()

    def action_cancel(self):
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed):
        event.stop()
        self.dismiss(event.button.id == 'module-confirm-yes')


class ModulePanel(Vertical):
    DEFAULT_CSS = '''
    ModulePanel { height: auto; }
    ModulePanel Input, ModulePanel Select { margin-bottom: 1; }
    ModulePanel Horizontal { height: auto; }
    ModulePanel Button { margin: 0 1 1 0; }
    #module-table { height: 10; margin-bottom: 1; }
    #module-status { height: auto; padding: 1; color: #fbbf24; }
    '''

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.client: GalaxyClient | None = None
        self.repositories: list[Repository] = []
        self.selected: Repository | None = None
        self.busy = False

    def compose(self) -> ComposeResult:
        yield Label('Conectar a um Galaxy existente — chave de administrador, mantida só nesta sessão')
        yield Input(os.environ.get('GALAXY_URL', 'http://localhost:8080'), placeholder='URL do Galaxy', id='module-url')
        yield Input(os.environ.get('GALAXY_API_KEY', ''), password=True, placeholder='Chave de API do administrador', id='module-key')
        with Horizontal():
            yield Button('Conectar', id='module-connect')
            yield Button('Atualizar estado', id='module-refresh')
        yield Static('Sem conexão. Nenhuma consulta ou instalação foi feita.', id='module-status')
        yield DataTable(id='module-table', cursor_type='row')
        yield Button('Desinstalar selecionado', id='module-uninstall', variant='error')
        yield Label('Novo módulo — escolha um preset ou informe outro repositório do Tool Shed')
        yield Select([('IQ-TREE', 'iqtree'), ('QIIME 2 • Feature Table (Docker)', 'qiime2'),
                      ('Outro repositório', 'custom')], prompt='Escolha um módulo', id='module-preset')
        yield Input(placeholder='Nome do repositório (ex.: iqtree)', id='module-name')
        yield Input(placeholder='Proprietário no Tool Shed (ex.: iuc)', id='module-owner')
        yield Button('Consultar revisões', id='module-revisions')
        yield Select([], prompt='Revisões consultadas — escolha uma', id='module-revision-options')
        yield Input(placeholder='Revisão exata do Tool Shed (também pode ser informada manualmente)', id='module-revision')
        yield Static('QIIME 2: este preset é só o plugin Feature Table, não a distribuição inteira. '
                     'Os wrappers oficiais atuais usam Docker; configure o destino de jobs do Galaxy antes de instalar. '
                     'O BioSuite não instala Docker automaticamente.')
        yield Button('Revisar instalação', id='module-install', variant='primary')

    def on_mount(self):
        self.query_one(DataTable).add_columns('Repositório', 'Proprietário', 'Revisão', 'Estado')

    def status(self, message: str):
        self.query_one('#module-status', Static).update(Text(message))

    def render_repositories(self, repos: list[Repository]):
        self.repositories = repos
        self.selected = None
        table = self.query_one(DataTable)
        table.clear()
        for repo in repos:
            table.add_row(*(Text(v) for v in (repo.name, repo.owner, repo.revision, repo.display_status)))

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted):
        event.stop()
        index = event.cursor_row
        self.selected = self.repositories[index] if index < len(self.repositories) else None

    def on_select_changed(self, event: Select.Changed):
        event.stop()
        if event.select.id == 'module-preset':
            name, owner = PRESETS.get(event.value, ('', ''))
            self.query_one('#module-name', Input).value = name
            self.query_one('#module-owner', Input).value = owner
            self.query_one('#module-revision', Input).value = ''
            self.query_one('#module-revision-options', Select).set_options([])
        elif event.select.id == 'module-revision-options' and event.value is not Select.BLANK:
            self.query_one('#module-revision', Input).value = str(event.value)

    def on_button_pressed(self, event: Button.Pressed):
        event.stop()
        if self.busy:
            return
        action = event.button.id.removeprefix('module-')
        try:
            if action == 'connect':
                client = GalaxyClient(self.query_one('#module-url', Input).value,
                                      self.query_one('#module-key', Input).value)
                self.run_operation('connect', client)
                return
            if self.client is None:
                raise GalaxyError('Conecte primeiro ao Galaxy com uma chave de administrador.')
            client = self.client
            if action in ('refresh', 'revisions'):
                args = (self.query_one('#module-name', Input).value.strip(),
                        self.query_one('#module-owner', Input).value.strip()) if action == 'revisions' else ()
                self.run_operation(action, client, *args)
            elif action == 'install':
                spec = ToolSpec(*(self.query_one('#module-' + field, Input).value.strip()
                                  for field in ('name', 'owner', 'revision')))
                spec.validate()
                message = (f'Instalar em {client.url}\n\n{spec.owner}/{spec.name}\nRevisão: {spec.revision}\n\n'
                           'Galaxy instalará também as dependências do repositório e do resolver configurado. '
                           'Isso pode baixar arquivos grandes. Confira espaço e compatibilidade no Galaxy. '
                           'Wrappers QIIME 2 podem exigir Docker.\n\nConfirmar a solicitação?')
                self.app.push_screen(ConfirmModule(message),
                                     lambda yes: self.run_operation('install', client, spec) if yes else None)
            elif action == 'uninstall':
                repo = self.selected
                if repo is None:
                    raise GalaxyError('Selecione uma linha na lista de repositórios.')
                message = (f'Desinstalar de {client.url}\n\n{repo.owner}/{repo.name}\nRevisão: {repo.revision}\nID: {repo.id}\n\n'
                           'Galaxy removerá este repositório do disco. Isso pode afetar workflows que usam suas ferramentas. '
                           'Esta ação não solicita exclusão de históricos ou datasets, nem limpeza global de ambientes Conda. '
                           'Confira jobs em andamento antes de continuar.\n\nConfirmar a remoção?')
                self.app.push_screen(ConfirmModule(message),
                                     lambda yes: self.run_operation('uninstall', client, repo) if yes else None)
        except GalaxyError as error:
            self.status(str(error))

    @work(group='module-api')
    async def run_operation(self, action: str, client: GalaxyClient, *args):
        if self.busy:
            return
        self.busy = True
        for widget in self.query('Button, Input, Select'):
            widget.disabled = True
        self.status('Consultando o servidor… Fechar o painel não cancela operações já recebidas pelo Galaxy.')
        try:
            method = {'connect': client.connect, 'refresh': client.repositories,
                      'revisions': client.revisions, 'install': client.install, 'uninstall': client.uninstall}[action]
            result = await asyncio.to_thread(method, *args)
            if action == 'revisions':
                self.query_one('#module-revision-options', Select).set_options([(r, r) for r in result])
                self.status('Revisões obtidas no Tool Shed. Escolha explicitamente a revisão a instalar.')
            else:
                self.client = client
                self.query_one('#module-key', Input).value = ''
                self.render_repositories(result)
                outcome = {'connect': 'Conexão estabelecida.', 'refresh': 'Lista atualizada.',
                           'install': 'Solicitação de instalação enviada; confira os estados.',
                           'uninstall': 'Solicitação de remoção enviada; confira os estados.'}[action]
                self.status(f'{outcome} Destino: {client.url}. {len(result)} registros. '
                            'Estado retornado pelo Galaxy; use Atualizar para acompanhar operações. '
                            '“Instalado” não substitui um teste funcional da ferramenta.')
        except GalaxyError as error:
            if action == 'connect':
                self.client = None
                self.render_repositories([])
            self.status(str(error))
        except OSError:
            self.status('Não foi possível preparar o lock local da operação. Verifique as permissões do diretório de estado.')
        finally:
            self.busy = False
            for widget in self.query('Button, Input, Select'):
                widget.disabled = False
