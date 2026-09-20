const VERSION = "1.0.0"
const CERTIFICATE = { type: "string", pattern: "^[0-9]{17}[0-9Xx]$", description: "18位公民身份号码" }

export default async function plugin(_context, options, platform) {
  const execute = (path) => async (args) => query(platform, options, path, args)
  return {
    tool: {
      peixian_query_person_profile: {
        description: "按身份证号查询人员户籍和基础档案。只在用户明确要求查询人员基础资料时调用。",
        args: { certificate_no: CERTIFICATE },
        execute: execute("/v1/person/profile/query"),
      },
      peixian_query_houses: {
        description: "按身份证号查询人员名下房屋记录。",
        args: { certificate_no: CERTIFICATE },
        execute: execute("/v1/person/houses/query"),
      },
      peixian_query_companies: {
        description: "按身份证号查询人员关联单位记录。",
        args: { certificate_no: CERTIFICATE },
        execute: execute("/v1/person/companies/query"),
      },
    },
  }
}

async function query(platform, options, path, args) {
  requireCertificate(args.certificate_no)
  const result = await platform.connections.request("peixian_data", { method: "POST", path, json: { certificate_no: args.certificate_no, page: { number: 1, size: options.max_items || 50 } } })
  return normalize(result, options.max_items || 50)
}

function requireCertificate(value) {
  if (!/^[0-9]{17}[0-9Xx]$/.test(value || "")) throw new Error("请输入有效的18位身份证号。")
}

function normalize(result, limit) {
  if (result.status !== 200) throw new Error(result.data?.error?.retryable ? "数据服务暂时不可用，请稍后重试。" : "人员档案查询失败，请核对查询条件。")
  if (result.data?.schema_version !== "1.0" || !Array.isArray(result.data?.items)) throw new Error("数据服务返回格式不符合约定，请联系管理员。")
  const items = result.data.items.slice(0, limit)
  const warnings = Array.isArray(result.data.warnings) ? result.data.warnings : []
  const truncated = result.data.items.length > limit || result.data.page?.has_more === true
  return JSON.stringify({ ...result.data, items, returned_count: items.length, truncated, warning_count: warnings.length, warnings: truncated ? [...warnings, "结果已截断，可缩小查询范围后重试。"] : warnings, version: VERSION })
}

export async function test(_options, platform) {
  const result = await platform.connections.request("peixian_data", { method: "GET", path: "/health" })
  return { ok: result.status === 200 && result.data?.ok === true && result.data?.schema_version === "1.0", message: "人员档案数据连接测试完成" }
}
