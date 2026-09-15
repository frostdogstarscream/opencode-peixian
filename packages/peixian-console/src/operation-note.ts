import { safeMessage } from "./api"

const testMessages: Record<string, string> = {
  "Plugin does not export a connection test": "这个插件尚未提供连接测试功能。请通过实际调用核验。",
  "Connection test passed": "测试通过。",
  "Connection test failed": "测试未通过，请检查配置后重试。",
  "Connection test timed out": "连接测试超时，请稍后重试或联系超级管理员检查服务。",
}

export function operationNote(value: unknown) {
  const result = value as {
    message?: string
    job?: { status?: string }
    success?: boolean
    ok?: boolean
    passed?: boolean
    supported?: boolean
    status?: string
  } | null
  const message = typeof result?.message === "string" ? result.message : ""
  const localized = testMessages[message]
  const translated = /[\u4e00-\u9fff]/.test(message) ? safeMessage(message) : localized
  if (result?.supported === false) return testMessages["Plugin does not export a connection test"]
  if (
    result?.success === false ||
    result?.ok === false ||
    result?.passed === false ||
    ["failed", "error"].includes(result?.status ?? "")
  )
    return translated ?? testMessages["Connection test failed"]
  if (result?.job) return "设置已保存，正在更新个人工作空间。"
  if (result?.ok === true || result?.success === true || result?.passed === true)
    return translated ?? testMessages["Connection test passed"]
  return translated ?? "操作状态已返回，请根据实际结果核验。"
}
