/** Offline only: no API calls, credentials, or deployment side effects. */
export function deploymentErrors(config) {
  const errors = [], vars = config.vars ?? {};
  const hexId = value => typeof value === 'string' && /^[a-f0-9]{32}$/i.test(value);
  const uuid = value => typeof value === 'string' && /^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/i.test(value);
  if (config.name !== 'biosuite-broker') errors.push('Use o Worker separado biosuite-broker.');
  if (vars.APPLICATION !== 'galaxy') errors.push('APPLICATION deve ser galaxy.');
  if (vars.ZONE_NAME === 'koha.nexus' && vars.STAFF_SUFFIX !== '-admin')
    errors.push('Mantenha STAFF_SUFFIX=-admin: nomes com esse final colidem com a rota existente do Koha.');
  if (vars.NAME_PREFIX !== 'bio-') errors.push('NAME_PREFIX deve ser bio-, separado do Koha.');
  if (!hexId(vars.CF_ACCOUNT_ID) || !hexId(vars.CF_ZONE_ID)) errors.push('Preencha CF_ACCOUNT_ID e CF_ZONE_ID com IDs públicos válidos.');
  if (!hexId(config.account_id) || config.account_id !== vars.CF_ACCOUNT_ID) errors.push('Defina account_id no topo do TOML, igual a CF_ACCOUNT_ID.');
  const zone = vars.ZONE_NAME, host = vars.BROKER_HOST;
  const dns = value => typeof value === 'string' && value.length <= 253 && value.split('.').length >= 2 &&
    value.split('.').every(label => label.length <= 63 && /^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/.test(label));
  if (!dns(zone) || !dns(host) || !host.endsWith('.' + zone) || host === 'broker.koha.nexus')
    errors.push('BROKER_HOST deve ser um domínio novo na zona, separado de broker.koha.nexus.');
  const routes = config.routes ?? [];
  if (config.route || routes.length !== 1 || routes[0]?.custom_domain !== true || routes[0]?.pattern !== host)
    errors.push('Configure exatamente um custom_domain para BROKER_HOST, sem rotas curinga do Koha.');
  const db = config.d1_databases ?? [];
  if (db.length !== 1 || db[0]?.binding !== 'DB' || db[0]?.database_name !== 'biosuite-broker' || !uuid(db[0]?.database_id))
    errors.push('Configure DB com o novo D1 biosuite-broker e seu database_id válido.');
  const queues = config.queues ?? {};
  if (queues.producers?.length !== 1 || queues.producers[0]?.binding !== 'PROVISION_QUEUE' || queues.producers[0]?.queue !== 'biosuite-provision' ||
      queues.consumers?.length !== 1 || queues.consumers[0]?.queue !== 'biosuite-provision' || queues.consumers[0]?.dead_letter_queue !== 'biosuite-provision-dlq')
    errors.push('Use as filas novas biosuite-provision e biosuite-provision-dlq.');
  if (!['true', 'false'].includes(vars.AUTO_APPROVE)) errors.push('AUTO_APPROVE deve ser true ou false.');
  return errors;
}
