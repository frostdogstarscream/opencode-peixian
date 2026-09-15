import { test, expect } from "bun:test";
import { createPlatform } from "../plugin-client.mjs";

test("only a bound identifier and delegated token reach the fixed relay", async () => {
  const requests = [];
  const platform = createPlatform({ records: { id: "a".repeat(32), token: "synthetic-delegated-token" } }, async (url, options) => {
    requests.push({ url, options });
    return new Response(JSON.stringify({ status: 200, data: { items: ["example"] } }));
  });
  expect(await platform.connections.request("records", { method: "GET", path: "/records" })).toEqual({status: 200, data: {items:["example"]}});
  expect(requests[0].url).toBe("http://model-relay:8081/platform/connections/" + "a".repeat(32) + "/request");
  expect(requests[0].options.redirect).toBe("error");
  expect(requests[0].options.headers.Authorization).toBe("Bearer synthetic-delegated-token");
  await expect(platform.connections.request("other", { method: "GET", path: "/records" })).rejects.toThrow("尚未配置");
  await expect(platform.connections.request("records", { method: "GET", path: "/records", url: "http://unapproved" })).rejects.toThrow("参数无效");
  expect(requests).toHaveLength(1);
});

test("upstream failures do not expose response content or credentials", async () => {
  const platform = createPlatform({ records: { id: "a".repeat(32), token: "synthetic-delegated-token" } }, async () =>
    new Response("internal URL and credentials must not escape", {status:403}));
  await expect(platform.connections.request("records", {method:"GET",path:"/records"})).rejects.toThrow("服务调用未完成");
});
