import { createSignal, onCleanup, onMount, Show } from "solid-js"
import { api, post } from "../api"
import { Button, ErrorLine, Modal } from "../components"

type State = { mode: "normal" | "frozen" | "repair_only"; state_version: number; recovery_required: number; security_pending: number; capacity_healthy: boolean }
const labels = { normal: "正常服务", frozen: "维护中", repair_only: "仅恢复处理" }

export default function RuntimeMaintenance() {
  const [state, setState] = createSignal<State>()
  const [busy, setBusy] = createSignal(false)
  const [error, setError] = createSignal("")
  const [choice, setChoice] = createSignal<State["mode"]>()
  let disposed = false
  const controller = new AbortController()
  async function refresh() {
    try {
      const result = await api<State>("/admin/maintenance", { signal: controller.signal })
      if (!disposed) setState(result)
    } catch (failure) {
      if (!disposed) setError((failure as Error).message)
    }
  }
  onMount(() => {
    void refresh()
    const timer = setInterval(() => { if (!document.hidden && !busy()) void refresh() }, 15000)
    onCleanup(() => clearInterval(timer))
  })
  onCleanup(() => { disposed = true; controller.abort() })
  async function change() {
    const current = state(), mode = choice()
    if (!current || !mode || busy()) return
    setBusy(true)
    setError("")
    try {
      await post("/admin/maintenance", { mode, state_version: current.state_version })
      setChoice(undefined)
      await refresh()
    } catch (failure) { setError((failure as Error).message) }
    finally { setBusy(false) }
  }
  return <section class="runtime-banner" aria-label="平台维护状态">
    <div>
      <strong>平台状态：{state() ? labels[state()!.mode] : "正在读取"}</strong>
      <Show when={state()}><p>待恢复空间 {state()!.recovery_required} 个，停止待确认 {state()!.security_pending} 个。</p></Show>
      <ErrorLine message={error()} />
    </div>
    <Button variant="ghost" disabled={busy() || !state()} onClick={() => setChoice(state()?.mode === "normal" ? "frozen" : "normal")}>
      {state()?.mode === "normal" ? "进入维护" : "恢复正常服务"}
    </Button>
    <Button variant="ghost" disabled={busy() || !state() || state()?.mode === "repair_only"} onClick={() => setChoice("repair_only")}>仅允许恢复处理</Button>
    <Show when={choice()}><Modal title={"切换为" + labels[choice()!]} onClose={() => !busy() && setChoice(undefined)}>
      <p>维护期间暂停新任务和配置提交，已有任务按当前策略处理。恢复正常服务前，平台会核对未完成的恢复事项。</p>
      <Button disabled={busy()} onClick={() => void change()}>确认切换</Button>
    </Modal></Show>
  </section>
}
