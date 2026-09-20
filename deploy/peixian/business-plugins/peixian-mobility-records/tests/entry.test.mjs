import assert from "node:assert/strict"
import test from "node:test"
import plugin, { test as connectionTest } from "../entry.mjs"

const calls = []
const platform = { connections: { async request(_alias, request) {
  calls.push(request)
  if (request.path === "/health") return { status: 200, data: { ok: true, schema_version: "1.0" } }
  return { status: 200, data: { schema_version: "1.0", trace_id: "trace", source: "mock", queried_at: "2026-09-17T00:00:00Z", returned_count: 1, total_count: 1, page: { number: 1, size: 50, has_more: false }, items: [{ source_record_id: "mock" }], warnings: [] } }
} } }

test("queries tracks with an explicit range", async () => {
  const loaded = await plugin({}, { max_items: 50 }, platform)
  const result = JSON.parse(await loaded.tool.peixian_query_tracks.execute({ certificate_no: "999999199001010001", begin_time: "2026-09-01T00:00:00+08:00", end_time: "2026-09-17T23:59:59+08:00" }))
  assert.equal(result.returned_count, 1)
  assert.deepEqual(calls.at(-1).json.track_types, [0, 1, 2])
})

test("rejects a reversed time range", async () => {
  const loaded = await plugin({}, { max_items: 50 }, platform)
  await assert.rejects(loaded.tool.peixian_query_tracks.execute({ certificate_no: "999999199001010001", begin_time: "2026-09-18T00:00:00+08:00", end_time: "2026-09-17T00:00:00+08:00" }))
})

test("exposes four tools and tests health", async () => {
  const loaded = await plugin({}, { max_items: 50 }, platform)
  assert.equal(Object.keys(loaded.tool).length, 4)
  assert.equal((await connectionTest({}, platform)).ok, true)
})
