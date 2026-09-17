import { describe, expect, test } from "bun:test"
import { capabilityCatalog } from "../src/capability-catalog"
import type { Plugin } from "../src/types"
describe("personal capability contract", () => {
  test("only enabled skills are selectable and credentials never enter display catalog", () => {
    const value = capabilityCatalog([{ id: "s", name: "method", content: "instruction", enabled: true }, { id: "off", name: "off", enabled: false, content: "" }], [{ id: "p", name: "tool", version: "1", installed: { version: "1", enabled: true, state: "pending", config: { private: "not-for-catalog" } } }])
    expect(value.map((item) => item.kind)).toEqual(["skill", "plugin"])
    expect(JSON.stringify(value)).not.toContain("not-for-catalog")
    expect(value[1].state).toBe("待生效")
  })
  test("installed does not imply applied or enabled", () => {
    const plugin: Plugin = { id: "p", name: "tool", version: "2" }
    expect(capabilityCatalog([], [plugin])[0].state).toBe("待安装")
    plugin.installed = { version: "1", enabled: false, state: "active" }
    expect(capabilityCatalog([], [plugin])[0].state).toBe("已停用")
    plugin.installed.enabled = true
    expect(capabilityCatalog([], [plugin])[0].state).toBe("已生效")
    plugin.connection_status = { "1": { ready: false, missing: ["service"] } }
    expect(capabilityCatalog([], [plugin])[0].state).toBe("连接待配置")
  })
})
