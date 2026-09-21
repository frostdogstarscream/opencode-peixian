import { describe, expect, test } from "bun:test"
import { ownedResult, usageLabels, label } from "../src/trusted-v2"
describe("trusted result boundary", () => {
  const pending = {
    schema: "peixian.analysis-result",
    version: "2.0",
    run_id: "r1",
    status: "pending",
    data_environment: "synthetic",
    data_usage: { status: "unknown" },
  }
  test("unknown is never displayed as empty or zero", () => {
    expect(usageLabels.unknown).toContain("可能已发出")
    expect(usageLabels.unknown).toContain("不会自动重试")
    expect(usageLabels.unknown).not.toContain("零")
  })
  test("rejects stale run and unsupported versions", () => {
    expect(ownedResult(pending, "r1")).toBe(true)
    expect(ownedResult(pending, "r2")).toBe(false)
    expect(ownedResult({ ...pending, version: "9" }, "r1")).toBe(false)
  })
  test("rejects mixed data environments", () => {
    expect(ownedResult({ ...pending, data_environment: "production" }, "r1")).toBe(false)
  })
  test("free model structure does not pass as trusted final result", () => {
    expect(ownedResult({ ...pending, status: undefined, claims: [{ type: "inference" }] }, "r1")).toBe(false)
  })
  test("legacy is explicit and has no generated claims", () => {
    expect(ownedResult({ schema: pending.schema, version: "legacy", run_id: "r1", status: "legacy" }, "r1")).toBe(true)
  })
  test("rejects a claim for another Agent",()=>{
    const final={...pending,status:undefined,agent:{id:"theft-assistant"},claims:[{type:"fact",agent_id:"gambling-assistant",verification_status:"approved",statement:"test",source_ids:[]}],records:[],missing:[],narrative:{status:"not_generated"}}
    expect(ownedResult(final,"r1")).toBe(false)
  })
  test("unknown values are not coerced to zero", () => {
    expect(label(null)).toBe("未提供")
    expect(label(0)).toBe("0")
  })
})
