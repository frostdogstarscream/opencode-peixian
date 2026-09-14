import type { Auth } from "./types"
export const BASE = "/api/console/v1"
let csrf = ""
let unauthorized: (() => void) | undefined
export function setAuth(value?: Auth) {
  csrf = value?.csrf_token ?? ""
}
export function onUnauthorized(callback: () => void) {
  unauthorized = callback
}
export function safeMessage(value: unknown, fallback = "操作未完成，请稍后重试。"): string {
  const text = typeof value === "string" ? value : fallback
  return text
    .replace(/https?:\/\/[^\s"'<>]+/gi, "服务连接")
    .replace(/\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?\b/g, "服务连接")
    .replace(/\bsk-[A-Za-z0-9_-]{8,}\b/g, "已隐藏")
    .slice(0, 300)
}
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public code?: string,
  ) {
    super(message)
  }
}
export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json")
  if (options.method && !["GET", "HEAD"].includes(options.method.toUpperCase()) && csrf)
    headers.set("X-CSRF-Token", csrf)
  let response: Response
  try {
    response = await fetch(BASE + path, { ...options, headers, credentials: "same-origin" })
  } catch {
    throw new ApiError("连接暂时中断，请稍后重试。", 0, "network_error")
  }
  const content = response.status === 204 ? "" : await response.text()
  let data: Record<string, unknown> | null = null
  if (content) {
    try {
      data = JSON.parse(content)
    } catch {
      if (response.ok) return content as T
    }
  }
  if (!response.ok) {
    if (response.status === 401 && path !== "/auth/login") unauthorized?.()
    const fallback =
      response.status === 401
        ? "登录已失效，请重新登录。"
        : response.status === 403
          ? "你没有执行此操作的权限。"
          : response.status === 413
            ? "文件过大，请选择较小的文件。"
            : response.status === 422
              ? "请检查填写内容后重试。"
              : "操作未完成，请稍后重试。"
    throw new ApiError(
      safeMessage(data?.message, fallback),
      response.status,
      typeof data?.code === "string" ? data.code : undefined,
    )
  }
  return data as T
}
export function list<T>(path: string) {
  return api<{ items: T[] }>(path).then((data) => data.items ?? [])
}
export function post<T>(path: string, body: unknown = {}) {
  return api<T>(path, { method: "POST", body: JSON.stringify(body) })
}
export function patch<T>(path: string, body: unknown) {
  return api<T>(path, { method: "PATCH", body: JSON.stringify(body) })
}
export function remove(path: string) {
  return api(path, { method: "DELETE" })
}
export function download(path: string) {
  return BASE + path
}
