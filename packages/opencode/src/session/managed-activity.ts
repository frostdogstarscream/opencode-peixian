import { Effect, Fiber, Scope } from "effect"

export type Entry = { id: string; session_id: string; state: "running" | "finished" }

/** Metadata only. The managed gateway correlates admission before prompt_async forks. */
export class Registry {
  readonly boot_id = crypto.randomUUID()
  private readonly entries = new Map<string, Entry>()
  private sequence = 0

  begin(sessionID: string, identity?: string) {
    const id = identity && /^[a-f0-9]{32}$/.test(identity) ? identity : crypto.randomUUID().replaceAll("-", "")
    if (this.entries.has(id)) throw new Error("Managed activity identity was already admitted")
    this.entries.set(id, { id, session_id: sessionID, state: "running" })
    this.sequence++
    return id
  }

  finish(id: string) {
    const entry = this.entries.get(id)
    if (entry?.state === "running") {
      entry.state = "finished"
      this.sequence++
    }
    // Keep terminal metadata long enough for the gateway's normal polling gap.
    if (this.entries.size > 4096) {
      for (const [key, value] of this.entries) {
        if (this.entries.size <= 2048) break
        if (value.state === "finished") this.entries.delete(key)
      }
    }
  }

  snapshot() {
    return { boot_id: this.boot_id, activity_sequence: this.sequence, entries: Array.from(this.entries.values(), (entry) => ({ ...entry })) }
  }

  running(id: string) {
    return this.entries.get(id)?.state === "running"
  }
}

const registry = new Registry()
const children = new Map<string, { sessionID: string; fiber: Fiber.Fiber<unknown, unknown> }>()
export const enabled = () => Boolean(process.env.PEIXIAN_MANAGED_ROOT)
export const snapshot = () => registry.snapshot()

export function track<A, E, R>(work: Effect.Effect<A, E, R>, sessionID: string, identity?: string) {
  if (!enabled()) return work
  return Effect.scoped(
    Effect.gen(function* () {
      const scope = yield* Scope.Scope
      const fiber = yield* fork(work, sessionID, scope, identity)
      return yield* Fiber.join(fiber)
    }),
  )
}

export function fork<A, E, R>(
  work: Effect.Effect<A, E, R>,
  sessionID: string,
  scope: Scope.Scope,
  identity?: string,
  startImmediately = false,
  onExit?: () => void,
) {
  if (!enabled()) return work.pipe(Effect.forkIn(scope, { startImmediately }))
  return Effect.uninterruptibleMask((restore) =>
    Effect.gen(function* () {
      const id = registry.begin(sessionID, identity)
      const fiber = yield* restore(work).pipe(Effect.forkIn(scope, { startImmediately }))
      children.set(id, { sessionID, fiber })
      // An exit observer also runs when cancellation wins before the child starts.
      fiber.addObserver(() => {
        registry.finish(id)
        children.delete(id)
        onExit?.()
      })
      return fiber
    }),
  )
}

export function acknowledge(sessionID: string, identity?: string) {
  if (enabled()) registry.finish(registry.begin(sessionID, identity))
}

export const cancel = (sessionID: string) =>
  Effect.forEach(
    Array.from(children.values()).filter((child) => child.sessionID === sessionID),
    (child) => Fiber.interrupt(child.fiber),
    { concurrency: "unbounded", discard: true },
  )

export * as ManagedActivity from "./managed-activity"
