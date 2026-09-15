import { describe, expect, test } from "bun:test"
import {
  adminResources,
  canManageUser,
  roleNames,
  userCreateBody,
  userGrantBody,
  visibleManagementTabs,
} from "../src/access"
import type { Capability, User } from "../src/types"

const admin: Capability[] = ["users.manage", "models.manage", "audit.read"]
const superAdmin: Capability[] = [
  ...admin,
  "admins.manage",
  "plugins.manage",
  "templates.manage",
  "runtimes.manage",
  "jobs.read",
]
const ordinary: Capability[] = ["business.use"]
const account = (role: User["role"], id = "target"): User => ({
  id,
  role,
  username: "synthetic",
  must_change_password: false,
})
const create = {
  username: " synthetic-user ",
  password: "",
  role: "user" as const,
  modelIds: ["model"],
  pluginIds: ["plugin"],
}

describe("server capabilities determine management navigation and reads", () => {
  test("ordinary users have no management tabs or administrative reads", () => {
    expect(visibleManagementTabs(ordinary)).toEqual([])
    for (const tab of ["users", "models", "plugins", "templates", "audit"] as const)
      expect(adminResources(tab, ordinary)).toEqual([])
  })
  test("administrators load only users, models and audit resources", () => {
    expect(visibleManagementTabs(admin).map((tab) => tab.id)).toEqual(["users", "models", "audit"])
    expect(adminResources("users", admin)).toEqual(["users", "models"])
    expect(adminResources("models", admin)).toEqual(["models"])
    expect(adminResources("audit", admin)).toEqual(["audit", "users"])
    expect(adminResources("plugins", admin)).toEqual([])
    expect(adminResources("templates", admin)).toEqual([])
  })
  test("super administrators load only the active tab and required dependencies", () => {
    expect(visibleManagementTabs(superAdmin)).toHaveLength(5)
    expect(adminResources("users", superAdmin)).toEqual(["users", "models", "plugins", "jobs"])
    expect(adminResources("templates", superAdmin)).toEqual(["templates"])
    expect(adminResources("plugins", superAdmin)).toEqual(["plugins"])
  })
  test("an empty capability set fails closed", () => {
    expect(visibleManagementTabs([])).toEqual([])
    expect(adminResources("users", [])).toEqual([])
  })
})

describe("account mutation payloads", () => {
  test("admin creation omits role and plugin fields even when drafts contain them", () => {
    expect(userCreateBody(admin, create)).toEqual({ username: "synthetic-user", model_ids: ["model"] })
    expect(userGrantBody(admin, ["model"], ["plugin"])).toEqual({ model_ids: ["model"] })
  })
  test("admin cannot create another administrator", () => {
    expect(() => userCreateBody(admin, { ...create, role: "admin" })).toThrow("创建管理员")
  })
  test("super administrator creation excludes business grants and runtime fields", () => {
    expect(userCreateBody(superAdmin, { ...create, role: "admin" })).toEqual({
      username: "synthetic-user",
      role: "admin",
    })
  })
  test("super can create users with authorized models and plugins", () => {
    expect(userCreateBody(superAdmin, create)).toEqual({
      username: "synthetic-user",
      role: "user",
      model_ids: ["model"],
      plugin_ids: ["plugin"],
    })
  })
  test("grant updates never carry a role change", () => {
    expect(userGrantBody(superAdmin, [], [])).toEqual({ model_ids: [], plugin_ids: [] })
  })
  test("business users cannot produce management mutation payloads", () => {
    expect(() => userCreateBody(ordinary, create)).toThrow("创建账号")
    expect(() => userGrantBody(ordinary, [], [])).toThrow("管理用户")
  })
})

describe("manageable account boundaries", () => {
  test("admin manages ordinary users only", () => {
    expect(canManageUser(admin, account("user"), "actor")).toBe(true)
    expect(canManageUser(admin, account("admin"), "actor")).toBe(false)
    expect(canManageUser(admin, account("super_admin"), "actor")).toBe(false)
  })
  test("super manages users and admins, never super administrators or self", () => {
    expect(canManageUser(superAdmin, account("user"), "actor")).toBe(true)
    expect(canManageUser(superAdmin, account("admin"), "actor")).toBe(true)
    expect(canManageUser(superAdmin, account("super_admin"), "actor")).toBe(false)
    expect(canManageUser(superAdmin, account("user", "actor"), "actor")).toBe(false)
  })
  test("labels distinguish all three roles", () => {
    expect(Object.values(roleNames)).toEqual(["超级管理员", "管理员", "普通用户"])
  })
})
