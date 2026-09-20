import type { AnalysisResult, Run } from "./types"

function object(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value)
}
function strings(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(item => typeof item === "string")
}
function displayArrays(value: Record<string, unknown>) {
  return Array.isArray(value.process) && value.process.every(item => object(item) && typeof item.id === "string" && typeof item.title === "string" && ["pending", "running", "completed", "failed"].includes(String(item.status)))
    && Array.isArray(value.evidence) && value.evidence.every(item => object(item) && typeof item.type === "string" && typeof item.title === "string" && (item.items === undefined || strings(item.items)))
    && Array.isArray(value.clues) && value.clues.every(item => object(item) && typeof item.id === "string" && typeof item.title === "string" && typeof item.type === "string" && typeof item.headline === "string" && typeof item.summary === "string" && strings(item.discoveries) && Array.isArray(item.evidence) && item.evidence.every(row => object(row) && typeof row.type === "string" && typeof row.label === "string" && typeof row.content === "string"))
}
export function isAnalysisResult(value: unknown): value is AnalysisResult {
  return object(value) && value.schema === "peixian.analysis-result" && value.version === "1.0" && displayArrays(value) && Array.isArray(value.subjects) && strings(value.conclusions)
}

// Use only for the authenticated session evidence endpoint, never model message data.
export function legacyPresentation(value: unknown): AnalysisResult | undefined {
  if (!object(value) || value.schema !== undefined || value.version !== "1.0" || !displayArrays(value) || !Array.isArray(value.conclusions) || !value.conclusions.every(item => object(item) && typeof item.text === "string" && strings(item.source_ids) && (item.clue_id === undefined || typeof item.clue_id === "string")) || !strings(value.missing)) return
  const sources = value.conclusions as NonNullable<AnalysisResult["conclusion_sources"]>
  return { schema: "peixian.analysis-result", version: "1.0", process: value.process as AnalysisResult["process"], subjects: [], conclusions: sources.map(item => item.text), conclusion_sources: sources, evidence: value.evidence as AnalysisResult["evidence"], clues: value.clues as AnalysisResult["clues"], missing: value.missing, presentation_version: value.version }
}
export function acceptedRun(value: unknown, session: string): Run {
  if (!object(value) || value.accepted !== true || typeof value.run_id !== "string" || !value.run_id || typeof value.message_id !== "string" || !value.message_id) throw new Error("提交结果待确认，请核对执行记录，不要重复提交。")
  return { id: value.run_id, session_id: session, status: "queued", phase: "accepted", user_message_id: value.message_id, created_at: "" }
}
