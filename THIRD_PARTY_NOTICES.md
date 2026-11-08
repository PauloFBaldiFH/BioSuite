# Código de terceiros

O diretório `broker/` incorpora código do [Koha Nexus](https://github.com/PauloFBaldiFH/koha.nexus),
commit `d76218203b79c2a9fecfac923444c356fe175cd6`, publicado sob GNU GPL versão 3.
Os avisos originais foram preservados. Consulte [LICENSE](LICENSE) para a licença
GPLv3 distribuída com este projeto. As adaptações BioSuite incluem perfil Galaxy,
porta de origem configurável, recuperação JSON, namespace próprio e testes de
integração com o cliente Python.

O protocolo mantém o identificador `KEI-SIG-v1` e os cabeçalhos `X-KEI-*` para
compatibilidade criptográfica. Isso não autoriza reutilizar o banco, Worker,
identificadores ou credenciais do Koha na implantação BioSuite.

Galaxy, PostgreSQL, Docker e cloudflared são obtidos de suas fontes oficiais;
continuam sujeitos às respectivas licenças. Não são ferramentas científicas
embutidas no pacote Python do painel.
