// No runtime npm install is required. Package any additional dependencies at build time.
const VERSION = "1.0.0";

export default async function plugin(context, options, platform) {
  return {
    tool: {
      platform_sample_records: {
        description: "查询示例资料服务。用户需要查找或汇总示例资料时调用，使用个人插件设置中的关键词和条数。",
        args: {},
        async execute() {
          const result = await platform.connections.request("records", {
            method: "GET", path: "/records", query: { q: options.query || "", limit: options.limit || 5 },
          });
          if (result.status !== 200 || !Array.isArray(result.data?.items))
            throw new Error("资料服务没有返回可用结果，请稍后重试。");
          return JSON.stringify({ items: result.data.items, count: result.data.items.length, version: VERSION, source: "示例资料服务" });
        },
      },
    },
  };
}

export async function test(options, platform) {
  const result = await platform.connections.request("records", { method: "GET", path: "/health" });
  return { ok: result.status === 200 && result.data?.ok === true, message: "连接测试完成" };
}
