const VERSION = "1.0.0"
const CERTIFICATE = { type: "string", pattern: "^[0-9]{17}[0-9Xx]$", description: "18位公民身份号码" }

export default async function plugin(_context, options, platform) {
  const execute = (path) => async (args) => query(platform, options, path, args)
  return {
    tool: {
      peixian_query_case_records: { description: "按身份证号查询人员涉案记录。记录只表示数据源中的案件关联角色。", args: { certificate_no: CERTIFICATE }, execute: execute("/v1/police/cases/query") },
      peixian_query_police_incidents: { description: "按身份证号查询人员涉警记录。不得把报警人、当事人等角色自动表述为违法嫌疑人。", args: { certificate_no: CERTIFICATE }, execute: execute("/v1/police/incidents/query") },
      peixian_query_disputes: { description: "按身份证号查询纠纷调解记录。", args: { certificate_no: CERTIFICATE }, execute: execute("/v1/police/disputes/query") },
    },
  }
}

async function query(platform, options, path, args) {
  if (!/^[0-9]{17}[0-9Xx]$/.test(args.certificate_no || "")) throw new Error("请输入有效的18位身份证号。")
  const limit = options.max_items || 50
  const result = await platform.connections.request("peixian_data", { method: "POST", path, json: { certificate_no: args.certificate_no, page: { number: 1, size: limit } } })
  if (result.status !== 200) throw new Error(result.data?.error?.retryable ? "警情案件数据服务暂时不可用，请稍后重试。" : "警情案件查询失败，请核对查询条件。")
  if (result.data?.schema_version !== "1.0" || !Array.isArray(result.data?.items)) throw new Error("数据服务返回格式不符合约定，请联系管理员。")
  const items = result.data.items.slice(0, limit)
  const warnings = Array.isArray(result.data.warnings) ? result.data.warnings : []
  const truncated = result.data.items.length > limit || result.data.page?.has_more === true
  return JSON.stringify({ ...result.data, items, returned_count: items.length, truncated, warning_count: warnings.length, warnings: truncated ? [...warnings, "结果已截断，可缩小查询范围后重试。"] : warnings, version: VERSION })
}

export async function test(_options, platform) {
  const result = await platform.connections.request("peixian_data", { method: "GET", path: "/health" })
  return { ok: result.status === 200 && result.data?.ok === true && result.data?.schema_version === "1.0", message: "警情案件数据连接测试完成" }
}
