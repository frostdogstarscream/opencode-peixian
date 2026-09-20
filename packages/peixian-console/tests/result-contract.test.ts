import { expect, test } from "bun:test"
import { acceptedRun, isAnalysisResult, legacyPresentation } from "../src/result-contract"
const legacy = {
  version: "1.0", process: [{ id: "night", title: "查询夜间记录", status: "completed", time: "—" }],
  conclusions: [{ text: "取得两条记录", clue_id: "finding-night", source_ids: ["DEMO-1", "DEMO-2"] }],
  evidence: [{ type: "trajectory", title: "夜间记录", value: 2, clue_id: "finding-night" }],
  clues: [{ id: "finding-night", type: "trajectory", title: "夜间记录", headline: "两条", summary: "两条", discoveries: [], evidence: [{ type: "trajectory", label: "DEMO-1", content: "时间未提供" }] }],
  missing: ["地点无距离测量依据。"],
}
test("accepted response uses run_id and fixed message identity, without fabricated time", () => {
 const run = acceptedRun({ accepted: true, run_id: "run-2", message_id: "message-2" }, "session-1")
 expect(run.id).toBe("run-2"); expect(run.user_message_id).toBe("message-2"); expect(run.session_id).toBe("session-1")
 expect(run.status).toBe("queued"); expect(run.created_at).toBe("")
})
test("malformed or unknown acceptance cannot create a run", () => {
 for (const response of [{ id: "run-1" }, { accepted: false }, { accepted: true, run_id: "", message_id: "m" }]) expect(() => acceptedRun(response, "s")).toThrow()
})
test("legacy evidence preserves sources, gaps, clocks and immutable input", () => {
 const before = JSON.stringify(legacy)
 const value = legacyPresentation(legacy)!
 expect(isAnalysisResult(value)).toBe(true)
 expect(value.conclusions).toEqual(["取得两条记录"])
 expect(value.conclusion_sources).toEqual(legacy.conclusions)
 expect(value.missing).toEqual(legacy.missing)
 expect(value.process[0].time).toBe("—")
 expect(value.subjects).toEqual([])
 expect(JSON.stringify(legacy)).toBe(before)
})
test("legacy data cannot pass the message-result validator", () => {
 expect(isAnalysisResult(legacy)).toBe(false)
 expect(isAnalysisResult(JSON.stringify(legacy))).toBe(false)
})
test("unknown versions and malformed nested data fail closed", () => {
 for (const value of [{ ...legacy, version: "2.0" }, { ...legacy, schema: "other" }, { ...legacy, conclusions: ["free text"] }, { ...legacy, clues: [{ id: "bad" }] }, { ...legacy, missing: [42] }]) expect(legacyPresentation(value)).toBeUndefined()
 expect(isAnalysisResult({ schema: "peixian.analysis-result", version: "1.0", process: [], clues: [] })).toBe(false)
})
