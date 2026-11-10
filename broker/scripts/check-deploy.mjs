import {fileURLToPath} from 'node:url';
import {unstable_readConfig} from 'wrangler';
import {deploymentErrors} from './deployment-config.mjs';
try {
  const config = unstable_readConfig({config:fileURLToPath(new URL('../wrangler.toml', import.meta.url))}, {hideWarnings:true});
  const errors = deploymentErrors(config);
  if (errors.length) {
    console.error('Publicação bloqueada pela configuração local:');
    for (const error of errors) console.error('- ' + error);
    console.error('Veja broker/README.md. Não informe tokens neste arquivo.');
    process.exitCode = 1;
  } else {
    console.log('Configuração local aprovada. Autenticação, propriedade dos IDs e recursos na conta ainda não foram verificados.');
  }
} catch {
  console.error('Não foi possível validar wrangler.toml. Confira a sintaxe com Wrangler; nenhum recurso foi publicado.');
  process.exitCode = 1;
}
