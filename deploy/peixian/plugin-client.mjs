// Platform-provided client: only account-bound connection identifiers are sent.
// Long-lived upstream credentials never enter this module or plugin options.
export function createPlatform(bindings = {}, request = fetch) {
  const allowed = Object.freeze({ ...bindings });
  return Object.freeze({
    connections: Object.freeze({
      async request(alias, input) {
        const binding = allowed[alias];
        if (!binding || !/^[a-zA-Z0-9_-]{1,128}$/.test(binding.id) || typeof binding.token !== "string")
          throw new Error("服务连接尚未配置，请联系超级管理员。");
        if (!input || typeof input !== "object" || Array.isArray(input) ||
            Object.keys(input).some(key => !["method", "path", "query", "json"].includes(key)))
          throw new Error("服务请求参数无效。");
        const body = JSON.stringify(input);
        if (new TextEncoder().encode(body).length > 1048576)
          throw new Error("服务请求超过大小限制。");
        let response;
        try {
          response = await request("http://model-relay:8081/platform/connections/" + binding.id + "/request", {
            method: "POST",
            headers: { "Content-Type": "application/json", "Authorization": "Bearer " + binding.token },
            body,
            signal: AbortSignal.timeout(65000),
            redirect: "error",
          });
          if (!response.ok || !response.body) throw new Error();
          const reader = response.body.getReader();
          const chunks = [];
          let size = 0;
          try {
            for (;;) {
              const next = await reader.read();
              if (next.done) break;
              size += next.value.byteLength;
              if (size > 10485760 + 4096) throw new Error();
              chunks.push(next.value);
            }
          } finally {
            await reader.cancel().catch(() => {});
          }
          const bytes = new Uint8Array(size);
          let offset = 0;
          for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
          const result = JSON.parse(new TextDecoder().decode(bytes));
          if (!Number.isInteger(result.status) || !("data" in result)) throw new Error();
          return result;
        } catch {
          throw new Error("服务调用未完成，请检查连接状态或稍后重试。");
        }
      },
    }),
  });
}
