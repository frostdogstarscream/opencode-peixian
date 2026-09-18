import legacy, { test } from './legacy.mjs';
import { readFile } from 'node:fs/promises';
import { compile, canonical, checkClaims } from './engine.mjs';
export { test };
const data=JSON.parse(await readFile(new URL('./fixtures.json',import.meta.url),'utf8'));
const scenario={type:'string',enum:Object.keys(data.scenarios)};
export default async function plugin(context,options,platform){
 const result=await legacy(context,options,platform);
 async function prepare(id){
  if(!Object.hasOwn(data.scenarios,id))throw new Error('请选择固定合成场景。');
  const responses={};
  for(const module of data.scenarios[id].required_modules){
   try {
    const response=await platform.connections.request('peixian_records',{method:'POST',path:'/v1/demo/records/query',json:{module}});
    if(response.status!==200||canonical(response.data)!==canonical(data.records[module]))continue;
    responses[module]=response.data;
   } catch { /* No retries or upstream error details in model output. */ }
  }
  return compile(data.scenarios[id],responses);
 }
 result.tool.peixian_prepare_scenario_facts={description:'代码固定取数、按字段筛选对象、统计时间和数量、核对独行来源，返回已整理事实表。场景 Skill 必须优先调用，不自行汇总混合资料。',args:{scenario_id:scenario},async execute(args){
  if(Object.keys(args).join(',')!=='scenario_id')throw new Error('invalid_arguments');
  return JSON.stringify(await prepare(args.scenario_id));
 }};
 result.tool.peixian_check_scenario_summary={description:'核对所选事实表原句与精确来源；引用存在但不支持表述仍拒绝。只把 approved 原句作为已核对摘要。',args:{scenario_id:scenario,claims:{type:'array',maxItems:40,items:{type:'object',additionalProperties:false,required:['fact_id','statement','source_ids'],properties:{fact_id:{type:'string'},statement:{type:'string',maxLength:2000},source_ids:{type:'array',maxItems:50,items:{type:'string'}}}}}},async execute(args){
  if(Object.keys(args).sort().join(',')!=='claims,scenario_id')throw new Error('invalid_arguments');
  return JSON.stringify(checkClaims(await prepare(args.scenario_id),args.claims));
 }};
 return result;
}
