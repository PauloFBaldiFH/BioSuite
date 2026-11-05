"""Painel de diagnóstico e gestão de módulos em um Galaxy existente."""

import json
from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Footer, Header, Static

from biosuite.preflight import inspect_machine, installation_plan
from biosuite.modules import ModulePanel


class BioSuiteApp(App):
    TITLE = 'BioSuite'
    SUB_TITLE = 'Galaxy • administração modular'
    BINDINGS = [('q', 'quit', 'Sair'), ('d', 'diagnose', 'Diagnóstico'),
                ('p', 'plan', 'Plano')]
    CSS = '''
    Screen { background: #0b1220; color: #e2e8f0; }
    Header { background: #153243; color: #7dd3fc; }
    Footer { background: #153243; }
    #layout { height: 1fr; }
    #sidebar { width: 25; background: #101e30; padding: 1; }
    #brand { color: #5eead4; text-style: bold; margin-bottom: 1; }
    #sidebar Button { width: 100%; margin-bottom: 1; }
    #content { padding: 1 2; }
    #phase { color: #fbbf24; margin-bottom: 1; }
    #page-title { color: #5eead4; text-style: bold; margin-bottom: 1; }
    #page-body { padding: 1 2; border: round #24445c; height: auto; }
    '''

    def __init__(self, storage: Path | None = None):
        super().__init__()
        self.storage = storage if storage is not None else Path.cwd()

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id='layout'):
            with VerticalScroll(id='sidebar'):
                yield Static('BIO SUITE\nSeu Galaxy, sob controle.', id='brand')
                for label, name in [('Início', 'home'), ('Instalação', 'install'),
                                    ('Ferramentas', 'tools'), ('Backups', 'backup'),
                                    ('Conexão', 'connection'), ('Diagnóstico', 'doctor')]:
                    yield Button(label, id=name)
            with VerticalScroll(id='content'):
                yield Static('PRÉVIA • Galaxy não é instalado por esta versão', id='phase')
                yield Static('', id='page-title')
                yield Static('', id='page-body')
                yield ModulePanel(id='module-panel')
        yield Footer()

    def on_mount(self) -> None:
        self.show_page('home')

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id in ('home', 'install', 'tools', 'backup', 'connection', 'doctor'):
            self.show_page(event.button.id)

    def action_diagnose(self) -> None:
        self.show_page('doctor')

    def action_plan(self) -> None:
        self.show_page('install')

    def show_page(self, name: str) -> None:
        self.query_one('#module-panel').display = name == 'tools'
        if name == 'install':
            title = 'Instalação • planejar antes de alterar'
            body = installation_plan(inspect_machine(self.storage))
        elif name == 'doctor':
            title = 'Diagnóstico • leitura local atualizada'
            body = ('Este levantamento não testa a saúde do Galaxy ou do PostgreSQL.\n\n'
                    + json.dumps(inspect_machine(self.storage).as_dict(), ensure_ascii=False, indent=2))
        else:
            title, body = {
                'home': ('Bem-vindo ao BioSuite',
                         'Uma central para instalar, acompanhar e manter seu Galaxy.\n\n'
                         'Disponível agora\n• Diagnóstico da máquina\n• Prévia do plano de instalação\n'
                         '• Gestão de módulos em um Galaxy existente\n\n'
                         'Em desenvolvimento\n• Instalação nativa do Galaxy\n'
                         '• Backup e restauração\n• Acesso remoto\n\n'
                         'Comece por Diagnóstico e consulte o plano em Instalação.'),
                'tools': ('Ferramentas • módulos do Galaxy',
                          'Atalhos por área e busca paginada no catálogo público do Tool Shed.\n'
                          'Inclui IQ-TREE e QIIME 2 Feature Table.\n'
                          'Conecte seu Galaxy, escolha a revisão e confirme a operação.\n'
                          'Abrir esta tela não faz consultas ou instalações automaticamente.'),
                'backup': ('Backups • local e nuvem',
                           'Integração em desenvolvimento.\n\n'
                           'O backup incluirá banco, datasets, configurações e manifesto.\n'
                           'A restauração será testada em ambiente isolado antes de substituir dados.\n'
                           'rclone permitirá cópia para um destino escolhido por você.\n'
                           'Nenhum backup ou upload está sendo realizado.'),
                'connection': ('Conexão • Cloudflare Tunnel',
                               'Integração em desenvolvimento.\n\n'
                               'O domínio e o broker do BioSuite ainda precisam ser configurados.\n'
                               'O serviço terá identidade separada do Koha Nexus.\n'
                               'A publicação dependerá de uma ação explícita.\n'
                               'Nenhum tunnel ou subdomínio foi criado.'),
            }[name]
        self.query_one('#page-title', Static).update(Text(title))
        self.query_one('#page-body', Static).update(Text(body))
