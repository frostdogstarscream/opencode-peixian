import { createSignal, Show } from "solid-js"
import { post } from "./api"
import { Button, ErrorLine } from "./components"
import { useConsole } from "./context"

export default function RuntimeStatus() {
  const app = useConsole()
  const [pending, setPending] = createSignal(false)
  const [error, setError] = createSignal("")
  const runtime = () => app.user().runtime
  async function change(action: "start" | "stop") {
    if (pending()) return
    setPending(true)
    setError("")
    try {
      const state = runtime()
      const body = action === "start" ? {} : {
        expected_state_version: state?.state_version,
        ...(state?.job && ["provision", "resume"].includes(state.job.action) ? { start_job_id: state.job.id } : {}),
      }
      await post("/me/runtime/" + action, body)
      await app.refreshUser()
    } catch (error) {
      setError((error as Error).message)
      await app.refreshUser().catch(() => {})
    } finally {
      setPending(false)
    }
  }
  return <Show when={runtime()?.runtime_mode === "on_demand"}>
    <section class="runtime-banner runtime-controls" aria-label="我的助手" aria-live="polite">
      <div>
        <strong>我的助手</strong>
        <p>{runtime()?.ready ? "助手已就绪，可以开始对话。" : runtime()?.manual_stop_reason !== "none"
          ? "管理员已暂停助手，请联系管理员恢复。" : runtime()?.job
            ? "正在处理启停操作，输入内容已保留。" : "按需启动助手后即可对话和使用文件；技能和个人配置仍可编辑。"}</p>
        <ErrorLine message={error()} />
      </div>
      <Show when={runtime()?.allowed_actions?.includes("start")}>
        <Button disabled={pending()} onClick={() => void change("start")}>启动助手</Button>
      </Show>
      <Show when={runtime()?.allowed_actions?.includes("stop")}>
        <Button disabled={pending()} onClick={() => void change("stop")}>{runtime()?.job && ["provision", "resume"].includes(runtime()!.job!.action) ? "取消启动" : "停止助手"}</Button>
      </Show>
    </section>
  </Show>
}
