import { describe, expect, test } from "bun:test"
import { connectionBody, connectionDraft, connectionTestPaths, pluginConnectionReady } from "../src/connections"
import { defaultPlatform, platformMetadata } from "../src/platform"
import type { Plugin, ServiceConnection } from "../src/types"

const connection: ServiceConnection = {
  ...connectionDraft(),
  id: "service",
  name: "Synthetic service",
  base_url: "https://example.internal",
  auth_type: "api_key",
  header_name: "X-API-Key",
  secret_configured: true,
  revision: 2,
}
const plugin: Plugin = { id: "synthetic", name: "Synthetic", version: "1.0.0" }

describe("service connection editor preserves protected credentials", () => {
  test("editing never populates a secret and blank edits preserve the stored value", () => {
    const draft = connectionDraft(connection)
    expect(draft.secret).toBe("")
    const body = connectionBody(draft, connection)
    expect(body).not.toHaveProperty("secret")
    expect(body).not.toHaveProperty("secret_configured")
    expect(body).not.toHaveProperty("id")
    expect(body).not.toHaveProperty("revision")
  })
  test("new authenticated connections and changed auth scope require new credentials", () => {
    expect(() => connectionBody(connectionDraft(connection))).toThrow("访问凭据")
    expect(() => connectionBody({ ...connectionDraft(connection), auth_type: "bearer" }, connection)).toThrow(
      "访问凭据",
    )
    expect(() => connectionBody({ ...connectionDraft(connection), header_name: "X-Other" }, connection)).toThrow(
      "访问凭据",
    )
  })
  test("disabling authentication omits a previous draft secret", () => {
    const body = connectionBody(
      { ...connectionDraft(connection), auth_type: "none", secret: "synthetic-only" },
      connection,
    )
    expect(body).not.toHaveProperty("secret")
    expect(body.header_name).toBe("")
  })
  test("replacement credentials are only sent on explicit entry", () => {
    expect(connectionBody({ ...connectionDraft(connection), secret: "synthetic-only" }, connection).secret).toBe(
      "synthetic-only",
    )
  })
})

describe("service request policy form", () => {
  test("rejects embedded credentials, URL fragments and query strings", () => {
    for (const base_url of [
      "file:///tmp",
      "https://user:password@example.internal",
      "https://example.internal?token=x",
      "https://example.internal#part",
    ])
      expect(() => connectionBody({ ...connectionDraft(connection), base_url }, connection)).toThrow("服务地址")
  })
  test("rejects ambiguous paths but retains an explicit descendant rule", () => {
    for (const path of [
      "https://example.internal/",
      "//external",
      "/records/../secret",
      "/records/%2f",
      "/records?a=1",
      "/records\\file",
      "/rec*ords",
      "/records/*/child",
    ])
      expect(() => connectionBody({ ...connectionDraft(connection), allowed_paths: [path] }, connection)).toThrow(
        "路径",
      )
    expect(
      connectionBody({ ...connectionDraft(connection), allowed_paths: [" /records/* ", "/records/*", ""] }, connection)
        .allowed_paths,
    ).toEqual(["/records/*"])
  })
  test("requires allowed methods and bounded timeout and response size", () => {
    expect(() => connectionBody({ ...connectionDraft(connection), allowed_methods: [] }, connection)).toThrow("方法")
    expect(() => connectionBody({ ...connectionDraft(connection), allowed_methods: ["HEAD"] }, connection)).toThrow(
      "方法",
    )
    for (const timeout_seconds of [0, 61, 1.5, NaN])
      expect(() => connectionBody({ ...connectionDraft(connection), timeout_seconds }, connection)).toThrow("超时")
    for (const max_response_bytes of [1023, 10485761, NaN])
      expect(() => connectionBody({ ...connectionDraft(connection), max_response_bytes }, connection)).toThrow("响应")
  })
  test("a wildcard is never submitted as a literal test path", () => {
    expect(connectionTestPaths({ ...connection, allowed_paths: ["/records/*", "/health"] })).toEqual(["/health"])
  })
})

describe("user plugin status", () => {
  test("unconfigured installed versions cannot be enabled", () => {
    expect(
      pluginConnectionReady(
        { ...plugin, installed: { version: "1.0.0", enabled: false, state: "unconfigured" } },
        "1.0.0",
      ),
    ).toBe(false)
  })
  test("changing version uses that version's platform readiness", () => {
    const item = {
      ...plugin,
      connection_status: { "1.0.0": { ready: false, missing: ["records"] }, "2.0.0": { ready: true, missing: [] } },
    }
    expect(pluginConnectionReady(item, "1.0.0")).toBe(false)
    expect(pluginConnectionReady(item, "2.0.0")).toBe(true)
  })
  test("plugins without external connections remain usable", () => {
    expect(pluginConnectionReady(plugin, "1.0.0")).toBe(true)
  })
})

describe("public platform metadata", () => {
  test("defaults remain available during metadata service startup", () => {
    expect(platformMetadata(null)).toEqual(defaultPlatform)
    expect(platformMetadata({ name: " " })).toEqual(defaultPlatform)
  })
  test("custom branding applies independently without leaking unspecified metadata", () => {
    expect(platformMetadata({ name: " Team Agent ", short_name: "TA" })).toEqual({
      name: "Team Agent",
      short_name: "TA",
      description: defaultPlatform.description,
    })
  })
})
