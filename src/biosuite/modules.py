"""Gestão interativa de repositórios em um Galaxy existente."""

import asyncio
import os

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Label, Select, Static

from biosuite.catalog import BY_ID, CATALOG
from biosuite.galaxy import GalaxyClient, GalaxyError, Repository, SearchPage, ToolShedClient, ToolSpec

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
    #module-table, #module-search-table { height: 10; margin-bottom: 1; }
    #module-status { height: auto; padding: 1; color: #fbbf24; }
    '''

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.client: GalaxyClient | None = None
        self.repositories: list[Repository] = []
        self.selected: Repository | None = None
        self.busy = False
        self.shed = ToolShedClient()
        self.search_page: SearchPage | None = None

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
        yield Label('Catálogo público do Tool Shed — buscar não exige conexão ao Galaxy')
        yield Input(placeholder='Buscar por nome ou assunto (ex.: samtools, RNA, alignment)', id='module-search-query')
        yield Button('Buscar no Tool Shed', id='module-search')
        yield DataTable(id='module-search-table', cursor_type='row')
        with Horizontal():
            yield Button('Anterior', id='module-search-prev', disabled=True)
            yield Button('Próxima', id='module-search-next', disabled=True)
        yield Static('Clique em um resultado ou pressione Enter para preencher o formulário. '
                     'Resultados do catálogo não são ferramentas instaladas ou validadas.', id='module-search-info')
        yield Label('Novo módulo — escolha um preset ou informe outro repositório do Tool Shed')
        yield Select([(f'{preset.category} • {preset.label}', preset.id) for preset in CATALOG]
                     + [('Outro repositório', 'custom')], prompt='Escolha um módulo', id='module-preset')
        yield Static('Os atalhos preenchem identidades conferidas no código-fonte; escolha a revisão no Tool Shed.',
                     id='module-description')
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
        self.query_one('#module-table', DataTable).add_columns('Repositório', 'Proprietário', 'Revisão', 'Estado')
        self.query_one('#module-search-table', DataTable).add_columns('Repositório', 'Proprietário', 'Descrição')

    def status(self, message: str):
        self.query_one('#module-status', Static).update(Text(message))

    def render_repositories(self, repos: list[Repository]):
        self.repositories = repos
        self.selected = None
        table = self.query_one('#module-table', DataTable)
        table.clear()
        for repo in repos:
            table.add_row(*(Text(v) for v in (repo.name, repo.owner, repo.revision, repo.display_status)))

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted):
        event.stop()
        if event.data_table.id != 'module-table':
            return
        index = event.cursor_row
        self.selected = self.repositories[index] if index < len(self.repositories) else None

    def on_data_table_row_selected(self, event: DataTable.RowSelected):
        event.stop()
        if event.data_table.id != 'module-search-table' or self.search_page is None:
            return
        if event.cursor_row >= len(self.search_page.hits):
            return
        hit = self.search_page.hits[event.cursor_row]
        self.query_one('#module-preset', Select).value = 'custom'
        self.fill_repository(hit.name, hit.owner)
        self.query_one('#module-description', Static).update(Text(hit.description))
        self.status(f'Selecionado: {hit.owner}/{hit.name}. Consulte e escolha uma revisão antes de instalar.')

    def fill_repository(self, name: str, owner: str):
        self.query_one('#module-name', Input).value = name
        self.query_one('#module-owner', Input).value = owner
        self.query_one('#module-revision', Input).value = ''
        self.query_one('#module-revision-options', Select).set_options([])

    def catalog_buttons(self):
        page = self.search_page
        self.query_one('#module-search-prev', Button).disabled = self.busy or page is None or page.page <= 1
        self.query_one('#module-search-next', Button).disabled = self.busy or page is None or not page.has_next

    def on_select_changed(self, event: Select.Changed):
        event.stop()
        if event.select.id == 'module-preset':
            preset = BY_ID.get(event.value)
            if preset:
                self.fill_repository(preset.name, preset.owner)
                self.query_one('#module-description', Static).update(Text(preset.description))
        elif event.select.id == 'module-revision-options' and event.value is not Select.BLANK:
            self.query_one('#module-revision', Input).value = str(event.value)

    def on_button_pressed(self, event: Button.Pressed):
        event.stop()
        if self.busy:
            return
        action = event.button.id.removeprefix('module-')
        try:
            if action == 'search':
                self.run_operation('search', self.shed, self.query_one('#module-search-query', Input).value, 1)
                return
            if action in ('search-prev', 'search-next'):
                if self.search_page:
                    page = self.search_page
                    offset = -1 if action == 'search-prev' else 1
                    self.run_operation('search', self.shed, page.query, page.page + offset)
                return
            if action == 'revisions':
                self.run_operation('revisions', self.shed,
                                   self.query_one('#module-name', Input).value.strip(),
                                   self.query_one('#module-owner', Input).value.strip())
                return
            if action == 'connect':
                client = GalaxyClient(self.query_one('#module-url', Input).value,
                                      self.query_one('#module-key', Input).value)
                self.run_operation('connect', client)
                return
            if self.client is None:
                raise GalaxyError('Conecte primeiro ao Galaxy com uma chave de administrador.')
            client = self.client
            if action == 'refresh':
                self.run_operation(action, client)
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
    async def run_operation(self, action: str, client: GalaxyClient | ToolShedClient, *args):
        if self.busy:
            return
        self.busy = True
        for widget in self.query('Button, Input, Select'):
            widget.disabled = True
        self.status('Consultando o catálogo público do Tool Shed…' if action in ('search', 'revisions') else
                    'Consultando o servidor… Fechar o painel não cancela operações já recebidas pelo Galaxy.')
        try:
            method = getattr(client, {'connect': 'connect', 'refresh': 'repositories', 'search': 'search',
                                      'revisions': 'revisions', 'install': 'install', 'uninstall': 'uninstall'}[action])
            result = await asyncio.to_thread(method, *args)
            if action == 'search':
                self.search_page = result
                table = self.query_one('#module-search-table', DataTable)
                table.clear()
                for hit in result.hits:
                    table.add_row(*(Text(v) for v in (hit.name, hit.owner, hit.description)))
                self.query_one('#module-search-info', Static).update(Text(
                    f'Busca: {result.query} • Página {result.page} • {result.total} resultados. '
                    'Selecione uma linha para preencher o formulário; nenhuma instalação será feita.'))
                self.status('Busca concluída no Tool Shed.' if result.hits else 'Nenhum resultado para essa busca.')
            elif action == 'revisions':
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
            self.catalog_buttons()
