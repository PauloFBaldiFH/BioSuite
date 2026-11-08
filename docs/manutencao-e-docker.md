# Atualizações, Docker e conexão

Abra `sudo biosuite-config` para operações de sistema. Para usar apenas o
Docker já disponível ao usuário, o painel pode rodar sem sudo; mantenha o mesmo
usuário nas próximas operações para localizar a instalação correta.

## Instalação

Na tela **Instalação**, selecione **Nativo** ou **Docker**, informe o e-mail
do administrador e a porta. O padrão de testes é **8080**, somente em
`127.0.0.1`. Use outra porta livre entre 1024 e 65535 se necessário. Revise o
plano antes de confirmar. O acesso remoto pode ser feito pelo túnel ou por
encaminhamento SSH. A instalação não abre o Galaxy para a rede inteira.

O modo nativo continua sendo o padrão e usa PostgreSQL/systemd no host.
O modo Docker constrói uma imagem do Galaxy 26.1.2 a partir do commit oficial
fixado, baixa seu cliente pré-compilado e inicia PostgreSQL 17 com Compose.
O banco não publica portas no host. Galaxy roda com usuário sem privilégios.
As ferramentas científicas são instaladas depois, sob demanda.

Use **Preparar Docker** se Engine/Compose estiverem ausentes. Essa ação exige
root e systemd e configura o repositório APT oficial em Ubuntu 22.04/24.04 ou
Debian 12/13. Uma instalação Docker existente não é substituída silenciosamente.
Docker já instalado e acessível pode ser usado sem preparar novamente.

Dados/configuração e banco ficam em volumes separados `biosuite-galaxy_data`
e `biosuite-galaxy_postgres`. Compose, recibo, log e senha privada ficam em
`/opt/biosuite-docker` para root, ou `~/.local/share/biosuite/docker` para usuário.
O projeto Compose é `biosuite-galaxy`: há uma instância gerenciada por host.
Uma configuração diferente ou volumes existentes sem recibo não são adotados
silenciosamente. Repetir a instalação com os mesmos parâmetros preserva dados,
configuração e senha. **Parar** não apaga volumes. Não apague volumes manualmente
sem ter backup verificado. O build inicial exige rede, disco e alguns minutos.

Exemplo por CLI:

```bash
biosuite galaxy plan --mode docker --admin-email admin@example.org --port 8082
biosuite galaxy install --mode docker --admin-email admin@example.org --port 8082 --yes
biosuite galaxy status --mode docker
biosuite galaxy logs --mode docker
biosuite galaxy stop --mode docker
biosuite galaxy start --mode docker
```

O Docker da instalação não configura automaticamente executores científicos
que exigem Docker dentro do Galaxy. Em particular, não é montado o socket Docker
no container Galaxy. Os wrappers QIIME 2 ainda exigem destino de jobs apropriado.

## Atualizações

A tela **Atualizações** oferece:

- **Atualizar listas APT**: executa `apt-get update` com as fontes do host.
- **Revisar upgrade do sistema**: simula `apt-get upgrade`, mostra os pacotes e
  pede confirmação antes de executar. Preserva arquivos de configuração locais
  nas decisões padrão do dpkg. Pacotes podem reiniciar serviços durante a atualização.
- **Verificar atualização do painel**: consulta o commit da `main` oficial,
  mostra o destino e pede confirmação. Baixa esse commit exato, instala em
  outro ambiente Python, valida e troca o launcher. A versão anterior é mantida.

APT exige root, registra saída em `/var/log/biosuite-install/apt.log` e informa
se o sistema sinalizou necessidade de reinicialização. Não executa dist-upgrade,
autoremove nem reboot. Execute a atualização das listas antes de revisar o
upgrade, pois a simulação usa os índices atuais. A resolução final do APT pode
mudar se outro administrador alterar os índices/pacotes após a revisão.

Atualizar o painel não atualiza o Galaxy, seus schemas, ferramentas ou imagens
Docker. Atualizações APT no host também não atualizam pacotes dentro dos
containers. A atualização gerenciada do Galaxy e de suas imagens com migração
verificada ainda não faz parte desta entrega.

A atualização do painel precisa do recibo `biosuite-install.json`, criado pelo
bootstrap desta versão. Para instalações anteriores, reexecute o bootstrap
uma vez. Checkouts de desenvolvimento continuam sendo atualizados pelo Git.
Após concluir, saia e abra `biosuite-config` para carregar a versão nova.
O log fica em `panel-update.log` no prefixo do painel.

```bash
sudo biosuite updates apt-update
biosuite updates apt-plan
sudo biosuite updates apt-upgrade --yes
biosuite updates check-panel
# Use o SHA retornado acima:
biosuite updates panel --commit SHA_COMPLETO --yes
```

Até o merge desta entrega, a `main` pode conter uma versão anterior: confira o
commit exibido antes de aplicar a atualização.

## Endereço gratuito

O cliente está na tela **Conexão**, mas o serviço central adaptado precisa ser
publicado antes: veja [configuração do broker](../broker/README.md). O broker
Koha original `https://broker.koha.nexus` não aceita Galaxy/porta configurável.
O endereço proposto para o novo serviço é `https://biosuite-broker.koha.nexus`.
Ele usa a mesma zona autorizada pelo proprietário, com recursos independentes.

1. Abra o painel como root desde o cadastro (`sudo biosuite-config`).
2. Verifique o broker; informe instituição, contato, nome desejado e a mesma
   porta local escolhida na instalação.
3. Solicite o endereço, consulte a aprovação e conclua o cadastro aprovado.
4. Consulte o estado até ficar `active`, prepare cloudflared e ative o túnel.
5. Exporte o arquivo privado de recuperação e guarde-o fora do servidor.

O broker aplica `bio-`: por exemplo, `laboratorio` recebe
`bio-laboratorio.koha.nexus`, ou uma alternativa se o nome estiver ocupado.
O serviço `biosuite-cloudflared.service` conecta ao Galaxy local. Token de túnel
fica em arquivo 0600 e é entregue ao processo via credenciais systemd, sem
aparecer na linha de comando. O token administrativo Cloudflare não é pedido
no painel. **Desativar** para só o conector local, preservando o endereço.

Identidade/estado ficam em `/etc/biosuite/connection` para root. O modo sem sudo
usa `~/.config/biosuite/connection`; são configurações diferentes. Para mover
um cadastro de usuário para root, exporte a recuperação no usuário e importe
no painel root antes de ativar. Arquivos de recuperação contêm chave privada:
não os publique, não os envie pelo chat nem mantenha em locais compartilhados.

Cadastros pendentes expiram conforme o broker. O botão **Encerrar solicitação
recusada/expirada** consulta o servidor e permite nova solicitação, preservando
a chave local. Respostas perdidas na matrícula e recuperação sem arquivo
exigem intervenção do administrador. Não apague a
identidade para tentar repetir a matrícula. A instalação/configuração do conector
exige systemd. O acesso público e uploads grandes dependem dos limites Cloudflare.

Backups de datasets/banco e rclone continuam pendentes. O arquivo de recuperação
do endereço não substitui um backup do Galaxy.
