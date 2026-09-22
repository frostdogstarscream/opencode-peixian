import { test, expect } from "bun:test"
import { controlledAnswer } from "../src/trusted-v2"
import type { TrustedResult } from "../src/trusted-v2"
const claim = {agent_id:"theft-assistant",claim_id:"c1",type:"fact" as const,statement:"原事实",source_ids:["r1"],verification_status:"approved" as const,protected_fields:{},source_run_id:"run1"}
const result:TrustedResult = {schema:"peixian.analysis-result",version:"2.0",run_id:"run1",claims:[claim],answer:{version:"controlled-zh-v1",status:"ready",summary:"资料已整理",items:[{text:"中文事实",claim_id:"c1",source_run_id:"run1",source_ids:["r1"]}],missing:[],next_steps:["展开来源"]}}
test("known answer and source references",()=>expect(controlledAnswer(result)?.items[0].text).toBe("中文事实"))
test("unknown version keeps evidence fallback",()=>expect(controlledAnswer({...result,answer:{...result.answer!,version:"future"}})).toBeUndefined())
test("foreign or forged sources rejected",()=>{
  for (const delta of [{claim_id:"forged"},{source_run_id:"other"},{source_ids:["fake"]}]) {
    expect(controlledAnswer({...result,answer:{...result.answer!,items:[{...result.answer!.items[0],...delta}]}})).toBeUndefined()
  }
})
test("legacy results have no controlled answer",()=>expect(controlledAnswer({...result,answer:undefined})).toBeUndefined())
