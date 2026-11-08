"""Manutenção do painel e do sistema operacional com plano e confirmação."""
import asyncio
import json

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Button, RichLog, Static

from biosuite import updates
from biosuite.modules import ConfirmModule
from biosuite.operations import OperationError


class UpdatePanel(Vertical):
    DEFAULT_CSS = '''
    UpdatePanel { height: auto; }
    UpdatePanel Button { margin-bottom: 1; }
    #update-log { height: 18; border: round #24445c; }
    #update-status { height: auto; color: #fbbf24; padding: 1; }
    '''

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.busy = False

    def compose(self) -> ComposeResult:
        yield Static('Atualizações do painel são separadas das do Galaxy. '
                     'APT usa as fontes já configuradas, preserva arquivos locais e não reinicia a máquina automaticamente.')
        yield Button('Atualizar listas APT', id='update-apt-lists')
        yield Button('Revisar upgrade do sistema', id='update-apt-plan')
        yield Button('Verificar atualização do painel', id='update-panel-plan')
        yield Static('Nenhuma atualização foi executada.', id='update-status')
        yield RichLog(id='update-log', wrap=True, markup=False)

    def on_button_pressed(self, event: Button.Pressed):
        event.stop()
        if not self.busy:
            self.run_action(event.button.id.removeprefix('update-'))

    @work(group='updates')
    async def run_action(self, action, plan=None):
        if self.busy:
            return
        self.busy = True
        for button in self.query(Button):
            button.disabled = True
        output = self.query_one(RichLog)
        output.clear()
        status = self.query_one('#update-status', Static)
        status.update('Consultando/executando a operação…')
        try:
            def line(text):
                self.app.call_from_thread(output.write, Text(text))
            if action == 'apt-lists':
                result = await asyncio.to_thread(updates.apt, 'update', line)
            elif action == 'apt-plan':
                result = await asyncio.to_thread(updates.apt_plan)
                self.app.push_screen(ConfirmModule('Plano APT (upgrade, sem dist-upgrade/autoremove):\n\n' + result
                                                   + '\n\nPode reiniciar serviços dos pacotes atualizados. Confirmar execução?'),
                                     lambda yes: self.run_action('apt-upgrade') if yes else None)
            elif action == 'apt-upgrade':
                result = await asyncio.to_thread(updates.apt, 'upgrade', line)
            elif action == 'panel-plan':
                plan = await asyncio.to_thread(updates.panel_plan)
                result = (f'Canal main\nInstalado: {plan.current_commit or "origem local"}\nDestino: {plan.commit}\n'
                          f'Instalação: {plan.prefix}\nComandos: {plan.bin_dir}')
                if plan.current_commit == plan.commit:
                    result += '\nO commit instalado já corresponde ao canal.'
                else:
                    self.app.push_screen(ConfirmModule(result + '\n\nAtualizar o painel? A sessão atual continua usando '
                                                       'a versão anterior até você reabrir biosuite-config.'),
                                         lambda yes: self.run_action('panel-apply', plan) if yes else None)
            else:
                await asyncio.to_thread(updates.update_panel, plan, line)
                result = 'Painel instalado. Saia e abra biosuite-config novamente.'
            output.write(Text(result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=2)))
            status.update('Operação concluída. Confira o resultado e eventual necessidade de reinicialização.')
        except (OperationError, OSError, TimeoutError) as error:
            status.update(Text(str(error)))
        finally:
            self.busy = False
            for button in self.query(Button):
                button.disabled = False
