import { expect, test } from "bun:test";
import createPlugin, { test as testConnection } from "./plugin/entry.mjs";

const toolModules = {
  peixian_get_funds_records: "funds",
  peixian_get_calls_records: "calls",
  peixian_get_portrait_records: "portrait",
  peixian_get_composite_records: "composite",
  peixian_get_night_records: "night",
  peixian_get_vehicle_records: "vehicle",
  peixian_get_lookup_records: "lookup",
};

function response(module) {
  return {
    schema_version: "1.0",
    synthetic: true,
    module,
    snapshot_id: "DEMO-SNAPSHOT-001",
    scope: { material_batch: "DEMO-BATCH-001", timezone: "Asia/Shanghai", query_scope: "embedded_fixture_only" },
    data_status: "complete",
    records: [{ record_id: "DEMO-" + module, source_type: module, group_ref: "DEMO-GROUP", member_ref: "DEMO-MEMBER" }],
    returned_count: 1,
    total_count: 1,
    has_more: false,
    missing_sources: [],
    errors: [],
    rule_version: "demo-v1",
    rule_status: "demo_only",
  };
}

test("all seven tools use the fixed read-only connection and exact module body", async () => {
  const calls = [];
  const platform = { connections: { request: async (alias, request) => {
    calls.push({ alias, request });
    return { status: 200, data: response(request.json.module) };
  } } };
  const plugin = await createPlugin({}, {}, platform);
  expect(Object.keys(plugin.tool).sort()).toEqual(Object.keys(toolModules).sort());
  for (const [name, module] of Object.entries(toolModules)) {
    const result = JSON.parse(await plugin.tool[name].execute());
    expect(result).toMatchObject({ module, synthetic: true, data_status: "complete", returned_count: 1, total_count: 1, has_more: false, snapshot_id: "DEMO-SNAPSHOT-001" });
    expect(result.items).toEqual(response(module).records);
  }
  expect(calls).toHaveLength(7);
  for (const [index, module] of Object.values(toolModules).entries()) {
    expect(calls[index]).toEqual({ alias: "peixian_records", request: { method: "POST", path: "/v1/demo/records/query", json: { module } } });
  }
});

test("the plugin fails closed for an incomplete or non-synthetic response", async () => {
  const platform = { connections: { request: async () => ({ status: 200, data: { ...response("funds"), synthetic: false } }) } };
  const plugin = await createPlugin({}, {}, platform);
  await expect(plugin.tool.peixian_get_funds_records.execute()).rejects.toThrow("合成资料服务未返回可用结果");
});

test("connection testing reaches only the health endpoint", async () => {
  const calls = [];
  const platform = { connections: { request: async (alias, request) => {
    calls.push({ alias, request });
    return { status: 200, data: { ok: true, synthetic: true } };
  } } };
  expect(await testConnection({}, platform)).toEqual({ ok: true, message: "合成资料连接测试完成" });
  expect(calls).toEqual([{ alias: "peixian_records", request: { method: "GET", path: "/health" } }]);
});
