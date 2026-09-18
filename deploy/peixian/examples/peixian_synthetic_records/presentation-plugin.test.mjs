import { test, expect } from "bun:test";
import { readFile } from "node:fs/promises";
import plugin from "./presentation-plugin/entry.mjs";
import { compile } from "./presentation-plugin/engine.mjs";
const fixtures=JSON.parse(await readFile(new URL("./presentation-plugin/fixtures.json",import.meta.url),"utf8"));
test("actual trace is ordered, bounded and leaves facts unchanged",async()=>{
 const notices=[];const instance=await plugin({}, {}, {connections:{request:async(_,r)=>({status:200,data:fixtures.records[r.json.module]})}});
 const result=JSON.parse(await instance.tool.peixian_prepare_scenario_facts.execute({scenario_id:"DEMO-CASE-THEFT"},{metadata:x=>notices.push(structuredClone(x))}));
 const {execution_trace,...facts}=result;
 expect(facts).toEqual(compile(fixtures.scenarios["DEMO-CASE-THEFT"],fixtures.records));
 expect(execution_trace.map(x=>x.code)).toEqual(["scope","night","night","portrait","portrait","vehicle","vehicle"]);
 expect(execution_trace.every((x,i)=>i===0||x.at>=execution_trace[i-1].at)).toBe(true);expect(notices.length).toBe(7);
 const f=facts.facts[0];const checked=JSON.parse(await instance.tool.peixian_check_scenario_summary.execute({scenario_id:facts.scenario_id,claims:[{fact_id:f.fact_id,statement:f.statement,source_ids:f.source_ids}]},{}));
 expect(checked.execution_trace.map(x=>x.status)).toEqual(["running","completed"]);
});
test("failed fetch is explicit and cannot appear completed",async()=>{
 const instance=await plugin({}, {}, {connections:{request:async()=>({status:503,data:{}})}});
 const result=JSON.parse(await instance.tool.peixian_prepare_scenario_facts.execute({scenario_id:"DEMO-CASE-THEFT"},{}));
 expect(result.data_status).toBe("partial");expect(result.execution_trace.filter(x=>x.status==="failed").length).toBe(3);
});
