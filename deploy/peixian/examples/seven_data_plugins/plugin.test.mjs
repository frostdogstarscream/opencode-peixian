import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
for (const module of ['funds','calls','portrait','composite','night','vehicle','lookup']) {
 test(module+' uses only its fixed module and health path',async()=>{
  const entry=await import('./'+module+'/entry.mjs');
  const manifest=JSON.parse(await readFile(new URL('./'+module+'/manifest.json',import.meta.url),'utf8'));
  const requests=[];
  const platform={connections:{request:async(alias,input)=>{requests.push({alias,input});return {status:200,data:input.path==='/health'?{ok:true,synthetic:true}:{module,synthetic:true,data_status:'complete',records:[{record_id:'DEMO-1'}],returned_count:1,total_count:1,has_more:false,snapshot_id:'DEMO-SNAPSHOT',rule_version:'demo-v1'}};}}};
  const plugin=await entry.default({}, {},platform);const name='peixian_get_'+module+'_records';
  assert.deepEqual(Object.keys(plugin.tool),[name]);assert.deepEqual(manifest.tools,[name]);
  const result=JSON.parse(await plugin.tool[name].execute({}));assert.equal(result.items[0].record_id,'DEMO-1');
  assert.deepEqual(requests[0],{alias:'records',input:{method:'POST',path:'/v1/demo/records/query',json:{module}}});
  await assert.rejects(plugin.tool[name].execute({module:'other'}));assert.equal(requests.length,1);
  assert.equal((await entry.test({},platform)).ok,true);assert.deepEqual(requests[1].input,{method:'GET',path:'/health'});
 });
 test(module+' rejects mismatched response',async()=>{
  const entry=await import('./'+module+'/entry.mjs');const plugin=await entry.default({}, {},{connections:{request:async()=>({status:200,data:{module:'wrong',synthetic:true}})}});
  await assert.rejects(plugin.tool['peixian_get_'+module+'_records'].execute({}));
 });
}
