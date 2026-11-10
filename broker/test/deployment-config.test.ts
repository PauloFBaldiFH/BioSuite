import {describe, expect, it} from 'vitest';
import {deploymentErrors} from '../scripts/deployment-config.mjs';
function valid() {
  return {
    name:'biosuite-broker', account_id:'a'.repeat(32),
    vars:{APPLICATION:'galaxy', NAME_PREFIX:'bio-', STAFF_SUFFIX:'-admin', CF_ACCOUNT_ID:'a'.repeat(32), CF_ZONE_ID:'b'.repeat(32),
      ZONE_NAME:'koha.nexus', BROKER_HOST:'biosuite-broker.koha.nexus', AUTO_APPROVE:'false'},
    routes:[{pattern:'biosuite-broker.koha.nexus', custom_domain:true}],
    d1_databases:[{binding:'DB',database_name:'biosuite-broker',database_id:'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'}],
    queues:{producers:[{binding:'PROVISION_QUEUE',queue:'biosuite-provision'}],
      consumers:[{queue:'biosuite-provision',dead_letter_queue:'biosuite-provision-dlq'}]}
  };
}
describe('deployment isolation checks',()=>{
  it('accepts an explicitly configured separate Galaxy deployment',()=>{
    expect(deploymentErrors(valid())).toEqual([]);
  });
  it('preserves the staff suffix reserved by the existing Koha route',()=>{
    const c=valid(); c.vars.STAFF_SUFFIX='';
    expect(deploymentErrors(c).join('\n')).toMatch(/rota existente/);
  });
  it('rejects placeholder IDs and a different deployment account',()=>{
    const c=valid(); c.vars.CF_ZONE_ID='REPLACE_WITH_ZONE_ID'; c.account_id='c'.repeat(32);
    expect(deploymentErrors(c).join('\n')).toMatch(/CF_ZONE_ID/);
    expect(deploymentErrors(c).join('\n')).toMatch(/account_id/);
  });
  it('rejects the existing Koha endpoint and wildcard routes',()=>{
    const c=valid(); c.vars.BROKER_HOST='broker.koha.nexus'; c.routes[0]!.pattern='*.koha.nexus/*';
    expect(deploymentErrors(c).join('\n')).toMatch(/domínio novo/);
    expect(deploymentErrors(c).join('\n')).toMatch(/curinga/);
  });
  it('rejects reuse of Nexus worker, database, queues or public namespace',()=>{
    const c=valid(); c.name='kei-broker'; c.vars.NAME_PREFIX=''; c.d1_databases[0]!.database_name='kei-broker'; c.queues.producers[0]!.queue='kei-provision';
    expect(deploymentErrors(c)).toHaveLength(4);
  });
});
