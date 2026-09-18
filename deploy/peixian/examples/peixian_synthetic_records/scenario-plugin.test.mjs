import { test, expect } from "bun:test";
import plugin from "./scenario-plugin/entry.mjs";
test("fixed scenarios are local, bounded and preserve seven tools", async () => {
 const runtime=await plugin({}, {}, {connections:{request:()=>{throw Error("unexpected network")}}});
 expect(Object.keys(runtime.tool)).toHaveLength(8);
 for(const scenario_id of ["DEMO-CASE-GAMBLING","DEMO-CASE-THEFT"]) {
  const result=JSON.parse(await runtime.tool.peixian_get_scenario_context.execute({scenario_id}));
  expect(result.synthetic).toBe(true);expect(result.scenario_id).toBe(scenario_id);
 }
 for(const args of [{}, {scenario_id:"real-case"},{scenario_id:"DEMO-CASE-THEFT",url:"http://x"}])
  await expect(runtime.tool.peixian_get_scenario_context.execute(args)).rejects.toThrow();
});

test("plugin context exactly matches server-reviewed fixture and original record tools remain fixed", async () => {
 const data=await Bun.file(new URL("../../../../services/peixian-control/control/scenario_data.json",import.meta.url)).json();
 const calls=[];
 const runtime=await plugin({}, {}, {connections:{request:async(alias,request)=>{calls.push({alias,request});return {status:200,data:data.records[request.json.module]}}}});
 for(const scenario_id of Object.keys(data.scenarios)) expect(JSON.parse(await runtime.tool.peixian_get_scenario_context.execute({scenario_id}))).toEqual(data.scenarios[scenario_id]);
 for(const module of Object.keys(data.records)) {
   const result=JSON.parse(await runtime.tool["peixian_get_"+module+"_records"].execute({}));
   expect(result.items).toEqual(data.records[module].records);
   expect(calls.at(-1)).toEqual({alias:"peixian_records",request:{method:"POST",path:"/v1/demo/records/query",json:{module}}});
 }
});
