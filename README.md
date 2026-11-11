# BioSuite

Suite de administração do [Galaxy](https://github.com/galaxyproject/galaxy),
com painel interativo no terminal e instalação de ferramentas sob demanda.

**Estado: instalação nativa/Docker, ferramentas e manutenção.** O bootstrap
instala o painel Python. A tela Instalação prepara Galaxy 26.1.2/PostgreSQL,
com escolha do modo e da porta local (padrão 8080). Há atualizações do painel
e APT e um cliente de subdomínios Cloudflare. O broker BioSuite precisa ser
publicado separadamente. Backups locais, restauração e transporte rclone estão
implementados; Windows continua pendente. Veja o [guia de backups](docs/backups.md).

## Abrir e instalar pelo painel

O comando permanente é **`biosuite-config`** (também disponível como `biosuite`).
Abra com `sudo biosuite-config` para instalar e controlar serviços do sistema.
Na instalação por usuário, use `sudo "$HOME/.local/bin/biosuite-config"` quando
precisar dessas ações. O `config.sh` do Nexus é preservado.

Em **Instalação**, selecione Nativo ou Docker, informe e-mail do administrador
e porta, revise o plano e
confirme a instalação. O painel mostra progresso, logs e estado. Veja o
[guia da instalação nativa](docs/instalacao-nativa.md) para requisitos,
primeiro acesso, recuperação e limitações. Veja também o
[guia de atualizações, Docker e conexão](docs/manutencao-e-docker.md).

## Módulos no painel

Abra **Ferramentas**, informe a URL de um Galaxy existente e sua chave de API
de administrador e clique em **Conectar**. A chave fica apenas em memória;
também é possível fornecer `GALAXY_URL` e `GALAXY_API_KEY` no ambiente local.
Não envie chaves pelo chat nem as salve no repositório.

- Catálogo: pesquise repositórios no Tool Shed, com páginas de 10 resultados,
  ou escolha entre 10 atalhos organizados por área. Buscar e consultar revisões
  não exigem um Galaxy conectado nem chave de API.
- Instalação: conecte seu Galaxy, escolha o repositório e uma revisão e confirme
  o plano. Selecionar um resultado de busca apenas preenche o formulário.
- Acompanhamento: use **Atualizar estado** para consultar o servidor.
- Desinstalação: selecione uma linha, confira o repositório, revisão e ID e
  confirme a remoção pelo Galaxy.

O preset QIIME 2 cobre apenas Feature Table. Os wrappers oficiais atuais
dependem de Docker no destino de execução do Galaxy; esse requisito não é
instalado automaticamente. A integração foi verificada com testes simulados
da API e do painel; a instalação e uma análise científica em Galaxy real ainda
precisam de validação. Consulte o [guia dos módulos](docs/modulos.md).

Atalhos atuais: FastQC, MultiQC, fastp, Cutadapt, Trimmomatic, Bowtie 2, BWA,
SPAdes, IQ-TREE e QIIME 2 Feature Table. A busca pública permite descobrir outros
repositórios sem precisar de uma nova versão do BioSuite. Disponibilidade no
catálogo não significa compatibilidade ou execução científica já validadas.

## Instalar no Ubuntu ou Debian com um comando

Matriz do painel: **Ubuntu 22.04/24.04 e Debian 12/13, x86_64**.
Com `curl` disponível, execute no terminal:

```bash
bash -o pipefail -c 'curl -fsSL https://raw.githubusercontent.com/PauloFBaldiFH/BioSuite/main/installer | bash'
```

Esse endereço funciona quando esta entrega estiver na `main`. Para testar outra
branch, use o arquivo `installer` dessa branch e passe `--ref NOME_DA_BRANCH`
ao Bash que o executa. O script baixa o BioSuite do GitHub, prepara o ambiente
Python e abre o painel quando há um terminal interativo. Em uma sessão SSH,
use um terminal alocado; em automação, use `--no-launch`.

Quando faltam pré-requisitos, instala somente os pacotes necessários via APT
(`python3`, `python3-venv`, `git` e `ca-certificates`). Esse passo pode pedir
`sudo`; o painel não exige root. Não faz upgrade geral do sistema nem instala
Galaxy, PostgreSQL, QIIME 2 ou IQ-TREE.

Por padrão, a instalação pertence ao usuário:

- Ambientes: `${XDG_DATA_HOME:-~/.local/share}/biosuite/releases`.
- Comandos: `~/.local/bin/biosuite-config` e `~/.local/bin/biosuite`.

Para abrir novamente de qualquer diretório:

```bash
~/.local/bin/biosuite-config
```

Se `~/.local/bin` já estiver no `PATH`, basta `biosuite-config`. O instalador mostra o
comando para acrescentar esse diretório na sessão quando necessário e não
altera seus arquivos de shell. Quando executado como root, usa `/opt/biosuite`
e os comandos em `/usr/local/bin`.

Reexecutar o comando cria um novo ambiente, verifica importação do painel e
diagnóstico, e só então troca a instalação ativa. A versão anterior é mantida;
uma falha na preparação mantém o painel anterior disponível. Um lock impede
duas instalações simultâneas no mesmo prefixo. Versões antigas não são removidas
automaticamente.

Também é possível baixar o script, inspecioná-lo e executar:

```bash
bash installer --check       # lista plataforma e pré-requisitos, sem instalar
bash installer --no-launch   # instala sem entrar no painel
```

`--check` não certifica prontidão do Galaxy. Para instalação a partir de um
checkout local: `bash installer --source "$PWD"`. `--prefix` e `--bin-dir`
permitem escolher caminhos absolutos.

## Executar a base no checkout de desenvolvimento

Com Python 3.10+ e suporte a `venv`, no checkout do projeto:

```bash
bash scripts/install.sh
.venv/bin/biosuite-config
```

No Ubuntu ou Debian, caso necessário, instale os pré-requisitos com
`sudo apt install python3 python3-venv`. O bootstrap precisa de acesso ao PyPI,
instala apenas o BioSuite em `.venv` e não requer execução com `sudo`.
Execute-o novamente após alterações no código para atualizar o pacote instalado.

O painel tem navegação por mouse e teclado, menu lateral com rolagem e telas
Início, Instalação, Ferramentas, Backups, Conexão, Atualizações e Diagnóstico.
Atalhos: `d` para diagnóstico, `p` para plano e `q` para sair.
A gestão de ferramentas exige um Galaxy configurado. Backups e restauração
operam em janela de manutenção, com verificação e backup de segurança.
Conexão pública exige publicar e configurar o
[broker adaptado](broker/README.md) antes de usar o painel.

Também é possível consultar sem abrir o painel:

```bash
.venv/bin/biosuite doctor
.venv/bin/biosuite --storage /caminho/dos/dados plan
```

`doctor` lista fatos locais em JSON. Seu código de saída zero indica que o
levantamento terminou, não que a máquina está pronta para instalar Galaxy.
Para caminhos ainda inexistentes, o espaço é medido no ancestral existente.

## Desenvolvimento e testes

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

Os testes cobrem diagnóstico, matriz de distribuições, preservação da instalação
anterior quando uma atualização falha, contratos simulados da API Galaxy,
confirmação e cancelamento de operações, e navegação em terminais de 110×40 e 80×24.
O teste real Docker `tests/docker-smoke.py` verificou API, HTML, JavaScript,
catálogo básico, schema PostgreSQL e persistência após parar/iniciar/reinstalar
com porta personalizada 8082. Há workflow manual para repetir essa integração.
A CI também instala o painel por pipe e reexecuta a instalação nas quatro
distribuições, em containers descartáveis. O usuário não precisa de Docker
para instalar o BioSuite. A integração nativa tem um teste separado em
`tests/native-smoke.sh` e workflow manual: Galaxy/PostgreSQL reais, API, HTML,
JavaScript, catálogo básico e reexecução preservando configuração foram
verificados em Debian 12/13 e Ubuntu 22.04/24.04. Os testes mais recentes
conferiram também portas alternativas e preservação de um arquivo de dados.
Em VMs Ubuntu 22.04/24.04, instalação, stop/start via systemd, backup completo,
restauração de dataset e rollback com falha injetada também passaram
([execução no Actions](https://github.com/PauloFBaldiFH/BioSuite/actions/runs/42887838165)).
Em VMs Debian 12/13, o mesmo ciclo passou, incluindo reboot real e início
automático com configuração e dataset preservados
([execução no Actions](https://github.com/PauloFBaldiFH/BioSuite/actions/runs/43048527427)).
O staging dos backups usa disco no diretório gerenciado; outro disco pode ser
selecionado com `BIOSUITE_BACKUP_STAGING`, conforme o [guia](docs/backups.md).
Reboot no Ubuntu, análises científicas, Windows/WSL e a publicação real no Cloudflare ainda
precisam de validação. Os testes do broker executam Worker/D1/filas/DO locais
e cliente Python real com API Cloudflare simulada.

## Objetivo da primeira versão

- Galaxy nativo no Linux e no Windows por WSL2.
- Painel Python com Textual para instalação, serviços, diagnóstico e logs.
- Catálogo de ferramentas do Tool Shed, com instalação individual e conjuntos
  curados; nenhuma coleção científica pesada instalada automaticamente.
- Backups locais e em nuvem com rclone, com restauração verificada.
- Acesso por Cloudflare Tunnel e distribuição de subdomínios por um broker.

Consulte a [arquitetura e o plano de entrega](docs/arquitetura.md).

O [Koha Nexus](https://github.com/PauloFBaldiFH/koha.nexus) é a referência de
experiência de uso. O broker incorpora código GPLv3 desse projeto; veja os
[avisos de terceiros](THIRD_PARTY_NOTICES.md) e [LICENSE](LICENSE).
