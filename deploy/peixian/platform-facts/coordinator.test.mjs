import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createCoordinator } from './coordinator.mjs';
const context={scenario_id:'demo',subject_ref:'DEMO-P',required_modules:['night','funds'],limitations:[],facts:[],snapshot_id:'scenario-1',records_snapshot_id:'records-1',window_start:'2026-09-01T00:00:00+08:00',window_end:'2026-09-03T00:00:00+08:00'};
const identity={uid:'a',run_id:'r1',revision:1};
function fixture(){
 const records=new Map(),calls=[],events=[];let allowed=true;
 const key=id=>JSON.stringify(id);
 const adapter={read:async id=>structuredClone(records.get(key(id))),write:async(id,value)=>{records.set(key(id),structuredClone(value))},authorize:async()=>{if(!allowed)throw new Error('revoked')},invoke:async(id,module)=>{calls.push([id.run_id,module]);return {records:[],snapshot_id:'records-1'}},audit:async(id,event)=>events.push(event),scenarios:{demo:context},validate:(_module,response)=>response.snapshot_id==='records-1'};
 return {adapter,calls,events,revoke:()=>allowed=false};
}
test('selected modules cached durably; check never queries; new run isolated',async()=>{
 const f=fixture();let c=createCoordinator(f.adapter);
 const first=await c.prepare(identity,{scenario_id:'demo',methods:['night']});
 assert.deepEqual(f.calls,[['r1','night']]);assert.equal(first.summary.length,1);
 c=createCoordinator(f.adapter);
 await c.prepare(identity,{scenario_id:'demo',methods:['night']});assert.equal(f.calls.length,1);
 const fact=first.facts[0];const approved=await c.check(identity,{scenario_id:'demo',claims:[{fact_id:fact.fact_id,statement:fact.statement,source_ids:fact.source_ids}]});
 assert.equal(approved.approved.length,1);assert.equal(f.calls.length,1);
 await c.prepare({...identity,run_id:'r2'},{scenario_id:'demo',methods:['night']});assert.equal(f.calls.length,2);
 f.revoke();await assert.rejects(c.check(identity,{scenario_id:'demo',claims:[]}));
});
test('unknown outcome survives restart and is not resent',async()=>{
 const f=fixture();let count=0;f.adapter.invoke=async()=>{count++;throw new Error('lost response')};
 let c=createCoordinator(f.adapter);const result=await c.prepare(identity,{scenario_id:'demo',methods:['funds']});
 assert.equal(result.data_status,'partial');assert.equal(count,1);
 c=createCoordinator(f.adapter);await c.prepare(identity,{scenario_id:'demo',methods:['funds']});assert.equal(count,1);
 assert.equal(f.events.at(-1).status,'unknown');
});
test('invalid method and unauthorized modules never dispatch',async()=>{
 const f=fixture();const c=createCoordinator(f.adapter);
 for(const methods of [['unknown'],[],['night','night'],['vehicles']])await assert.rejects(c.prepare(identity,{scenario_id:'demo',methods}));
 f.revoke();await assert.rejects(c.prepare(identity,{scenario_id:'demo',methods:['night']}));assert.equal(f.calls.length,0);
});
test('concurrent operation refused; cancellation stays unconfirmed',async()=>{
 const f=fixture();let release;f.adapter.invoke=()=>new Promise(resolve=>release=resolve);const c=createCoordinator(f.adapter);const abort=new AbortController();
 const first=c.prepare(identity,{scenario_id:'demo',methods:['night']},abort.signal);
 while(!release)await new Promise(resolve=>setTimeout(resolve,1));
 await assert.rejects(c.prepare(identity,{scenario_id:'demo',methods:['night']}));abort.abort();release({records:[],snapshot_id:'records-1'});await assert.rejects(first);
 const restarted=createCoordinator(f.adapter);const result=await restarted.prepare(identity,{scenario_id:'demo',methods:['night']});assert.equal(result.data_status,'partial');
});
