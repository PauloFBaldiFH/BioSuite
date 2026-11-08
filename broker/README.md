# Broker BioSuite para koha.nexus

Adaptação do broker GPLv3 do Koha Nexus. Distribui `bio-<nome>.koha.nexus`
para instâncias Galaxy, com porta local configurável (padrão 8080), cadastro
Ed25519, DNS e Cloudflare Tunnel. A API administrativa Cloudflare fica apenas
no Worker. O painel recebe uma credencial limitada ao túnel da instalação.
Veja [proveniência e licença](../THIRD_PARTY_NOTICES.md).

## Implantação separada do Koha

**Não publique este código no Worker `broker.koha.nexus` existente e não aponte
para seu banco D1.** Use um Worker novo, `biosuite-broker`, em
`biosuite-broker.koha.nexus`, na mesma conta da zona `koha.nexus`.
A configuração proposta já separa os recursos:

| Recurso | BioSuite |
| --- | --- |
| Aplicação | `APPLICATION="galaxy"` |
| Domínio do serviço | `biosuite-broker.koha.nexus` |
| Endereços emitidos | `bio-<nome>.koha.nexus` |
| D1 | `biosuite-broker`, novo ID |
| Filas | `biosuite-provision`, `biosuite-provision-dlq` |
| Nome dos túneis | `biosuite-instance-<id>` |
| Comentário DNS de propriedade | `biosuite:instance:<id>` |
| Durable Objects | vinculados ao Worker novo |
| Rate limiters | 9301, 9302, 9303; verificar disponibilidade na conta |

A reconciliação remove apenas órfãos com o prefixo BioSuite. Há um teste que
cria um órfão BioSuite e recursos Koha, executa o cron e verifica que somente
o órfão BioSuite é removido. Não compartilhe esses prefixos com outro broker.
Um nome ocupado é ajustado pelo servidor. Apenas Galaxy é publicado neste perfil;
as rotas de ativação de serviços Koha/Tainacan/DSpace não ficam disponíveis.

## Configurar e publicar

Os comandos abaixo alteram a conta Cloudflare quando executados pelo operador.
Este repositório não contém IDs reais nem segredos e não publica automaticamente.
Node.js 22+, npm, Python 3.10+ e OpenSSL são usados pelos testes.

1. Entre na conta que contém a zona `koha.nexus` e crie recursos novos:

```bash
cd broker
npm ci
npx wrangler login
npx wrangler d1 create biosuite-broker
npx wrangler queues create biosuite-provision
npx wrangler queues create biosuite-provision-dlq
```

2. Em `wrangler.toml`, preencha `CF_ACCOUNT_ID`, `CF_ZONE_ID` e `database_id`
com os IDs da conta/zona e do **novo** D1. Confirme os nomes das filas e
namespaces dos rate limiters. Substitua `routes = []` por:

```toml
routes = [{ pattern = "biosuite-broker.koha.nexus", custom_domain = true }]
```

Mantenha `AUTO_APPROVE="false"` durante a configuração. Não adicione uma rota
curinga no domínio do Koha. `workers_dev=true` permite acesso ao endpoint de
implantação; o painel deve usar o domínio HTTPS configurado acima.

3. Valide, aplique todas as migrações **no D1 novo** e publique:

```bash
npm run typecheck
npm test
npm run test:e2e
npm run db:migrate
npm run deploy
```

As migrações 0001–0004 preservam o modelo herdado; 0005 acrescenta a porta
Galaxy. Não execute migrações BioSuite no D1 do Nexus.

4. Configure segredos no prompt seguro do Wrangler:

```bash
npx wrangler secret put CF_API_TOKEN
npx wrangler secret put ADMIN_TOKEN
npx wrangler secret put STAFF_SESSION_KEY
```

Crie um token Cloudflare próprio, limitado a **Account → Cloudflare Tunnel →
Edit**, na conta correta, e **Zone → DNS → Edit**, somente na zona `koha.nexus`.
O login do Wrangler é separado desse token. Gere valores aleatórios fortes e
diferentes para os outros dois segredos e guarde `ADMIN_TOKEN` em um gerenciador
de senhas. `STAFF_SESSION_KEY` é um requisito herdado, mesmo sem staff gate no
perfil Galaxy. Não cole nenhum desses valores no chat, em arquivos versionados
ou argumentos de comandos. Segredos do Worker existente não podem ser lidos de
volta: um token novo evita depender dessa recuperação.

5. Consulte `https://biosuite-broker.koha.nexus/v1/capabilities`: deve retornar
`application: "galaxy"`, `services: ["galaxy"]` e
`origin_port_configurable: true`. Faça um cadastro de teste pelo painel, aprove-o
pela API administrativa e verifique DNS, túnel, porta, suspensão e recuperação.
Depois, se quiser distribuição imediata, configure `AUTO_APPROVE="true"` e
publique novamente. Defina `MAX_LIBRARIES_PER_DAY` conforme a capacidade da
conta; `0` desativa essa cota adicional, sem retirar os rate limiters.

## Operação administrativa

As rotas abaixo exigem o cabeçalho `Authorization: Bearer ADMIN_TOKEN`.
Forneça-o por ferramenta local segura; não o exponha em histórico ou prints.

| Método e rota | Operação |
| --- | --- |
| `GET /admin/enrollments?status=pending` | Solicitações aguardando aprovação |
| `POST /admin/enrollments/{USER-CODE}/approve` | Aprovar; corpo JSON `{}` ou `{ "slug": "nome" }` |
| `POST /admin/enrollments/{USER-CODE}/deny` | Recusar |
| `GET /admin/libraries` | Instâncias e estado |
| `POST /admin/libraries/{id}/suspend` | Responder 503 no túnel, mantendo endereço |
| `POST /admin/libraries/{id}/restore` | Restaurar, preservando porta registrada |
| `POST /admin/libraries/{id}/recovery-file` | Gerar JSON privado e invalidar imediatamente a chave antiga |
| `DELETE /admin/libraries/{id}` | Remover recursos e reter nome conforme política do broker |

A recuperação administrativa exige verificar a identidade do contato antes de
entregar o arquivo, por um canal privado. O painel também exporta a identidade
local. Não restaure duas máquinas simultaneamente com a mesma identidade/túnel.
Uma resposta perdida em `/v1/enroll` exige recuperação administrativa; o cliente
não repete automaticamente uma matrícula que pode ter sido consumida.

## Limites e validação

“Grátis” significa sem cobrança do endereço pelo projeto ao usuário final.
A conta, o domínio, as cotas de Workers/D1/Queues/Durable Objects e o tráfego
continuam sob responsabilidade do operador. Confirme as condições atuais do
plano Cloudflare; não há garantia de disponibilidade ou de ausência de custos.
Uploads Galaxy grandes podem exceder o limite do proxy: planeje transferência
alternativa. A autenticação e as permissões do Galaxy continuam necessárias.

`npm test` cobre assinaturas, nomes, permissões e passos de provisionamento.
`npm run test:e2e` executa Worker, D1, filas e Durable Objects locais, inclusive
cliente Python real, porta personalizada, recuperação e isolamento do Koha.
A API Cloudflare nesses testes é simulada. A publicação real, DNS público e
conector systemd em uma conta Cloudflare ainda precisam ser verificados pelo
operador após configurar os recursos acima.
