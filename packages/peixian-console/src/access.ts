import type { Capability, Role, User } from "./types"

export const roleNames: Record<Role, string> = { super_admin: "超级管理员", admin: "管理员", user: "普通用户" }
export const managementTabs = [
  { id: "users", label: "用户管理", capability: "users.manage" },
  { id: "models", label: "模型管理", capability: "models.manage" },
  { id: "plugins", label: "插件发布", capability: "plugins.manage" },
  { id: "templates", label: "技能模板", capability: "templates.manage" },
  { id: "audit", label: "操作记录", capability: "audit.read" },
] as const
export type ManagementTab = (typeof managementTabs)[number]["id"]
export type AdminResource = ManagementTab | "jobs"

export function visibleManagementTabs(capabilities: readonly Capability[]) {
  return managementTabs.filter((tab) => capabilities.includes(tab.capability))
}

export function adminResources(tab: ManagementTab, capabilities: readonly Capability[]): AdminResource[] {
  if (!visibleManagementTabs(capabilities).some((item) => item.id === tab)) return []
  if (tab === "users")
    return [
      "users",
      ...(capabilities.includes("models.manage") ? ["models" as const] : []),
      ...(capabilities.includes("plugins.manage") ? ["plugins" as const] : []),
      ...(capabilities.includes("jobs.read") ? ["jobs" as const] : []),
    ]
  if (tab === "audit" && capabilities.includes("users.manage")) return ["audit", "users"]
  return [tab]
}

export function canManageUser(capabilities: readonly Capability[], target: User, actorId: string) {
  if (target.id === actorId || target.role === "super_admin" || !capabilities.includes("users.manage")) return false
  return target.role === "user" || (target.role === "admin" && capabilities.includes("admins.manage"))
}

export function userGrantBody(capabilities: readonly Capability[], modelIds: string[], pluginIds: string[]) {
  if (!capabilities.includes("users.manage")) throw new Error("你没有管理用户的权限。")
  return { model_ids: modelIds, ...(capabilities.includes("plugins.manage") ? { plugin_ids: pluginIds } : {}) }
}

export function userCreateBody(
  capabilities: readonly Capability[],
  values: { username: string; password: string; role: "admin" | "user"; modelIds: string[]; pluginIds: string[] },
) {
  if (!capabilities.includes("users.manage")) throw new Error("你没有创建账号的权限。")
  const account = { username: values.username.trim(), ...(values.password ? { password: values.password } : {}) }
  if (values.role === "admin") {
    if (!capabilities.includes("admins.manage")) throw new Error("你没有创建管理员的权限。")
    return { ...account, role: "admin" as const }
  }
  return {
    ...account,
    ...(capabilities.includes("admins.manage") ? { role: "user" as const } : {}),
    ...userGrantBody(capabilities, values.modelIds, values.pluginIds),
  }
}
