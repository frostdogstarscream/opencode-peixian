const VERSION = "1.0.0";
const CONNECTION = "peixian_records";
const SOURCE = "沛县七项合成资料服务";

const TOOLS = {
  peixian_get_funds_records: { module: "funds", description: "查询资金碰撞模块的完整合成原始记录。仅在用户明确要求资金资料或资金碰撞资料时调用。" },
  peixian_get_calls_records: { module: "calls", description: "查询话单碰撞模块的完整合成原始记录。仅在用户明确要求话单或通话碰撞资料时调用。" },
  peixian_get_portrait_records: { module: "portrait", description: "查询预先标注的人像事件模块合成原始记录。仅在用户明确要求人像、同框、同行或同乘资料时调用。" },
  peixian_get_composite_records: { module: "composite", description: "查询综合碰撞模块的合成原始记录。仅用于按既有对象对应关系查看分来源资料，不生成综合评分。" },
  peixian_get_night_records: { module: "night", description: "查询夜间活动模块的完整合成原始记录。仅在用户明确要求夜间活动资料时调用。" },
  peixian_get_vehicle_records: { module: "vehicle", description: "查询驾乘车辆模块的完整合成原始记录。仅在用户明确要求车辆使用资料时调用。" },
  peixian_get_lookup_records: { module: "lookup", description: "查询关联互查模块的完整合成原始记录。仅在用户明确要求已有对应关系或已有交集资料时调用。" },
};

function output(module, data) {
  if (data?.synthetic !== true || data?.module !== module || data?.data_status !== "complete" || !Array.isArray(data?.records)) {
    throw new Error("合成资料服务未返回可用结果，请稍后重试。");
  }
  if (data.returned_count !== data.records.length || data.total_count !== data.records.length || data.has_more !== false) {
    throw new Error("合成资料服务返回不完整，请稍后重试。");
  }
  return JSON.stringify({
    items: data.records,
    module: data.module,
    data_status: data.data_status,
    returned_count: data.returned_count,
    total_count: data.total_count,
    has_more: data.has_more,
    snapshot_id: data.snapshot_id,
    source: SOURCE,
    synthetic: true,
    rule_version: data.rule_version,
    rule_status: data.rule_status,
  });
}

export default async function plugin(_context, _options, platform) {
  return {
    tool: Object.fromEntries(Object.entries(TOOLS).map(([name, definition]) => [name, {
      description: definition.description,
      args: {},
      async execute() {
        const result = await platform.connections.request(CONNECTION, {
          method: "POST",
          path: "/v1/demo/records/query",
          json: { module: definition.module },
        });
        if (result.status !== 200) throw new Error("合成资料服务暂时不可用，请稍后重试。");
        return output(definition.module, result.data);
      },
    }])),
  };
}

export async function test(_options, platform) {
  const result = await platform.connections.request(CONNECTION, { method: "GET", path: "/health" });
  return { ok: result.status === 200 && result.data?.ok === true && result.data?.synthetic === true, message: "合成资料连接测试完成" };
}
