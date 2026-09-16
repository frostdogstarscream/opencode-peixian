import { createEffect, createMemo, onCleanup } from "solid-js"
import { useConsole } from "./context"
import type { Resource } from "./events"
import { createRefreshScheduler } from "./refresh"

export function useResourceRefresh(names: Resource[], refresh: () => Promise<void>, visibleInterval = 30000) {
  const app = useConsole()
  const scheduler = createRefreshScheduler(
    async () => {
      await refresh()
    },
    {
      interval: () => (document.hidden ? 30000 : 500),
    },
  )
  const disposers = [...new Set([...names, "runtime" as const])].map((name) =>
    app.subscribe(name, () => {
      void scheduler.request()
    }),
  )
  const runtime = createMemo(() => app.user().runtime?.status)
  createEffect(() => {
    runtime()
    void scheduler.request()
  })
  const timer = setInterval(() => {
    if (!document.hidden) void scheduler.request()
  }, visibleInterval)
  onCleanup(() => {
    clearInterval(timer)
    disposers.forEach((dispose) => dispose())
    scheduler.dispose()
  })
  return scheduler.request
}
