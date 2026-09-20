import assert from "node:assert/strict"
import test from "node:test"
import plugin, { test as connectionTest } from "../entry.mjs"

const platform = { connections: { async request(_alias, request) {
  if (request.path === "/health") return { status: 200, data: { ok: true, schema_version: "1.0" } }
  return { status: 200, data: { schema_version: "1.0", trace_id: "trace", source: "mock", queried_at: "2026-09-17T00:00:00Z", returned_count: 1, total_count: 1, page: { number: 1, size: 50, has_more: false }, items: [{ source_record_id: "mock" }], warnings: [] } }
} } }

test("exposes three police record tools", async () => {
  const loaded = await plugin({}, { max_items: 50 }, platform)
  assert.equal(Object.keys(loaded.tool).length, 3)
  const result = JSON.parse(await loaded.tool.peixian_query_case_records.execute({ certificate_no: "999999199001010001" }))
  assert.equal(result.returned_count, 1)
})

test("reports adapter failures safely", async () => {
  const failing = { connections: { async request() { return { status: 504, data: { error: { retryable: true, message: "private upstream body" } } } } } }
  const loaded = await plugin({}, { max_items: 50 }, failing)
  await assert.rejects(loaded.tool.peixian_query_police_incidents.execute({ certificate_no: "999999199001010001" }), /暂时不可用/)
})

test("connection test uses health", async () => {
  assert.equal((await connectionTest({}, platform)).ok, true)
})
