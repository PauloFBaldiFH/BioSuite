// Local Worker/D1/Queue/DO and real BioSuite Python client; Cloudflare API is fake.
import assert from 'node:assert/strict';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {mkdtempSync,writeFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {startBroker,BROKER_DIR,ADMIN_TOKEN} from './harness.mjs';

const execute=promisify(execFile);
const temp=mkdtempSync(join(tmpdir(),'biosuite-galaxy-broker-'));
const broker=await startBroker({vars:{APPLICATION:'galaxy',NAME_PREFIX:'bio-'}});
let checks=0;
async function python(action,args=[],profile='client'){
  const script=`import json,sys\nfrom pathlib import Path\nfrom biosuite.connection import BrokerClient\nc=BrokerClient(sys.argv[1],Path(sys.argv[2]))\na=sys.argv[3]\nargs=json.loads(sys.argv[4])\nif a in ('export_recovery','import_recovery'): args=[Path(args[0])]\nprint(json.dumps(getattr(c,a)(*args)))`;
  const result=await execute('python3',['-c',script,broker.url,join(temp,profile),action,JSON.stringify(args)],{
    env:{...process.env,PYTHONPATH:resolve(BROKER_DIR,'../src')},timeout:30000});
  return JSON.parse(result.stdout);
}
async function admin(path){
  const r=await fetch(broker.url+path,{method:'POST',headers:{Authorization:`Bearer ${ADMIN_TOKEN}`}});
  assert.equal(r.status,200);return r;
}
try{
  const caps=await python('capabilities');assert.equal(caps.application,'galaxy');checks++;
  const conflict=await python('start',['BioSuite lab','lab@example.org','laboratorio-admin',8087],'staff-conflict');
  assert.equal(conflict.status,'approved');
  assert.ok(!conflict.hostnames.galaxy.endsWith('-admin.example.org'));checks++;
  const start=await python('start',['BioSuite lab','lab@example.org','laboratorio',8087]);
  assert.equal(start.status,'approved');assert.ok(!JSON.stringify(start).includes('device_code'));checks++;
  await python('enroll');assert.ok(await broker.settle());
  const state=await python('poll');assert.equal(state.status,'active');assert.equal(state.hostnames.galaxy,'bio-laboratorio.example.org');checks++;
  const snapshot=broker.fake.snapshot();
  assert.equal(snapshot.tunnels.length,1);assert.ok(snapshot.tunnels[0].name.startsWith('biosuite-instance-'));
  assert.deepEqual(snapshot.tunnels[0].ingress,[{hostname:'bio-laboratorio.example.org',service:'http://127.0.0.1:8087'},{service:'http_status:404'}]);
  assert.equal(snapshot.dns_records.length,1);assert.ok(snapshot.dns_records[0].comment.startsWith('biosuite:instance:'));checks++;
  await admin(`/admin/libraries/${state.library_id}/suspend`);
  assert.deepEqual(broker.fake.snapshot().tunnels[0].ingress,[{service:'http_status:503'}]);
  await admin(`/admin/libraries/${state.library_id}/restore`);
  assert.equal(broker.fake.snapshot().tunnels[0].ingress[0].service,'http://127.0.0.1:8087');checks++;
  const recovery=join(temp,'recovery.json');await python('export_recovery',[recovery]);
  const restored=await python('import_recovery',[recovery],'restored');assert.equal(restored.library_id,state.library_id);checks++;
  const regenerated=await (await admin(`/admin/libraries/${state.library_id}/recovery-file`)).json();
  const adminFile=join(temp,'admin-recovery.json');writeFileSync(adminFile,JSON.stringify(regenerated),{mode:0o600});
  const recovered=await python('import_recovery',[adminFile],'admin-restored');assert.equal(recovered.library_id,state.library_id);checks++;
  await assert.rejects(()=>python('poll'));checks++;
  broker.fake.state.tunnels.push({id:'nexus-existing',name:'kei-lib-existing',created_at:'2020-01-01T00:00:00Z',deleted_at:null,ingress:null});
  broker.fake.state.tunnels.push({id:'own-orphan',name:'biosuite-instance-orphan',created_at:'2020-01-01T00:00:00Z',deleted_at:null,ingress:null});
  broker.fake.state.dns_records.push({id:'nexus-record',type:'CNAME',name:'old.example.org',content:'nexus-existing.cfargotunnel.com',proxied:true,comment:'kei:lib:existing'});
  const worker=await broker.mf.getWorker();
  await worker.scheduled({cron:'0 * * * *'});
  const deadline=Date.now()+5000;
  while(broker.fake.snapshot().tunnels.some(t=>t.id==='own-orphan')&&Date.now()<deadline)
    await new Promise(ok=>setTimeout(ok,100));
  assert.ok(!broker.fake.snapshot().tunnels.some(t=>t.id==='own-orphan'));
  assert.ok(broker.fake.snapshot().dns_records.some(r=>r.id==='nexus-record'));
  assert.ok(broker.fake.snapshot().tunnels.some(t=>t.name==='kei-lib-existing'));checks++;
  console.log(`Galaxy broker e2e: ${checks} checks passed; no external publication.`);
}finally{await broker.close();rmSync(temp,{recursive:true,force:true});}
