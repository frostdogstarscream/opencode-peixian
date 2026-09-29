import type { AnswerDeltaNotice, AnswerSegmentNotice, LiveNotice } from "./events"
import type { Message, Part } from "./types"

export type LiveDraft = { messageID: string; text: string }
export type LiveAnswer = { sessionID: string; runID: string; progress?: string; segments: AnswerSegmentNotice[]; drafts?: Record<string, LiveDraft> }

// `known` returns the part text from /messages, so a delta can continue a part joined mid-stream.
export function applyLive(current: LiveAnswer | undefined, notice: LiveNotice, known?: (partID: string) => string | undefined): LiveAnswer {
  const base: LiveAnswer = current && current.runID === notice.run_id && current.sessionID === notice.session_id
    ? current
    : { sessionID: notice.session_id, runID: notice.run_id, segments: [] }
  if (notice.type === "run.progress") return base.progress === notice.label ? base : { ...base, progress: notice.label }
  if (notice.type === "answer.delta") {
    const text = base.drafts?.[notice.part_id]?.text ?? known?.(notice.part_id) ?? ""
    if (text.length !== notice.offset) return base
    return { ...base, drafts: { ...base.drafts, [notice.part_id]: { messageID: notice.message_id, text: text + notice.text } } }
  }
  const drafts = notice.display_kind === "final_answer" ? undefined : base.drafts
  const existing = base.segments.find((item) => item.sequence === notice.sequence)
  if (existing && (existing.text !== undefined || notice.text === undefined)) return drafts === base.drafts ? base : { ...base, drafts }
  const segments = [...base.segments.filter((item) => item.sequence !== notice.sequence), notice].sort((a, b) => a.sequence - b.sequence)
  return { ...base, segments, drafts }
}

// Neither the pushed draft nor /messages reached the end of this delta: some text was missed.
export function deltaBehind(state: LiveAnswer, notice: AnswerDeltaNotice, known?: string) {
  const end = notice.offset + notice.text.length
  return (state.drafts?.[notice.part_id]?.text.length ?? 0) < end && (known?.length ?? 0) < end
}

// A gap or a text-less (oversized) notice means the replayable segment log must be read.
export function needsBackfill(state: LiveAnswer, notice: AnswerSegmentNotice) {
  if (notice.text === undefined) return true
  const before = state.segments.filter((item) => item.sequence < notice.sequence)
  return before.length !== notice.sequence - 1 || before.some((item) => item.text === undefined)
}

type SegmentPage = {
  message_id?: string
  items: { sequence: number; part_id: string; display_kind: string; text: string; index?: number; count?: number }[]
}

export function fromPage(state: LiveAnswer, page: SegmentPage, finalMessageID?: string): LiveAnswer {
  let next = state
  for (const item of page.items) {
    if (item.display_kind !== "source_answer" && item.display_kind !== "final_answer") continue
    const messageID = item.display_kind === "final_answer" ? finalMessageID : page.message_id
    next = applyLive(next, {
      type: "answer.segment",
      session_id: state.sessionID,
      run_id: state.runID,
      ...(messageID ? { message_id: messageID } : {}),
      part_id: item.part_id,
      sequence: item.sequence,
      display_kind: item.display_kind,
      final: false,
      ...(item.index !== undefined ? { index: item.index } : {}),
      ...(item.count !== undefined ? { count: item.count } : {}),
      text: item.text,
    })
  }
  return next
}

// Pushed parts are shown until /messages returns the same part id; final-answer sections
// are only joined while contiguous so a missing section never produces spliced text.
export function withLive(messages: Message[], state: LiveAnswer | undefined, parentID?: string): Message[] {
  if (!state) return messages
  const answered = messages.some((message) => message.parts.some((part) => part.display_kind === "final_answer" && part.run_id === state.runID))
  const drafts = answered ? [] : Object.entries(state.drafts ?? {})
  if (!state.segments.length && !drafts.length) return messages
  const known = new Set(messages.flatMap((message) => message.parts.map((part) => part.id)).filter(Boolean))
  const parts = new Map<string, { messageID: string; part: Part }>()
  const nextSection = new Map<string, number>()
  for (const segment of state.segments) {
    if (known.has(segment.part_id) || segment.text === undefined) continue
    const messageID = segment.message_id ?? `live_${state.runID}_${segment.display_kind}`
    if (segment.display_kind === "source_answer") {
      parts.set(segment.part_id, { messageID, part: { id: segment.part_id, type: "text", text: segment.text, display_kind: "source_answer", run_id: state.runID } })
      continue
    }
    const expected = nextSection.get(segment.part_id) ?? 0
    if (expected < 0 || (segment.index ?? expected) !== expected) {
      nextSection.set(segment.part_id, -1)
      continue
    }
    nextSection.set(segment.part_id, expected + 1)
    const entry = parts.get(segment.part_id)
    if (entry) entry.part = { ...entry.part, text: (entry.part.text ?? "") + segment.text }
    else parts.set(segment.part_id, { messageID, part: { id: segment.part_id, type: "text", text: segment.text, display_kind: "final_answer", run_id: state.runID } })
  }
  const result = [...messages]
  // A draft yields once /messages holds at least as much text for the same part.
  for (const [partID, draft] of drafts) {
    const index = result.findIndex((message) => message.parts.some((part) => part.id === partID))
    if (index < 0) {
      parts.set(partID, { messageID: draft.messageID, part: { id: partID, type: "text", text: draft.text, run_id: state.runID } })
      continue
    }
    const message = result[index]
    if (message.parts.some((part) => part.id === partID && (part.text ?? "").length >= draft.text.length)) continue
    result[index] = { ...message, parts: message.parts.map((part) => part.id === partID ? { ...part, text: draft.text } : part) }
  }
  if (!parts.size) return drafts.length ? result : messages
  for (const { messageID, part } of parts.values()) {
    const index = result.findIndex((message) => message.info.id === messageID)
    if (index >= 0) result[index] = { ...result[index], parts: [...result[index].parts, part] }
    else result.push({ info: { id: messageID, role: "assistant", run_id: state.runID, parentID: parentID ?? null }, parts: [part] })
  }
  return result
}
