import assert from "node:assert/strict"
import test from "node:test"
import plugin, { test as connectionTest } from "../entry.mjs"

const platform = { connections: { async request(_alias, request) {
  if (request.path === "/health") return { status: 200, data: { ok: true, schema_version: "1.0" } }
  return { status: 200, data: { schema_version: "1.0", trace_id: "trace", source: "mock", queried_at: "2026-09-17T00:00:00Z", returned_count: 1, total_count: 1, page: { number: 1, size: 50, has_more: false }, items: [{ relation: "配偶" }], warnings: [] } }
} } }

test("queries family relations", async () => {
  const loaded = await plugin({}, { max_items: 50 }, platform)
  const result = JSON.parse(await loaded.tool.peixian_query_family_relations.execute({ certificate_no: "999999199001010001" }))
  assert.equal(result.items[0].relation, "配偶")
})

test("rejects invalid input and tests health", async () => {
  const loaded = await plugin({}, { max_items: 50 }, platform)
  await assert.rejects(loaded.tool.peixian_query_family_relations.execute({ certificate_no: "bad" }))
  assert.equal((await connectionTest({}, platform)).ok, true)
})
