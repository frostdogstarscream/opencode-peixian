const VERSION = "1.0.0"

export default async function plugin(_context, options, platform) {
  return {
    tool: {
      peixian_query_family_relations: {
        description: "按身份证号查询家庭和婚姻关系记录，仅返回登记数据，不推断未登记关系。",
        args: { certificate_no: { type: "string", pattern: "^[0-9]{17}[0-9Xx]$", description: "18位公民身份号码" } },
        async execute(args) {
          if (!/^[0-9]{17}[0-9Xx]$/.test(args.certificate_no || "")) throw new Error("请输入有效的18位身份证号。")
          const limit = options.max_items || 50
          const result = await platform.connections.request("peixian_data", { method: "POST", path: "/v1/person/family/query", json: { certificate_no: args.certificate_no, page: { number: 1, size: limit } } })
          if (result.status !== 200) throw new Error(result.data?.error?.retryable ? "家庭关系数据服务暂时不可用，请稍后重试。" : "家庭关系查询失败，请核对查询条件。")
          if (result.data?.schema_version !== "1.0" || !Array.isArray(result.data?.items)) throw new Error("数据服务返回格式不符合约定，请联系管理员。")
          const items = result.data.items.slice(0, limit)
          const warnings = Array.isArray(result.data.warnings) ? result.data.warnings : []
          const truncated = result.data.items.length > limit || result.data.page?.has_more === true
          return JSON.stringify({ ...result.data, items, returned_count: items.length, truncated, warning_count: warnings.length, warnings: truncated ? [...warnings, "结果已截断，可缩小查询范围后重试。"] : warnings, version: VERSION })
        },
      },
    },
  }
}

export async function test(_options, platform) {
  const result = await platform.connections.request("peixian_data", { method: "GET", path: "/health" })
  return { ok: result.status === 200 && result.data?.ok === true && result.data?.schema_version === "1.0", message: "家庭关系数据连接测试完成" }
}
