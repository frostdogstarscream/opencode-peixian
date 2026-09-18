const VERSION = "1.1.0";
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

async function recordsPlugin(_context, _options, platform) {
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

const SCENARIOS = {"DEMO-CASE-GAMBLING": {"synthetic": true, "snapshot_id": "DEMO-SCENARIOS-20260918-01", "records_snapshot_id": "DEMO-SNAPSHOT-20260918-01", "rule_version": "demo-scenarios-v1", "data_status": "complete", "timezone": "Asia/Shanghai", "window_start": "2026-09-14T00:00:00+08:00", "window_end": "2026-09-16T00:00:00+08:00", "night_window": "22:00-06:00", "scenario_id": "DEMO-CASE-GAMBLING", "title": "涉赌案件资料整理（合成演示）", "subject_ref": "DEMO-MEMBER-ORCHID", "required_modules": ["night", "portrait", "funds", "lookup"], "case_window": ["2026-09-14T22:00:00+08:00", "2026-09-15T06:00:00+08:00"], "facts": [{"record_id": "DEMO-CTX-G01", "title": "独立身份资料来源", "description": "虚构资料登记载明 DEMO-MEMBER-INDIGO 的既往涉赌记录，仅供演示资料引用；不能据此认定其他对象涉赌。", "source_record_ids": [], "source_document": "DEMO-DOC-G01", "occurred_at": "2026-09-01T09:00:00+08:00"}, {"record_id": "DEMO-CTX-G02", "title": "明确同行观测", "description": "资料明确标注 same_trip；仅表示该次同行观测，不表示参与共同活动。", "source_record_ids": ["DEMO-POR-005", "DEMO-POR-006"], "occurred_at": "2026-09-14T23:55:00+08:00"}, {"record_id": "DEMO-CTX-G03", "title": "合成地点映射", "description": "DEMO-CAMERA-CHARLIE 对应虚构地点 DEMO-PLACE-CHARLIE，无真实坐标。", "source_record_ids": ["DEMO-POR-005"], "occurred_at": "2026-09-14T23:55:00+08:00"}], "limitations": ["资料仅覆盖两个日期，不能据此概括长期频繁行为。", "流水缺少跨账户唯一配对键，不合并双边流水，不称为赌资。"]}, "DEMO-CASE-THEFT": {"synthetic": true, "snapshot_id": "DEMO-SCENARIOS-20260918-01", "records_snapshot_id": "DEMO-SNAPSHOT-20260918-01", "rule_version": "demo-scenarios-v1", "data_status": "complete", "timezone": "Asia/Shanghai", "window_start": "2026-09-14T00:00:00+08:00", "window_end": "2026-09-16T00:00:00+08:00", "night_window": "22:00-06:00", "scenario_id": "DEMO-CASE-THEFT", "title": "盗窃案件时空资料核对（合成演示）", "subject_ref": "DEMO-MEMBER-ORCHID", "required_modules": ["night", "portrait", "vehicle"], "case_window": ["2026-09-15T00:30:00+08:00", "2026-09-15T01:30:00+08:00"], "facts": [{"record_id": "DEMO-CTX-T01", "title": "合成案件登记", "description": "虚构事件发生范围为 00:30 至 01:30，地点 DEMO-PLACE-ECHO；这是场景设定，不是人员行为结论。", "source_record_ids": [], "source_document": "DEMO-DOC-T01", "occurred_at": "2026-09-15T00:30:00+08:00"}, {"record_id": "DEMO-CTX-T02", "title": "明确独行观测", "description": "补充观测仅在 01:12 的该段画面标注一人经过；不证明作案，也不证明其他时段没有同行者。", "source_record_ids": ["DEMO-NGT-007"], "source_document": "DEMO-DOC-T02", "occurred_at": "2026-09-15T01:12:00+08:00", "observation": "alone"}, {"record_id": "DEMO-CTX-T03", "title": "明确空间关系来源", "description": "虚构地点表将 DEMO-CAMERA-ECHO 标注为 DEMO-PLACE-ECHO 的相邻点；没有距离测量值，不推算米数。", "source_record_ids": ["DEMO-NGT-007"], "source_document": "DEMO-DOC-T03", "occurred_at": "2026-09-15T01:12:00+08:00"}, {"record_id": "DEMO-CTX-T04", "title": "无法判断的观测", "description": "22:16 资料没有同行覆盖信息，独行状态无法判断。", "source_record_ids": ["DEMO-NGT-001"], "occurred_at": "2026-09-14T22:16:00+08:00", "observation": "unknown"}, {"record_id": "DEMO-CTX-T05", "title": "明确同行观测", "description": "23:55 有明确同行记录；不能把其余时间无同行记录解释为独行。", "source_record_ids": ["DEMO-POR-005"], "occurred_at": "2026-09-14T23:55:00+08:00", "observation": "accompanied"}], "limitations": ["只有明确标注的观测才可描述独行或同行；缺失值保持无法判断。", "出现在相邻点不证明实施盗窃。", "车辆记录只表示各次使用，不证明同车同行。"]}};

export default async function plugin(context, options, platform) {
  const result = await recordsPlugin(context, options, platform);
  result.tool.peixian_get_scenario_context = {
    description: "读取指定虚构演示场景的资料范围、身份来源、观测说明与缺失项。只整理事实，不判定人员犯罪。",
    args: { scenario_id: { type: "string", enum: ["DEMO-CASE-GAMBLING", "DEMO-CASE-THEFT"], description: "固定合成场景编号" } },
    async execute(args) {
      if (!args || Object.keys(args).length !== 1 || !Object.hasOwn(SCENARIOS, args.scenario_id)) throw new Error("请选择固定合成场景。");
      return JSON.stringify(SCENARIOS[args.scenario_id]);
    },
  };
  return result;
}
