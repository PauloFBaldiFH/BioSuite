# Instalação nativa do Galaxy

O BioSuite oferece um instalador inicial do Galaxy com PostgreSQL e serviço
systemd. A release é fixada em **26.1.2**, commit
`391641a4e121216de4764ffd12b8c666859460ea`, com a interface pré-compilada oficial.
O instalador não atualiza a release automaticamente e não substitui um Galaxy
que já existia na máquina.

## Comando permanente do painel

O bootstrap cria **`biosuite-config`** e mantém `biosuite` como alternativa.
Ambos abrem o mesmo painel Python. Não cria nem substitui o `config.sh` do Nexus.

Na instalação por usuário, o comando fica em `~/.local/bin/biosuite-config`.
Na instalação como root, fica em `/usr/local/bin/biosuite-config`.
O bootstrap informa se o diretório ainda precisa entrar no `PATH`.
Em um checkout de desenvolvimento, `bash scripts/install.sh` também cria o
comando `.venv/bin/biosuite-config` no ambiente Python local.

Para uma instalação de sistema (após esta entrega estar na main):

```bash
bash -o pipefail -c 'curl -fsSL https://raw.githubusercontent.com/PauloFBaldiFH/BioSuite/main/installer | sudo -H bash'
sudo biosuite-config
```

Abra **Instalação**, informe o e-mail do administrador e a porta local, revise
o plano e confirme **Instalar Galaxy**. As ações de sistema exigem root; o
Galaxy em si executa como `biosuitegalaxy`, sem privilégios de administrador.
O painel não pede nem armazena sua senha de sudo.

## Recursos e arquivos

Alvos: Ubuntu 22.04/24.04 e Debian 12/13, em x86_64, com Python 3.10+.
Para o serviço automático, systemd deve ser o PID 1. Na instalação inicial,
a porta escolhida precisa estar livre e a partição do código precisa ter
pelo menos 15 GiB disponíveis. Isso é apenas um limite de entrada para a base;
datasets, ambientes científicos e referências exigem espaço e RAM adicionais.

| Recurso | Local |
| --- | --- |
| Código e ambiente Python Galaxy | `/opt/biosuite-galaxy/galaxy` |
| Dados, jobs e dependências | `/var/lib/biosuite-galaxy` |
| Configuração principal | `/etc/biosuite/galaxy.yml` |
| Execução local dos jobs | `/etc/biosuite/job_conf.xml` |
| Serviço | `biosuite-galaxy.service` |
| Log persistente da instalação | `/var/log/biosuite-install/galaxy.log` |
| Logs dos processos Galaxy | `/var/log/biosuite-galaxy` |

O banco e a role PostgreSQL chamam-se `biosuitegalaxy`. A autenticação usa peer
no socket local, sem senha de banco gravada em arquivos. O instalador não muda
`pg_hba.conf`, não remove bancos e não faz upgrade geral dos pacotes do sistema.
Recursos preexistentes sem os marcadores de propriedade do BioSuite são recusados.

Configuração e dados ficam separados do checkout. O segredo interno do Galaxy
é gerado aleatoriamente e a configuração tem permissão 0600. Reexecutar uma
instalação preparada preserva esses arquivos, banco e release. Alterar e-mail
ou porta por uma nova execução é recusado para não reescrever configurações
silenciosamente. Após uma falha, verifique o log antes de retomar. Uma falha
entre criar um recurso e registrar sua propriedade pode exigir inspeção manual;
o instalador prefere recusar a adotar automaticamente um recurso desconhecido.

Os pacotes Python seguem os pins oficiais da release. O bootstrap usa a opção
upstream para selecionar PyPI como índice adicional, sem desativar TLS ou alterar
checksums. São necessários GitHub, PyPI e os mirrors APT da distribuição. Ao
instalar ferramentas depois, Galaxy precisará também de acesso ao Tool Shed e
aos canais de dependências correspondentes.

## Primeiro acesso e ferramentas

O Galaxy escuta somente em `127.0.0.1`, na porta escolhida. Abra essa porta no
navegador da própria máquina; em um servidor remoto, use encaminhamento SSH.
O instalador não abre firewall nem publica o servidor na internet.

Cadastre uma conta na interface Galaxy usando o e-mail informado no instalador.
Essa conta terá permissão administrativa. Depois gere sua chave de API no
Galaxy e conecte a tela **Ferramentas** do BioSuite. Não há senha administrativa
padrão, e nenhuma chave de API é impressa nos logs da instalação.

O executor inicial admite dois jobs locais, com um slot por job. Isso não é um
dimensionamento para toda carga científica; ajuste conforme CPU, RAM e datasets.
Conda fica habilitado para inicializar e resolver dependências sob demanda.
O instalador não solicita uma coleção de ferramentas, bases de referência ou
imagens Docker. O QIIME 2 atual exige configuração adicional de containers no
destino de jobs, conforme o [guia de módulos](modulos.md).

## Serviço e diagnóstico

O painel oferece Estado, Iniciar, Parar, Reiniciar e Consultar logs. Parada e
reinicialização pedem confirmação porque podem afetar jobs em execução.
Também é possível usar a CLI:

```bash
biosuite-config galaxy plan --admin-email admin@example.org
sudo biosuite-config galaxy install --admin-email admin@example.org --yes
biosuite-config galaxy status
sudo biosuite-config galaxy restart
sudo biosuite-config galaxy logs
```

Não basta haver um PID ou porta aberta: o instalador automático aguarda resposta
da API de versão e HTML da interface. Falhas não são convertidas em sucesso.
O acompanhamento de logs é persistente; perder o terminal não fecha o stdout
do instalador. O painel impede saída normal por `q` enquanto sua ação está
em andamento. Isso não substitui backups ou um mecanismo de rollback de migrações.

`--no-service` é uma opção avançada de preparação para testes e execução manual
sem systemd. Ela instala dependências e aplica migrações, mas não inicia nem
declara saudável o serviço Galaxy. Nessa modalidade, execute como usuário de
serviço o wrapper `/opt/biosuite-galaxy/start` após conferir o PostgreSQL local.
Não use essa opção para anunciar um serviço automático como validado.

## Validação desta entrega

Foram executados testes com Galaxy e PostgreSQL reais em Debian 12/13 e
Ubuntu 22.04/24.04, em containers descartáveis. Nesta continuação, Debian 12
usou porta 8086 e Ubuntu 22.04 usou 8085; Debian 13/Ubuntu 24.04 foram
verificados na entrega anterior. A API de versão, o HTML, o JavaScript da
interface e o catálogo básico responderam; o esquema foi verificado no
PostgreSQL e a reexecução preservou a configuração. Os testes atuais também
verificaram a preservação de um arquivo de dados de teste. O teste fica em
`tests/native-smoke.sh`; há também um workflow manual de integração.

Esses containers não executam systemd como PID 1: neles o mesmo wrapper da
unidade foi iniciado em primeiro plano como `biosuitegalaxy`.

Em VMs Ubuntu 22.04/24.04 com systemd como PID 1, instalação, parada/início pelo
comando do painel, API/HTML/JavaScript, catálogo, schema e reexecução também
passaram. A mesma rodada validou backup, restauração de dataset e rollback com
falha injetada; veja a [execução de 10/11/2026](https://github.com/PauloFBaldiFH/BioSuite/actions/runs/42887838165),
commit `ff40f47`, e o [guia de backups](backups.md).
Ela revelou e permitiu corrigir a herança de um diretório de trabalho privado:
o instalador e os comandos PostgreSQL nativos usam `/` ao trocar para contas de
serviço, sem depender do acesso dessas contas ao diretório onde o painel foi aberto.

Reboot da VM, systemd em Debian e análises científicas ainda precisam de
validação própria. Os testes do painel, confirmação, CLI e tratamento de falhas
são separados dessa validação da aplicação real.

## Repetir a validação em ambiente descartável

O job `native` do workflow manual `Native Galaxy integration` cobre Ubuntu
22.04/24.04 e Debian 12/13. Instala Galaxy/PostgreSQL reais e verifica API, HTML, JavaScript,
catálogo básico, schema e reexecução preservando configuração e um arquivo de
dados. Usa porta alternativa 8087. Esses containers executam Galaxy em primeiro
plano com `--no-service`; não certificam o ciclo real via systemd.

O job separado `systemd` usa VMs descartáveis dos runners GitHub Ubuntu
22.04/24.04 e o mesmo teste em modo systemd. A execução citada acima passou
nas duas versões; para repetir, dispare o workflow no GitHub. A opção `backups`
acrescenta o ciclo completo de restauração. A branch dedicada
`validation/native-backups` também executa os dois testes completos por push.
Não troque esses runners por servidores de produção.

Em uma **VM descartável** com uma distribuição suportada e systemd como PID 1,
execute como root, a partir do checkout:

```bash
BIOSUITE_SMOKE_SYSTEMD=1 BIOSUITE_SMOKE_PORT=8087 bash tests/native-smoke.sh
```

Esse modo instala/inicia pelo caminho de produção, verifica HTTP, para e inicia
pelo comando do painel e repete as verificações após iniciar. O serviço é parado
ao sair do teste. **Não execute em um servidor com dados reais**: o teste cria
usuário, banco, configuração e um arquivo de dados de teste nos caminhos fixos
do BioSuite. O modo systemd recusa iniciar se PID 1 não for systemd. Uma
verificação estática da unidade, quando `systemd-analyze` estiver disponível,
não substitui essa execução real nem um teste após reinicialização da VM.

## Debian com systemd e reinicialização

O workflow `Debian VM systemd and reboot` cria guests QEMU Debian 12/13, em
x86_64, dentro de runners GitHub Ubuntu descartáveis. A action de VM está fixada
por commit. O teste não reinicia o runner host e não usa servidores de produção.
Pode ser disparado manualmente; pushes na branch dedicada
`validation/debian-reboot` também executam as duas VMs.

O controlador `tests/debian-vm-smoke.py` conecta somente ao alias SSH `debian`
criado pela action. Executa os testes nativos de instalação e backup, insere um
dataset fictício, registra o `boot_id` e agenda o reboot do guest. Aguarda outro
`boot_id` e confere o início automático do Galaxy, API/HTML, PostgreSQL, conteúdo
do dataset e checksum da configuração. A verificação após o reboot não inicia
o Galaxy manualmente. Os dados fictícios são removidos ao terminar.

O teste exige identificação explícita de VM descartável e recusa banco com
datasets existentes. Não o execute numa instalação real. Cache de imagem e
cópia dos resultados de volta ao host ficam desabilitados; backups e credenciais
não são enviados como artefatos. As anotações do Actions mostram a conclusão de
cada etapa e um resumo das falhas. A definição desse teste, por si só, não
comprova que Debian/systemd/reboot passaram; registre o resultado da execução.
