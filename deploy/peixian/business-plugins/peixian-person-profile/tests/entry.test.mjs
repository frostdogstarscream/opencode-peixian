import assert from "node:assert/strict"
import test from "node:test"
import plugin, { test as connectionTest } from "../entry.mjs"

const platform = {
  connections: {
    async request(_alias, request) {
      if (request.path === "/health") return { status: 200, data: { ok: true, schema_version: "1.0" } }
      return { status: 200, data: { schema_version: "1.0", trace_id: "trace", source: "mock", queried_at: "2026-09-17T00:00:00Z", returned_count: 1, total_count: 1, page: { number: 1, size: 50, has_more: false }, items: [{ source_record_id: "mock" }], warnings: [] } }
    },
  },
}

test("exposes profile tools and normalizes output", async () => {
  const loaded = await plugin({}, { max_items: 50 }, platform)
  assert.equal(Object.keys(loaded.tool).length, 3)
  const result = JSON.parse(await loaded.tool.peixian_query_person_profile.execute({ certificate_no: "999999199001010001" }))
  assert.equal(result.returned_count, 1)
  assert.equal(result.version, "1.0.0")
})

test("rejects an invalid certificate number", async () => {
  const loaded = await plugin({}, { max_items: 50 }, platform)
  await assert.rejects(loaded.tool.peixian_query_houses.execute({ certificate_no: "bad" }))
})

test("connection test uses health endpoint", async () => {
  assert.equal((await connectionTest({}, platform)).ok, true)
})
