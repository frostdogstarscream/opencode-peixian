import type { User } from "./types"

type Runtime = User["runtime"]

export function canSend(runtime: Runtime) {
  if (runtime?.runtime_mode === "on_demand" && runtime.ready !== true) return false
  return !!runtime && runtime.status === "ready" && runtime.gate_policy === "open"
    && !runtime.security_blocked && !runtime.recovery_required
}

export function runtimeNotice(runtime: Runtime): string {
  if (!runtime) return "正在准备你的工作空间，完成后即可开始对话。"
  if (runtime.runtime_mode === "on_demand" && !runtime.ready) {
    if (runtime.manual_stop_reason && runtime.manual_stop_reason !== "none") return "管理员已暂停助手，请联系管理员恢复。"
    if (runtime.allowed_actions?.includes("start")) return "点击“启动助手”后开始对话，输入内容将保持保留。"
    if (runtime.status === "provisioning") return "正在启动助手，完成核对后即可发送消息。"
  }
  if (runtime.security_blocked)
    return runtime.cancellation_confirmed
      ? "新调用已阻断，相关活动已停止。正在核对最新授权配置。"
      : "新调用已阻断，部分任务停止待确认。输入内容和当前对话已保留。"
  if (runtime.recovery_required) return "工作空间正在核对恢复状态，暂不接受新任务。输入内容已保留。"
  if (runtime.phase === "awaiting_action") return "当前任务仍未结束，更新正在等待超级管理员处理。你仍可查看或停止已有对话。"
  if (runtime.status === "draining") return "正在等待当前任务结束后更新配置，暂不接收新任务。你可以完成确认或停止已有对话。"
  if (["updating", "applying"].includes(runtime.status)) return "正在应用配置，完成检查后将自动恢复。输入内容已保留。"
  if (runtime.status === "paused") return "工作空间已暂停，请联系超级管理员恢复。"
  if (runtime.status === "failed") return "工作空间需要恢复处理，请联系超级管理员。历史数据保持保留。"
  if (!canSend(runtime)) return "正在检查工作空间入口，完成后即可发送消息。"
  if ((runtime.desired ?? 0) > (runtime.revision ?? 0)) return "配置已保存，等待生效；当前对话继续使用已生效的配置。"
  return ""
}
