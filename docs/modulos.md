# Módulos de ferramentas

Nesta versão, um módulo corresponde a um repositório do Tool Shed, em uma
revisão exata, instalado em um Galaxy existente. O BioSuite usa a API oficial
para listar, instalar e remover esses repositórios. Não executa `pip install`
de programas científicos no ambiente do painel.

## Pré-requisitos

- Galaxy acessível, com um administrador e sua chave de API.
- Configuração de instalação do Tool Shed habilitada no Galaxy, incluindo
  painel de ferramentas e resolvers de dependências compatíveis com os módulos.
- Espaço e permissões no servidor Galaxy; os dados não são baixados no host
  do painel quando ele está em outra máquina.
- Acesso do Galaxy ao Tool Shed e aos repositórios de suas dependências.
  A consulta de revisões também precisa que a máquina do painel acesse
  `toolshed.g2.bx.psu.edu` por HTTPS.

Use HTTPS para um servidor remoto. HTTP só é aceito para localhost ou endereços
loopback. Galaxy sob um subcaminho, como `https://host/galaxy`, é suportado;
informe a URL final, sem query, fragmento ou credenciais embutidas. Redirects
são recusados para impedir encaminhamento da chave. A chave é enviada no header
`x-api-key`, nunca na URL nem nas consultas públicas ao Tool Shed.

## Fluxo no painel

1. Entre em **Ferramentas**, informe URL e chave e clique em **Conectar**.
   O BioSuite consulta a conta atual e a lista de repositórios. Isso comprova
   autenticação e leitura; a autorização administrativa é exigida pelo Galaxy
   ao executar uma instalação ou remoção.
2. Escolha um preset ou informe proprietário e nome de outro repositório.
3. Clique em **Consultar revisões** e escolha uma revisão. Também é possível
   informar uma revisão do Tool Shed manualmente. Uma revisão GitHub não é
   substituta para a revisão Mercurial do Tool Shed.
4. Clique em **Revisar instalação**, confira destino, proprietário, nome e
   revisão e confirme. Dependências de repositório e do resolver são solicitadas
   ao Galaxy. Os mecanismos legados de `tool_dependencies.xml` ficam desativados.
5. Use **Atualizar estado** para acompanhar. O painel conserva o estado real
   retornado pelo Galaxy, inclusive etapas intermediárias e erros.

Nenhuma consulta ou alteração é feita só por abrir a tela. As chamadas rodam
fora da thread da interface; os controles do formulário ficam bloqueados durante
uma requisição. Fechar o painel não cancela uma tarefa já recebida pelo Galaxy.
Não há acompanhamento automático em segundo plano nesta versão.

Uma falha de rede ou timeout depois do envio não prova que a operação falhou no
servidor. Atualize a lista antes de decidir se precisa enviar outra solicitação.
O cliente não repete POST/DELETE automaticamente. Um lock local impede duas
operações BioSuite do mesmo usuário e URL ao mesmo tempo; não substitui o
controle de concorrência do Galaxy ou de outros administradores.

## Catálogo inicial e limites

| Preset | Proprietário / repositório | Observação |
| --- | --- | --- |
| IQ-TREE | `iuc/iqtree` | Dependências pelo resolver configurado no Galaxy. |
| QIIME 2 Feature Table | `q2d2/suite_qiime2__feature_table` | Plugin específico, com wrappers oficiais que usam Docker. |
| Outro repositório | Informado pelo administrador | Compatibilidade deve ser verificada antes de instalar. |

Os nomes foram conferidos nos `.shed.yml` dos projetos
[tools-iuc](https://github.com/galaxyproject/tools-iuc/tree/main/tools/iqtree)
e [qiime2/galaxy-tools](https://github.com/qiime2/galaxy-tools).
A implementação consulta as revisões disponíveis, sem presumir que o HEAD do
GitHub já esteja publicado no Tool Shed.

O QIIME 2 atual consultado (`8ff4403201defd5dced2ceeffcf668aeb19ae3ac`)
declara imagens `quay.io/qiime2/amplicon`. Para usar esses wrappers, configure
previamente um destino de jobs do Galaxy com suporte a Docker. Não se trata
de instalar todo o Galaxy em Docker. Uma alternativa totalmente nativa precisa
de wrappers e resolvers próprios validados; ela ainda não foi implementada.

## Desinstalação

Selecione uma linha e clique em **Desinstalar selecionado**. A confirmação
mostra nome, proprietário, revisão e ID. Antes do DELETE, o BioSuite consulta
novamente o registro; se ele mudou, exige nova seleção e confirmação.
Repositórios ainda em instalação não são removidos por este fluxo.

O pedido usa `remove_from_disk=true`: o Galaxy decide a remoção do repositório.
O BioSuite não solicita exclusão de históricos ou datasets e não faz limpeza
global de ambientes Conda. Verifique jobs e workflows dependentes antes de remover.

Uma suíte pode instalar outros repositórios como dependências. Remover o registro
da suíte não implica remover recursivamente esses outros registros; eles aparecem
individualmente na lista. Não eliminamos dependências compartilhadas por conta
própria, nem prometemos recuperar todo o espaço usado por uma instalação.

## Validação realizada

Testes com transporte HTTP simulado verificam endpoints, headers e payloads,
estados pendentes, bloqueio de duplicatas, revisão/ID alvo, falhas, timeout sem
reenvio, redirecionamentos e ausência da chave nas consultas públicas.
Os testes headless do painel verificam conexão, cancelamento e confirmação de
instalação e desinstalação.

Ainda não foi feita instalação em um Galaxy real nem executada uma análise
IQ-TREE/QIIME 2. Status `Installed` indica o estado informado pelo Galaxy;
ele não certifica execução científica, recursos suficientes ou qualidade dos
resultados. A instalação nativa da base Galaxy permanece uma entrega separada.
