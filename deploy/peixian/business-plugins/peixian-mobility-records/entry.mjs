const VERSION = "1.0.0"
const CERTIFICATE = { type: "string", pattern: "^[0-9]{17}[0-9Xx]$", description: "18位公民身份号码" }
const DATETIME = { type: "string", format: "date-time", description: "带时区的 ISO 8601 时间" }

export default async function plugin(_context, options, platform) {
  const basic = (path) => async (args) => query(platform, options, path, { certificate_no: requireCertificate(args.certificate_no) })
  return {
    tool: {
      peixian_query_tracks: {
        description: "按身份证号和时间范围查询人员及关联车辆轨迹。轨迹记录只表示数据源观测，不自动证明人员关系。",
        args: { certificate_no: CERTIFICATE, begin_time: DATETIME, end_time: DATETIME },
        async execute(args) {
          requireCertificate(args.certificate_no)
          const begin = Date.parse(args.begin_time)
          const end = Date.parse(args.end_time)
          if (!Number.isFinite(begin) || !Number.isFinite(end) || begin > end) throw new Error("请输入有效且先后顺序正确的起止时间。")
          return query(platform, options, "/v1/mobility/tracks/query", { certificate_no: args.certificate_no, begin_time: args.begin_time, end_time: args.end_time, track_types: [0, 1, 2] })
        },
      },
      peixian_query_hotels: { description: "按身份证号查询旅馆住宿记录。", args: { certificate_no: CERTIFICATE }, execute: basic("/v1/mobility/hotels/query") },
      peixian_query_railway: { description: "按身份证号查询铁路出行记录。", args: { certificate_no: CERTIFICATE }, execute: basic("/v1/mobility/railway/query") },
      peixian_query_netbar: { description: "按身份证号查询网吧活动记录。", args: { certificate_no: CERTIFICATE }, execute: basic("/v1/mobility/netbar/query") },
    },
  }
}

function requireCertificate(value) {
  if (!/^[0-9]{17}[0-9Xx]$/.test(value || "")) throw new Error("请输入有效的18位身份证号。")
  return value
}

async function query(platform, options, path, body) {
  const limit = options.max_items || 50
  const result = await platform.connections.request("peixian_data", { method: "POST", path, json: { ...body, page: { number: 1, size: limit } } })
  if (result.status !== 200) throw new Error(result.data?.error?.retryable ? "活动记录数据服务暂时不可用，请稍后重试。" : "活动记录查询失败，请核对查询条件。")
  if (result.data?.schema_version !== "1.0" || !Array.isArray(result.data?.items)) throw new Error("数据服务返回格式不符合约定，请联系管理员。")
  const items = result.data.items.slice(0, limit)
  const warnings = Array.isArray(result.data.warnings) ? result.data.warnings : []
  const truncated = result.data.items.length > limit || result.data.page?.has_more === true
  return JSON.stringify({ ...result.data, items, returned_count: items.length, truncated, warning_count: warnings.length, warnings: truncated ? [...warnings, "结果已截断，可缩小查询范围后重试。"] : warnings, version: VERSION })
}

export async function test(_options, platform) {
  const result = await platform.connections.request("peixian_data", { method: "GET", path: "/health" })
  return { ok: result.status === 200 && result.data?.ok === true && result.data?.schema_version === "1.0", message: "活动记录数据连接测试完成" }
}
