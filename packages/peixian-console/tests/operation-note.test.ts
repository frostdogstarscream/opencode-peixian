import { expect, test } from "bun:test"
import { operationNote } from "../src/operation-note"

test("gateway test statuses display Chinese and distinguish unsupported from passed", () => {
  expect(operationNote({ supported: true, ok: true, message: "Connection test passed" })).toBe("测试通过。")
  expect(operationNote({ supported: true, ok: false, message: "Connection test failed" })).toContain("测试未通过")
  expect(operationNote({ supported: false, ok: false, message: "Plugin does not export a connection test" })).toContain(
    "尚未提供连接测试",
  )
  expect(operationNote({ supported: true, ok: false, message: "Connection test timed out" })).toContain("超时")
  expect(operationNote({ message: "Connection test failed" })).toContain("测试未通过")
})

test("Chinese business guidance is preserved with internal addresses redacted", () => {
  expect(operationNote({ ok: false, message: "平台服务连接尚未配置，请联系超级管理员" })).toBe(
    "平台服务连接尚未配置，请联系超级管理员",
  )
  expect(operationNote({ ok: false, message: "连接 https://example.internal 失败" })).toBe("连接 服务连接 失败")
})

test("configuration jobs and unknown payloads do not imply successful connection tests", () => {
  expect(operationNote({ ok: true, job: { status: "queued" } })).toContain("正在更新")
  expect(operationNote({ message: "unrecognized status" })).not.toContain("测试通过")
  expect(operationNote(null)).not.toContain("操作已完成")
})
