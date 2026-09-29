import {test} from 'node:test';
import assert from 'node:assert/strict';
import {remoteTool} from './agent-client.mjs';
const context={sessionID:'s',messageID:'m',callID:'c'};
const failure=(code,message)=>({detail:{version:'tool-failure-v1',code,message,stage:'precheck',dispatch_status:'not_dispatched',field_errors:{},recovery_action:'stop'}});
test('public precheck rejections reach the model; unknown errors stay opaque',async()=>{
 const original=globalThis.fetch;
 try {
  globalThis.fetch=async()=>new Response(JSON.stringify(failure('scope_missing','请补充范围。')),{status:409});
  await assert.rejects(()=>remoteTool('token','tool',{}).execute({},context),e=>JSON.parse(e.message).dispatch_status==='not_dispatched');
  globalThis.fetch=async()=>new Response(JSON.stringify(failure('person_case_tracks_first','请先查询该人员轨迹；警情按轨迹停留点自动比对，不向用户追问经纬度。')),{status:409});
  await assert.rejects(()=>remoteTool('token','tool',{}).execute({},context),e=>{const d=JSON.parse(e.message);return d.code==='person_case_tracks_first'&&d.message.includes('轨迹');});
  globalThis.fetch=async()=>new Response(JSON.stringify({detail:{code:'private',message:'secret'}}),{status:500});
  await assert.rejects(()=>remoteTool('token','tool',{}).execute({},context),e=>!e.message.includes('secret')&&JSON.parse(e.message).code==='tool_execution_unavailable');
 } finally {globalThis.fetch=original;}
});
