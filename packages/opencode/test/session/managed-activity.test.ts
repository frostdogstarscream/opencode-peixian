import { describe, expect, test } from "bun:test"
import { Registry } from "../../src/session/managed-activity"
import { ManagedActivity } from "../../src/session/managed-activity"
import { Deferred, Effect, Layer, Scope } from "effect"
import { testEffect } from "../lib/effect"

const it = testEffect(Layer.empty)

describe("managed runtime activity metadata", () => {
  test("tracks acceptance before a native busy signal and retains its terminal receipt", () => {
    const registry = new Registry()
    const id = registry.begin("session-synthetic", "a".repeat(32))
    expect(registry.snapshot().entries).toEqual([{ id, session_id: "session-synthetic", state: "running" }])
    registry.finish(id)
    expect(registry.snapshot().activity_sequence).toBe(2)
    registry.finish(id)
    expect(registry.snapshot().activity_sequence).toBe(2)
    expect(registry.snapshot().entries[0].state).toBe("finished")
    expect(() => registry.begin("session-synthetic", id)).toThrow()
  })

  test("a process restart has a distinct boot and cannot claim old activity receipts", () => {
    const first = new Registry()
    first.begin("session-synthetic")
    const second = new Registry()
    expect(second.boot_id).not.toBe(first.boot_id)
    expect(second.snapshot().entries).toEqual([])
  })

  test("bounded terminal retention never evicts active work", () => {
    const registry = new Registry()
    const active = registry.begin("session-active")
    for (let i = 0; i < 5000; i++) registry.finish(registry.begin("session-finished"))
    expect(registry.snapshot().entries.length).toBeLessThanOrEqual(4096)
    expect(registry.snapshot().entries.find((entry) => entry.id === active)?.state).toBe("running")
  })

  it.effect("registers a fork before execution and cancels native preparation and background work", () =>
    Effect.scoped(
      Effect.gen(function* () {
        const previous = process.env.PEIXIAN_MANAGED_ROOT
        process.env.PEIXIAN_MANAGED_ROOT = "/synthetic-managed"
        yield* Effect.addFinalizer(() =>
          Effect.sync(() => {
            if (previous === undefined) delete process.env.PEIXIAN_MANAGED_ROOT
            else process.env.PEIXIAN_MANAGED_ROOT = previous
          }),
        )
        const scope = yield* Scope.Scope
        const started = yield* Deferred.make<void>()
        const first = "b".repeat(32)
        const second = "c".repeat(32)
        yield* ManagedActivity.fork(
          Deferred.succeed(started, undefined).pipe(Effect.andThen(Effect.never)),
          "session-cancel",
          scope,
          first,
        )
        yield* ManagedActivity.fork(Effect.never, "session-cancel", scope, second)
        expect(
          ManagedActivity.snapshot()
            .entries.filter((entry) => [first, second].includes(entry.id))
            .every((entry) => entry.state === "running"),
        ).toBe(true)
        yield* Deferred.await(started)
        yield* ManagedActivity.cancel("session-cancel")
        expect(
          ManagedActivity.snapshot()
            .entries.filter((entry) => [first, second].includes(entry.id))
            .every((entry) => entry.state === "finished"),
        ).toBe(true)
      }),
    ),
  )
})
