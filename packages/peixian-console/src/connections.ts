import type { Plugin, ServiceConnection } from "./types"

export const connectionMethods = ["GET", "POST", "PUT", "PATCH", "DELETE"] as const
export type ConnectionDraft = Omit<ServiceConnection, "id" | "revision" | "secret_configured"> & { secret: string }

export function connectionDraft(value?: ServiceConnection): ConnectionDraft {
  return {
    name: value?.name ?? "",
    base_url: value?.base_url ?? "",
    auth_type: value?.auth_type ?? "none",
    header_name: value?.header_name ?? "X-API-Key",
    secret: "",
    allowed_methods: value?.allowed_methods ?? ["GET"],
    allowed_paths: value?.allowed_paths ?? ["/health"],
    timeout_seconds: value?.timeout_seconds ?? 15,
    max_response_bytes: value?.max_response_bytes ?? 1048576,
    enabled: value?.enabled ?? true,
  }
}

export function connectionBody(draft: ConnectionDraft, existing?: ServiceConnection) {
  if (!draft.name.trim()) throw new Error("请填写服务名称。")
  const address = URL.parse(draft.base_url.trim())
  if (
    !address ||
    !["http:", "https:"].includes(address.protocol) ||
    address.username ||
    address.password ||
    address.search ||
    address.hash
  )
    throw new Error("请填写有效的 HTTP 或 HTTPS 服务地址，不包含账号、查询参数或片段。")
  if (
    !draft.allowed_methods.length ||
    draft.allowed_methods.some((method) => !connectionMethods.includes(method as (typeof connectionMethods)[number]))
  )
    throw new Error("请至少选择一种允许的请求方法。")
  const paths = [...new Set(draft.allowed_paths.map((path) => path.trim()).filter(Boolean))]
  if (
    !paths.length ||
    paths.some(
      (path) =>
        !path.startsWith("/") ||
        path.includes("//") ||
        /[%?#\\\s]/.test(path) ||
        path.split("/").some((segment) => [".", ".."].includes(segment)) ||
        (path.includes("*") && (!path.endsWith("/*") || path.slice(0, -1).includes("*"))),
    )
  )
    throw new Error("请填写以 / 开头的允许路径，每行一条，不包含查询参数。")
  if (
    draft.auth_type !== "none" &&
    !draft.secret &&
    !(
      existing?.secret_configured &&
      existing.auth_type === draft.auth_type &&
      (draft.auth_type !== "api_key" || existing.header_name === draft.header_name.trim())
    )
  )
    throw new Error("请填写访问凭据。")
  if (!Number.isInteger(draft.timeout_seconds) || draft.timeout_seconds < 1 || draft.timeout_seconds > 60)
    throw new Error("请求超时应为 1 至 60 秒。")
  if (
    !Number.isInteger(draft.max_response_bytes) ||
    draft.max_response_bytes < 1024 ||
    draft.max_response_bytes > 10485760
  )
    throw new Error("最大响应应为 1 至 10240 KiB。")
  return {
    name: draft.name.trim(),
    base_url: draft.base_url.trim(),
    auth_type: draft.auth_type,
    header_name: draft.auth_type === "api_key" ? draft.header_name.trim() : "",
    ...(draft.auth_type !== "none" && draft.secret ? { secret: draft.secret } : {}),
    allowed_methods: [...new Set(draft.allowed_methods)],
    allowed_paths: paths,
    timeout_seconds: draft.timeout_seconds,
    max_response_bytes: draft.max_response_bytes,
    enabled: draft.enabled,
  }
}

export function connectionTestPaths(value: ServiceConnection) {
  return value.allowed_paths.filter((path) => !path.includes("*"))
}

export function pluginConnectionReady(item: Plugin, version: string) {
  if (item.connection_status?.[version]) return item.connection_status[version].ready
  return item.installed?.version !== version || item.installed.state !== "unconfigured"
}
