import type { Plugin, Skill } from "./types"
import { pluginConnectionReady } from "./connections"
export type CapabilityEntry = {
  id: string; name: string; description?: string; kind: "skill" | "plugin"; version: string; state: string
}
export function capabilityCatalog(skills: Skill[], plugins: Plugin[]): CapabilityEntry[] {
  return [
    ...skills.filter((item) => item.enabled).map((item): CapabilityEntry => ({
      id: item.id, name: item.name, description: item.description, kind: "skill", version: String(item.version ?? 1), state: "已启用",
    })),
    ...plugins.map((item): CapabilityEntry => ({
      id: item.id, name: item.name, description: item.description, kind: "plugin", version: item.installed?.version ?? item.version,
      state: !item.installed ? "待安装" : !item.installed.enabled ? "已停用" : !pluginConnectionReady(item, item.installed.version) ? "连接待配置" : item.installed.state === "active" ? "已生效" : item.installed.state === "unavailable" ? "版本不可用" : "待生效",
    })),
  ]
}
