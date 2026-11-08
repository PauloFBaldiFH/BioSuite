# Arquitetura inicial do BioSuite

Proposta baseada nos requisitos do projeto e na leitura dos repositórios
Koha Nexus e Galaxy. Estão implementados o painel, o diagnóstico, a gestão de
repositórios e a instalação nativa inicial Galaxy/PostgreSQL. API e interface
foram verificadas em Debian 13 e Ubuntu 24.04. Os demais componentes e a execução
automática via systemd ainda têm validações pendentes; veja o
[guia da instalação nativa](instalacao-nativa.md).

## Referências consultadas

- Koha Nexus: `d6fcb70ee8dce8e3d685502a501825ef893e33af`.
  Referências principais: `panel/README.md`, `panel/kei_panel/cloud.py`,
  `panel/requirements.txt` e `broker/README.md`.
- Galaxy: `e08a4b559ad8b8e789a64c2eff85d3d91dc17484`.
  Referências iniciais: `README.rst` e `pyproject.toml`.
  O código consultado exige Python >= 3.10. A versão de produção deverá ser
  uma release estável fixada, com requisitos conferidos nessa release,
  em vez de instalar automaticamente a branch de desenvolvimento.
  O instalador agora fixa a release 26.1.2, commit
  `391641a4e121216de4764ffd12b8c666859460ea`, usando seu bootstrap e cliente
  pré-compilado oficiais.

## Instalação e execução

O bootstrap do painel cobre Ubuntu 22.04/24.04 e Debian 12/13, em x86_64,
com instalação por um comando e launcher permanente. Os testes Linux usam
containers apenas para isolar as distribuições: a instalação final é nativa.
A mesma matriz é alvo da instalação Galaxy. Debian 13 e Ubuntu 24.04 tiveram
validação funcional em primeiro plano; ciclo systemd, versões mais antigas e
ferramentas científicas exigem validação própria.
No Windows, usar Ubuntu em WSL2, com systemd e os dados no filesystem Linux;
evitar armazenar datasets e ambientes científicos em `/mnt/c`.
Outras distribuições e arquiteturas só serão anunciadas após testes próprios.

Instalar Galaxy nativamente, com usuário de serviço sem privilégios, ambiente
Python próprio, PostgreSQL e gerenciamento de processos compatível com a
release escolhida. Separar o ambiente Python do painel do ambiente do Galaxy.
Não há necessidade de Docker no fluxo padrão. Isso não garante maior
desempenho em toda carga: disco, memória, paralelismo e acesso aos dados
também precisam de medição.

O instalador verificará distribuição, arquitetura, CPU, RAM, espaço e inodes,
portas ocupadas e serviços existentes antes de apresentar o plano. Os limites
de execução dos jobs serão configurados conforme os recursos disponíveis.
Sem tamanho mínimo universal: módulos e bases de referência têm custos
muito diferentes, que precisam ser mostrados separadamente.

Usar releases fixadas e verificações de integridade disponíveis. Reexecutar
o instalador deve detectar o estado atual, retomar etapas incompletas e
preservar dados e configurações existentes. Atualizar Galaxy será uma ação
explícita, precedida de backup e avaliação das migrações.

## Painel e camada de operações

Usar Python e Textual, seguindo a experiência do Nexus: navegação por teclado
e mouse, tema escuro, painel de estado, progresso, diagnóstico e logs.
Telas principais: Início, Galaxy, Ferramentas, Backups, Conexão e Configurações.

As operações terão interfaces próprias, utilizáveis também por CLI, sem
acoplar lógica de instalação aos widgets. Tarefas longas precisam de lock,
registro persistente, estados de falha e retomada; uma instalação não pode
ser marcada como concluída só porque o processo foi iniciado.
Elevar privilégios apenas para operações de sistema que os exigem.
Ocultar credenciais dos logs e restringir permissões dos arquivos locais.

## Ferramentas científicas

O painel já possui um cliente da API do Galaxy para listar repositórios,
consultar revisões públicas no Tool Shed, solicitar instalação e remover um
repositório selecionado mediante confirmação. Essa integração exige um Galaxy
existente. Os testes atuais simulam a API; a execução científica ainda não
foi validada. Veja [Módulos](modulos.md) para requisitos e limites.

Integrar o catálogo e a instalação pelo Tool Shed/API do Galaxy e seus
resolvers de dependências. Conda não exige contêiner: cada dependência será
isolada conforme o mecanismo suportado pelo Galaxy. Não instalar todos os
pacotes científicos no Python do painel ou globalmente no sistema.

Oferecer busca geral e conjuntos curados por área. Cada ferramenta precisa
de proprietário, repositório, revisão e compatibilidade identificados.
Separar estados: disponível no catálogo, instalação solicitada, instalando,
instalada, falhou e teste funcional aprovado. Mostrar que estimativas de
espaço podem não incluir bases de referência e dados do usuário.

Primeiras ferramentas confirmadas pelo usuário: QIIME 2 e IQ-TREE.
O catálogo inicial identifica `iuc/iqtree` e o plugin QIIME 2 Feature Table
(`q2d2/suite_qiime2__feature_table`). Os wrappers oficiais atuais do QIIME 2
usam Docker, exigindo configuração própria do destino de jobs do Galaxy;
não há instalação automática desse runtime pelo painel.
Validar disponibilidade e wrappers na release
escolhida antes de prometer suporte. QIIME 2 pode envolver vários wrappers
e dependências volumosas; não será tratado como pacote leve.

“Todas as ferramentas” significa acesso ao catálogo expansível, com suporte
curado identificado. Não significa garantia de compatibilidade de todo wrapper
existente, nem instalação automática de todo o catálogo.

## Backup e restauração

O modelo de backup SQL do Koha não pode ser transposto diretamente. Galaxy
precisa do banco de dados, datasets, configurações e inventário das ferramentas;
object stores externos e bases de referência exigem políticas explícitas.
Dados e metadados precisam representar o mesmo ponto consistente.

A primeira implementação deve oferecer backup com janela de manutenção:
impedir novos jobs, aguardar ou interromper jobs de forma controlada e impedir
escritas antes da captura do banco e dos arquivos. Só liberar o serviço ao fim
da etapa consistente. Backups online ficam para uma estratégia validada própria.

Cada backup terá manifesto, versões, identificação do ponto de captura e
checksums. Validar conteúdo e integridade, testar a restauração em destino
isolado e criar backup de segurança antes de substituir uma instalação.
Restaurar primeiro para staging, com verificação de espaço, permissões,
versão do banco e acesso real a um dataset de teste.

rclone será o transporte para remotes configurados pelo usuário. Usar cópia
sem exclusão do destino por padrão; retenção e criptografia precisam de
configuração explícita. Um upload concluído não equivale a restauração validada.
Não embutir tokens no repositório; autenticação ocorre no ambiente do usuário.

## Conexão e subdomínios

Reaproveitar o desenho do broker do Nexus: Worker, D1, fila, Durable Object,
cadastro com chave Ed25519 e emissão de token limitado ao tunnel da instalação.
O token administrativo do Cloudflare permanece no serviço central.

Criar identidade e namespace próprios do BioSuite. O README do broker alerta
que duas instâncias na mesma conta podem reconciliar e remover tunnels uma
da outra. Rever a propriedade dos recursos e a reconciliação antes de qualquer
implantação conjunta; não copiar os identificadores e publicar o broker do
BioSuite ao lado do Nexus sem resolver esse isolamento.

O broker consultado documenta testes locais com uma API Cloudflare simulada
e ausência de validação em conta real. É uma referência de implementação,
não evidência de operação em produção.

O domínio do BioSuite ainda precisa ser definido. O subdomínio pode ser gratuito
para o usuário final, enquanto domínio, conta e recursos do serviço central
precisam ser mantidos pelo projeto. Não utilizar `koha.nexus` como padrão.
Não publicar dados nem endpoints administrativos automaticamente.
Galaxy exige análise de autenticação, dados sensíveis e limites de upload do
Cloudflare; arquivos grandes precisarão de um caminho de transferência adequado.

## Windows

O bootstrap PowerShell verificará os pré-requisitos do WSL2, instalará ou
selecionará uma distribuição compatível e chamará o mesmo instalador Linux.
Deve tratar reinicialização pendente, instalação existente, ativação do systemd,
limites de recursos, abertura do painel e parada limpa. Não remover nem
recriar uma distribuição existente silenciosamente. A validação Windows/WSL
precisa ocorrer em uma máquina Windows real.

## Etapas da primeira versão

1. Núcleo e painel: CLI, configuração, executor de tarefas, diagnóstico,
   testes de navegação e instalação base reproduzível do Galaxy/PostgreSQL.
   Aceite: abrir Galaxy, autenticar e executar uma análise pequena.
2. Módulos: catálogo Tool Shed, instalação sob demanda, progresso e detecção
   de erros. Aceite: executar exemplos das primeiras ferramentas confirmadas.
3. Dados: backup, restauração isolada e rclone. Aceite: recuperar banco e
   dataset de uma instalação de teste e conferir conteúdo.
4. Distribuição: bootstrap Windows/WSL2 e integração Cloudflare com broker
   isolado. Aceite: instalação Windows real e cadastro/recuperação de um
   subdomínio em conta de teste, sem afetar recursos do Nexus.

Todas as etapas pertencem ao escopo desejado da primeira versão. Entregas
incrementais permitem validar cada integração antes de anunciar o conjunto
como pronto. Publicação do broker e uso de serviços reais dependem da definição
do domínio e configuração segura das credenciais, sem valores em chat.

Se código do Nexus for incorporado, preservar os avisos e cumprir sua licença
GPLv3; este levantamento ainda não incorpora código daquele projeto.
