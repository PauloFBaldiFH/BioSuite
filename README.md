# BioSuite

Suite de administração do [Galaxy](https://github.com/galaxyproject/galaxy),
com painel interativo no terminal e instalação de ferramentas sob demanda.

**Estado: primeira base funcional.** O bootstrap instala o painel Python;
o painel oferece diagnóstico local e uma prévia das etapas de instalação.
A instalação do Galaxy e as integrações científicas, de backup e de conexão
ainda estão em desenvolvimento.

## Executar a base atual

Com Python 3.10+ e suporte a `venv`, no checkout do projeto:

```bash
bash scripts/install.sh
.venv/bin/biosuite
```

No Ubuntu, caso necessário, instale os pré-requisitos com
`sudo apt install python3 python3-venv`. O bootstrap precisa de acesso ao PyPI,
instala apenas o BioSuite em `.venv` e não requer execução com `sudo`.
Execute-o novamente após alterações no código para atualizar o pacote instalado.

O painel tem navegação por mouse e teclado, menu lateral com rolagem e telas
Início, Instalação, Ferramentas, Backups, Conexão e Diagnóstico.
Atalhos: `d` para diagnóstico, `p` para plano e `q` para sair.
Somente diagnóstico e prévia do plano estão operacionais; as demais integrações
são apresentadas como funcionalidades em desenvolvimento.

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

Os testes cobrem o diagnóstico, a prévia de máquina fora do alvo e a navegação
do painel em terminais de 110×40 e 80×24. Não validam uma instalação real do
Galaxy, PostgreSQL, ferramentas científicas, Windows/WSL ou Cloudflare.

## Objetivo da primeira versão

- Galaxy nativo no Linux e no Windows por WSL2.
- Painel Python com Textual para instalação, serviços, diagnóstico e logs.
- Catálogo de ferramentas do Tool Shed, com instalação individual e conjuntos
  curados; nenhuma coleção científica pesada instalada automaticamente.
- Backups locais e em nuvem com rclone, com restauração verificada.
- Acesso por Cloudflare Tunnel e distribuição de subdomínios por um broker.

Consulte a [arquitetura e o plano de entrega](docs/arquitetura.md).

O [Koha Nexus](https://github.com/PauloFBaldiFH/koha.nexus) é a referência de
experiência de uso. As operações específicas do Koha serão substituídas por
integrações próprias do Galaxy.
