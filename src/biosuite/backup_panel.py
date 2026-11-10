"""Backup, ensaio, restauração e transporte; toda mutação pede confirmação."""
import asyncio
import json
from pathlib import Path

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Button, DataTable, Input, Label, RichLog, Select, Static

from biosuite import backups
from biosuite.backup_format import verify
from biosuite.modules import ConfirmModule
from biosuite.operations import OperationError


class BackupPanel(Vertical):
    DEFAULT_CSS = '''
    BackupPanel { height: auto; }
    BackupPanel Input, BackupPanel Button, BackupPanel Select { margin-bottom: 1; }
    #backup-table { height: 8; }
    #backup-log { height: 15; border: round #24445c; }
    #backup-status { height: auto; padding: 1; color: #fbbf24; }
    '''

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.busy = False

    def compose(self) -> ComposeResult:
        yield Static('Backup completo em janela de manutenção para instalações gerenciadas, '
                     'com armazenamento local e jobs terminados. Nativo exige root/systemd; Docker exige acesso ao Engine. '
                     'Banco e arquivos precisam caber também no staging e no backup de segurança. '
                     'Backups contêm dados e credenciais: escolha armazenamento privado. '
                     'Checksums detectam corrupção; restaure somente cópias de origem confiável.')
        yield Select([('Galaxy nativo', 'native'), ('Galaxy Docker', 'docker')], value='native', allow_blank=False, id='backup-mode')
        yield Label('Diretório para novos backups e backup de segurança da restauração')
        yield Input('/var/backups/biosuite', id='backup-directory')
        yield Button('Listar backups locais', id='backup-list')
        yield DataTable(id='backup-table', cursor_type='row')
        yield Button('Criar backup local', id='backup-create', variant='primary')
        yield Label('Pasta de um backup completo')
        yield Input(placeholder='/var/backups/biosuite/backup-…', id='backup-source')
        yield Button('Verificar integridade', id='backup-verify')
        yield Button('Testar restauração em banco temporário', id='backup-rehearse')
        yield Button('Restaurar esta instalação', id='backup-restore', variant='error')
        yield Label('Destino/origem rclone já configurado (ex.: meucrypt:biosuite)')
        yield Input(placeholder='remote:caminho', id='backup-remote')
        yield Button('Listar remotes locais', id='backup-remotes')
        yield Button('Copiar backup para rclone e conferir leitura', id='backup-upload')
        yield Button('Baixar backup do caminho remoto exato', id='backup-download')
        yield Static('Nenhuma cópia ou restauração foi iniciada.', id='backup-status')
        yield RichLog(id='backup-log', wrap=True, markup=False)

    def on_mount(self):
        self.query_one(DataTable).add_columns('Backup', 'Modo', 'Criado (UTC)', 'Integridade')

    def on_data_table_row_selected(self, event: DataTable.RowSelected):
        self.query_one('#backup-source', Input).value = str(event.row_key.value)

    def on_select_changed(self, event: Select.Changed):
        if event.select.id == 'backup-mode' and event.value in ('native', 'docker'):
            field = self.query_one('#backup-directory', Input)
            defaults = {str(backups.default_directory(mode)) for mode in ('native', 'docker')}
            if field.value in defaults:
                field.value = str(backups.default_directory(event.value))

    def on_button_pressed(self, event: Button.Pressed):
        event.stop()
        if self.busy:
            return
        action = event.button.id.removeprefix('backup-')
        mode = str(self.query_one('#backup-mode', Select).value)
        directory = Path(self.query_one('#backup-directory', Input).value).expanduser()
        source = Path(self.query_one('#backup-source', Input).value).expanduser()
        remote = self.query_one('#backup-remote', Input).value.strip()
        if action in ('verify', 'remotes', 'list'):
            self.run_action(action, mode, directory, source, remote)
            return
        message = {
            'create': f'Criar backup {mode} em {directory}?\nGalaxy será parado durante a cópia e reaberto se estava ativo. Jobs pendentes impedem a operação.',
            'rehearse': f'Testar o backup confiável {source}?\nRestaura SQL em banco temporário e confere arquivos sem substituir a instalação ativa.',
            'restore': f'RESTAURAR {mode} usando {source}?\nSubstitui banco, dados, ferramentas e configuração desta instalação. '
                       f'Antes, testa a cópia e cria backup de segurança em {directory}. '
                       'A instância fica indisponível e será iniciada temporariamente para validação, mesmo se estava parada. Confirme a origem confiável do backup.',
            'upload': f'Copiar {source} para {remote}?\nO backup contém dados e credenciais. Configure um remote privado/crypt no rclone. '
                      'A cópia será imutável, sem excluir o destino; haverá leitura remota de conferência.',
            'download': f'Baixar o backup completo de {remote} para uma pasta nova em {directory}?\nNenhuma restauração será iniciada automaticamente.',
        }[action]
        self.app.push_screen(ConfirmModule(message),
                             lambda yes: self.run_action(action, mode, directory, source, remote) if yes else None)

    @work(group='backups')
    async def run_action(self, action, mode, directory, source, remote):
        if self.busy:
            return
        self.busy = True
        for widget in self.query('Button, Input, Select'):
            widget.disabled = True
        output = self.query_one(RichLog)
        status = self.query_one('#backup-status', Static)
        output.clear()
        status.update('Operação em andamento…')
        try:
            def line(text):
                self.app.call_from_thread(output.write, Text(text))
            if action == 'list':
                result = await asyncio.to_thread(backups.list_local, directory)
                table = self.query_one(DataTable)
                table.clear()
                for item in result:
                    table.add_row(Path(item['path']).name, item['mode'], item['created_utc'], 'Não conferida', key=item['path'])
            elif action == 'create':
                path = await asyncio.to_thread(backups.create, mode, directory, line)
                self.query_one('#backup-source', Input).value = str(path)
                result = {'backup': str(path)}
            elif action == 'verify':
                info = await asyncio.to_thread(verify, source)
                result = {'integrity': 'verified', 'mode': info['mode'], 'created_utc': info['created_utc'],
                          'galaxy_release': info['galaxy_release'], 'database_restore': 'not_tested'}
            elif action == 'rehearse':
                result = await asyncio.to_thread(backups.rehearse, mode, source, line)
            elif action == 'restore':
                result = await asyncio.to_thread(backups.restore, mode, source, directory, line)
            elif action == 'remotes':
                result = await asyncio.to_thread(backups.remotes)
            elif action == 'upload':
                result = await asyncio.to_thread(backups.upload, source, remote, line)
            else:
                result = await asyncio.to_thread(backups.download, remote, directory, line)
                self.query_one('#backup-source', Input).value = result['downloaded']
            output.write(Text(json.dumps(result, ensure_ascii=False, indent=2)))
            status.update('Operação concluída. Integridade, ensaio do banco e recuperação da aplicação são verificações distintas.')
        except (OperationError, OSError, ValueError, KeyError) as error:
            status.update(Text(str(error)))
        finally:
            self.busy = False
            for widget in self.query('Button, Input, Select'):
                widget.disabled = False
