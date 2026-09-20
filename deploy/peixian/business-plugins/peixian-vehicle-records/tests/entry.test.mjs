import assert from "node:assert/strict"
import test from "node:test"
import plugin, { test as connectionTest } from "../entry.mjs"

const platform = { connections: { async request(_alias, request) {
  if (request.path === "/health") return { status: 200, data: { ok: true, schema_version: "1.0" } }
  return { status: 200, data: { schema_version: "1.0", trace_id: "trace", source: "mock", queried_at: "2026-09-17T00:00:00Z", returned_count: 1, total_count: 1, page: { number: 1, size: 50, has_more: false }, items: [{ plate_no: "TEST" }], warnings: [] } }
} } }

test("queries motor and non-motor records", async () => {
  const loaded = await plugin({}, { max_items: 50 }, platform)
  assert.equal(Object.keys(loaded.tool).length, 2)
  assert.equal(JSON.parse(await loaded.tool.peixian_query_vehicles.execute({ certificate_no: "999999199001010001" })).items[0].plate_no, "TEST")
  assert.equal(JSON.parse(await loaded.tool.peixian_query_non_motor_vehicles.execute({ certificate_no: "999999199001010001" })).items[0].plate_no, "TEST")
})

test("tests health", async () => {
  assert.equal((await connectionTest({}, platform)).ok, true)
})
