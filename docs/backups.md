# Backups e restauração

Disponível no painel **Backups** e em `biosuite backups`. Suporta o Galaxy
26.1.2 gerenciado pelo BioSuite, com armazenamento local padrão. É um backup
completo e manual, em janela de manutenção; não é um snapshot do sistema operacional.

## Criar e conferir

No painel, escolha **Nativo** ou **Docker**, informe o diretório de destino e
confirme **Criar backup local**. No modo nativo, abra `sudo biosuite-config`.
No Docker, use o mesmo usuário/caminho `BIOSUITE_DOCKER_HOME` da instalação.

O banco precisa estar acessível. No Docker, se PostgreSQL estava parado, ele é
iniciado temporariamente e volta ao estado anterior. No nativo, deixe o serviço
PostgreSQL ativo. Jobs pendentes, pausados ou em execução e ferramentas em
instalação/remoção impedem a cópia: conclua ou cancele essas tarefas no Galaxy.
Não execute APT, alterações manuais de arquivos ou outros escritores em paralelo.

O BioSuite para Galaxy, confere novamente os jobs, exporta PostgreSQL em formato
custom e copia dados/configurações/ferramentas. O serviço volta a funcionar se
estava ativo. Falha durante a cópia também tenta reabrir o estado original.

```bash
sudo biosuite backups create --mode native --directory /srv/backups/biosuite --yes
biosuite backups list --directory /srv/backups/biosuite
biosuite backups verify --source /srv/backups/biosuite/backup-AAAA...
```

Os exemplos de leitura precisam de `sudo` quando o backup pertence a root.
Por padrão, usa `/var/backups/biosuite` no nativo e `backups/` no diretório
Docker gerenciado. Pastas são privadas (700), arquivos do backup usam modo 600.
O destino não pode estar dentro dos dados/código copiados.

**Listar backups locais** mostra data, modo e caminho; selecionar uma linha
preenche a origem, sem iniciar operações. A listagem não calcula checksums.
**Verificar integridade** lê todos os payloads e confere tamanho/SHA-256.
Isso detecta corrupção; não autentica a origem nem comprova que o SQL restaura.
Use somente backups de origem confiável.

## Conteúdo e espaço

Cada pasta completa contém `manifest.json`, `database.dump`, `data.tar` e
`inventory.json` com repositórios/revisões do Tool Shed. O manifesto registra
release Galaxy, PostgreSQL principal, data UTC, tamanhos e checksums.

- Nativo: `code.tar` inclui o checkout e ambiente Python do Galaxy;
  `config.tar` contém somente `galaxy.yml` e `job_conf.xml`. O diretório de
  dados completo inclui datasets, wrappers Tool Shed, dependências e metadados.
- Docker: `image.tar` guarda a imagem da instância parada, inclusive alterações
  na camada gravável; `data.tar` guarda o volume de dados. O backup PostgreSQL
  é lógico, sem copiar seus arquivos enquanto o banco está em execução.

Arquivos não são comprimidos: isso reduz trabalho de CPU, mas consome bastante
disco. Dependências e caches científicos também entram na cópia. Durante uma
restauração, reserve espaço adicional para staging, cópia de segurança, banco
provisório e diretórios de promoção. A verificação é conservadora (aproximadamente
três vezes os dados extraídos, até duas cópias da imagem Docker e espaço para
o banco). Filesystems dos destinos/banco também são conferidos. Falta de
permissões, inodes ou espaço ainda pode impedir a operação; o rollback protege
o ponto anterior quando uma etapa falha.

Payloads e manifesto são sincronizados antes de publicar o nome final. Uma
cópia incompleta permanece em `.incomplete-*`; não é listada como backup pronto.
Não há exclusão/retensão automática: remova cópias antigas somente depois de
conferir quais precisa guardar.

O backup contém credenciais do Galaxy e dados dos usuários. Não inclui os
remotes/senhas do rclone, a identidade do broker Cloudflare, o próprio painel,
pacotes APT, PostgreSQL global/roles ou um backup completo do SO. Guarde
separadamente a recuperação do endereço público.

## Ensaiar antes de restaurar

**Testar restauração em banco temporário** confere arquivos, extrai staging e
restaura SQL em outro banco. Verifica tabelas Galaxy e remove o banco temporário
ao terminar. Não substitui o banco ativo nem para Galaxy.

```bash
sudo biosuite backups rehearse --mode native --source /srv/backups/biosuite/backup-AAAA... --yes
```

O ensaio comprova a restauração do banco e a leitura/extração dos arquivos.
Não executa análises científicas nem inicia uma segunda instalação completa.
Tamanho/checksum, ensaio SQL e recuperação funcional são verificações distintas.

## Restaurar

Prepare primeiro uma instalação BioSuite compatível. A release Galaxy e a
versão principal PostgreSQL devem ser iguais às do backup. Nativo exige a mesma
distribuição, versão do SO e arquitetura, pois o ambiente Python também é copiado.
Docker exige a mesma arquitetura e Engine Linux no mesmo host do painel.
A versão do painel pode ser mais recente desde que suporte o formato do backup.

1. Selecione a pasta completa e o modo correto.
2. Informe um diretório gravável para o **backup de segurança**.
3. Confirme a substituição de banco, dados, ferramentas e configurações.
4. Aguarde a validação, criação da cópia de segurança e recuperação da aplicação.

```bash
sudo biosuite backups restore --mode native \
  --source /srv/backups/biosuite/backup-AAAA... \
  --directory /srv/backups/antes-da-restauracao --yes
```

No Docker, acrescente `--mode docker` aos comandos equivalentes. O processo
restaura SQL em banco temporário antes de substituir o destino. Cria uma cópia
completa obrigatória do estado atual, mantém o banco/diretórios anteriores e
promove os arquivos restaurados. Galaxy é iniciado temporariamente para conferir
API e HTML, inclusive quando estava parado. Ao terminar, conserva o estado
ativo/parado original. A porta local do destino é preservada. Usuários, senhas,
chaves API e administrador Galaxy voltam ao ponto do backup.

No Docker, usa a imagem guardada, mantém a senha PostgreSQL e os proxies do
destino e ajusta a conexão no config restaurado. O Compose fica fixado no ID dessa
imagem, sem reconstruí-la durante a restauração. Atualizar o painel não atualiza
a release/imagem Galaxy. A identidade Cloudflare do host não é substituída.

Se a promoção ou a verificação funcional falhar, tenta voltar ao banco e aos
arquivos anteriores. Depois da validação/commit, falhas de log ou limpeza não
apagam o banco recuperado. A cópia de segurança permanece mesmo após sucesso.

## Interrupções e limites

Há lock por instalação, compartilhado com instalação/controle de serviço.
O painel impede trocar de tela/sair durante uma operação. O diário privado
`maintenance.json` fica no diretório gerenciado Galaxy/Docker. No nativo, um
launcher padrão antigo é atualizado com uma proteção contra inicialização
durante manutenção pendente; a autorização de início pelo controlador é
volátil, em `/run/biosuite-backup`, e desaparece num reboot.

Se o controlador/máquina cair no meio de uma restauração ou o rollback não
terminar, Galaxy pode ficar parado e o diário bloqueia novas ações. **Não apague
o diário para forçar o início.** Confira sua fase, os nomes dos bancos/diretórios
anteriores e `safety_backup`; preserve esses arquivos. A recuperação após uma
interrupção abrupta exige revisão administrativa. Uma alternativa é restaurar
o backup de segurança em outra instalação compatível, validar os dados e só
então trocar o servidor. A operação entre banco e filesystem não é uma transação
única resistente a qualquer queda de energia.

Após sucesso, eventual limpeza incompleta fica registrada em `cleanup-*.json`.
Ela pode deixar banco/diretórios antigos consumindo espaço; não indica que o
backup de segurança deva ser apagado. Logs privados ficam em
`/var/log/biosuite-install/backups.log` (nativo) ou `backups.log` no diretório Docker.

Esta versão recusa datasets externos, object stores personalizados, executores
remotos no nativo, volumes Docker adicionais e configurações fora do layout
local suportado. A restauração nativa por troca de diretórios exige que os
próprios diretórios de dados/código não sejam pontos de montagem: monte o disco
no diretório pai ou restaure em destino padrão compatível. A cópia pode ser
criada em uma origem montada, mas essa promoção não é suportada nesse destino.
Backups online, retenção, agendamento e migração entre modos/versões não estão
incluídos.

## rclone

Instale `rclone` pelo gerenciador da distribuição e execute `rclone config` no
usuário que usará o painel. Prefira um remote `crypt` e armazenamento privado.
O painel lista nomes de remotes existentes; não pede nem grava tokens no projeto.
No modo root, a configuração rclone é a de root, ou a indicada explicitamente
por `RCLONE_CONFIG` num caminho privado e acessível.

```bash
biosuite backups remotes
biosuite backups upload --source /srv/backups/biosuite/backup-AAAA... \
  --remote meucrypt:biosuite --yes
biosuite backups download --remote meucrypt:biosuite/backup-AAAA... \
  --directory /srv/backups/recebidos --yes
```

O upload copia somente manifesto/payloads para uma pasta com o nome do backup,
usa `--immutable`, não sincroniza/exclui o destino e faz leitura remota de
conferência (`rclone check --download`). Pode levar tempo proporcional ao volume
inteiro. O download recebe o caminho remoto **exato da pasta do backup**, grava
em `.incoming-*`, verifica checksums e só então publica uma pasta nova. Não
restaura automaticamente. Depois de baixar, execute o ensaio e a restauração
normal. As cotas, autenticação e custos são os do provedor escolhido.

## Validação

Os testes unitários cobrem corrupção/travessia de caminhos, symlinks, jobs
pendentes, restauração de arquivos, falhas de promoção/saúde, rollback, perda
do terminal, interrupção depois do commit, lock/diário e confirmações da interface.
O rclone real foi testado com alias local, cópia imutável, leitura e download;
um provedor de nuvem real ainda depende da configuração do operador.

Galaxy/PostgreSQL Docker reais passaram por backup, ensaio, restauração e
rollback SQL com falha injetada. Um registro e arquivo de dataset foram
recuperados e lidos pelo object store oficial com usuário sem privilégios;
API/HTML e o estado ativo/parado foram conferidos. Os fixtures usam somente
uma instância vazia e dados fictícios.

Os workflows manuais `Docker Galaxy integration` e `Native Galaxy integration`
têm a opção **backups**. Ela acrescenta os testes completos, exige mais disco
e aumenta o tempo máximo. O fluxo nativo com PostgreSQL/systemd reais está
preparado para as VMs Ubuntu, mas não foi executado neste ambiente (PID 1 não
é systemd). Não use esses scripts em produção: eles semeiam dados de teste e
recusam bancos que já tenham usuários/datasets/jobs.
