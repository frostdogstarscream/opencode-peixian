import { expect, test } from "bun:test"
import { parseLive, type AnswerSegmentNotice } from "../src/events"
import { applyLive, deltaBehind, fromPage, needsBackfill, withLive } from "../src/live-answer"
import type { Message } from "../src/types"

const base = { type: "answer.segment" as const, session_id: "s1", run_id: "r1", final: false }
const segment = (sequence: number, extra: Partial<AnswerSegmentNotice>): AnswerSegmentNotice => ({ ...base, part_id: `part_delivery_r1_${sequence}`, sequence, display_kind: "source_answer", text: `来源${sequence}`, ...extra })

test("only versioned live notices with safe identifiers are accepted", () => {
  const ok = parseLive({ event: "change", data: JSON.stringify({ ...segment(1, {}), version: "live-push-v1" }) })
  expect(ok?.type).toBe("answer.segment")
  expect(parseLive({ event: "change", data: JSON.stringify({ ...segment(1, {}) }) })).toBeUndefined()
  expect(parseLive({ event: "change", data: JSON.stringify({ ...segment(1, {}), version: "live-push-v1", run_id: "../x" }) })).toBeUndefined()
  expect(parseLive({ event: "change", data: JSON.stringify({ type: "updated", resources: ["messages"] }) })).toBeUndefined()
  const progress = parseLive({ event: "change", data: JSON.stringify({ type: "run.progress", version: "live-push-v1", session_id: "s1", run_id: "r1", phase: "thinking", label: "正在分析问题" }) })
  expect(progress).toEqual({ type: "run.progress", session_id: "s1", run_id: "r1", phase: "thinking", label: "正在分析问题" })
})

test("final sections render as one part and yield to the persisted message", () => {
  let state = applyLive(undefined, segment(1, { message_id: "msg_delivery" }))
  for (const [index, text] of ["## 结论\n\n", "### 甲\n\n", "### 乙\n"].entries()) {
    state = applyLive(state, segment(2 + index, { part_id: "part_answer_r1", display_kind: "final_answer", message_id: "msg_a", index, count: 3, text }))
  }
  const user: Message = { info: { id: "msg_u", role: "user" }, parts: [{ type: "text", text: "问题" }] }
  const shown = withLive([user], state, "msg_u")
  expect(shown.map((item) => item.info.id)).toEqual(["msg_u", "msg_delivery", "msg_a"])
  expect(shown[2].parts[0].text).toBe("## 结论\n\n### 甲\n\n### 乙\n")
  expect(shown[2].info.parentID).toBe("msg_u")
  const persisted: Message = { info: { id: "msg_a", role: "assistant", run_id: "r1" }, parts: [{ id: "part_answer_r1", type: "text", text: "## 结论\n\n### 甲\n\n### 乙\n" }] }
  const replaced = withLive([user, persisted], state, "msg_u")
  expect(replaced.find((item) => item.info.id === "msg_a")?.parts.length).toBe(1)
})

test("a missing middle section stops the joined text instead of splicing", () => {
  let state = applyLive(undefined, segment(1, { part_id: "part_answer_r1", display_kind: "final_answer", message_id: "msg_a", index: 0, text: "A" }))
  state = applyLive(state, segment(3, { part_id: "part_answer_r1", display_kind: "final_answer", message_id: "msg_a", index: 2, text: "C" }))
  expect(withLive([], state)[0].parts[0].text).toBe("A")
  expect(needsBackfill(state, segment(3, { index: 2 }))).toBe(true)
  const filled = fromPage(state, { items: [{ sequence: 2, part_id: "part_answer_r1", display_kind: "final_answer", text: "B", index: 1 }] }, "msg_a")
  expect(withLive([], filled)[0].parts[0].text).toBe("ABC")
})

const delta = (offset: number, text: string) => ({ type: "answer.delta" as const, session_id: "s1", run_id: "r1", message_id: "msg_a", part_id: "prt_1", offset, text })

test("answer deltas are parsed only with a valid offset and text", () => {
  const raw = (extra: object) => parseLive({ event: "change", data: JSON.stringify({ ...delta(0, "正在查询"), version: "live-push-v1", ...extra }) })
  expect(raw({})).toEqual(delta(0, "正在查询"))
  expect(raw({ offset: -1 })).toBeUndefined()
  expect(raw({ offset: 1.5 })).toBeUndefined()
  expect(raw({ text: "" })).toBeUndefined()
  expect(raw({ message_id: "../x" })).toBeUndefined()
})

test("deltas append at their offset, continue /messages text and report gaps", () => {
  let state = applyLive(undefined, delta(0, "正在查询"))
  state = applyLive(state, delta(4, "近7天轨迹。"))
  expect(state.drafts?.prt_1.text).toBe("正在查询近7天轨迹。")
  const gap = delta(20, "后文")
  expect(applyLive(state, gap)).toBe(state)
  expect(deltaBehind(state, gap)).toBe(true)
  expect(deltaBehind(state, gap, "x".repeat(22))).toBe(false)
  const joined = applyLive(undefined, delta(2, "查询"), () => "正在")
  expect(joined.drafts?.prt_1.text).toBe("正在查询")
})

test("drafts render until /messages catches up or the platform answer arrives", () => {
  let state = applyLive(undefined, delta(0, "正在查询近7天轨迹。"))
  const user: Message = { info: { id: "msg_u", role: "user" }, parts: [{ type: "text", text: "问题" }] }
  const shown = withLive([user], state, "msg_u")
  expect(shown[1].info).toMatchObject({ id: "msg_a", parentID: "msg_u", run_id: "r1" })
  expect(shown[1].parts[0].text).toBe("正在查询近7天轨迹。")
  const behind: Message = { info: { id: "msg_a", role: "assistant", run_id: "r1" }, parts: [{ id: "prt_1", type: "text", text: "正在查询" }, { id: "t1", type: "tool" }] }
  expect(withLive([user, behind], state)[1].parts.map((part) => part.text)).toEqual(["正在查询近7天轨迹。", undefined])
  const ahead: Message = { ...behind, parts: [{ id: "prt_1", type: "text", text: "正在查询近7天轨迹。然后" }] }
  expect(withLive([user, ahead], state)[1].parts[0].text).toBe("正在查询近7天轨迹。然后")
  const answered: Message = { info: { id: "msg_a", role: "assistant", run_id: "r1" }, parts: [{ id: "part_answer_r1", type: "text", text: "### 表格", display_kind: "final_answer", run_id: "r1" }] }
  expect(withLive([user, answered], state)).toEqual([user, answered])
  state = applyLive(state, segment(1, { part_id: "part_answer_r1", display_kind: "final_answer", message_id: "msg_a", index: 0, text: "### 表格" }))
  expect(state.drafts).toBeUndefined()
})

test("oversized notices without text request a backfill and never overwrite text", () => {
  const state = applyLive(undefined, segment(1, {}))
  expect(needsBackfill(state, segment(1, { text: undefined, truncated: true }))).toBe(true)
  expect(applyLive(state, segment(1, { text: undefined, truncated: true })).segments[0].text).toBe("来源1")
  expect(needsBackfill({ ...state, segments: [] }, segment(1, {}))).toBe(false)
})
