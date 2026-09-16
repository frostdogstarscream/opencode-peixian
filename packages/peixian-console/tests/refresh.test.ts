import { describe, expect, test } from "bun:test"
import { createRefreshScheduler, createResponseGuard } from "../src/refresh"

function fakeClock() {
  let now = 0,
    identity = 0
  const timers = new Map<number, { at: number; callback: () => void }>()
  return {
    now: () => now,
    set(callback: () => void, delay: number) {
      const id = ++identity
      timers.set(id, { at: now + delay, callback })
      return id as unknown as ReturnType<typeof setTimeout>
    },
    clear(id: ReturnType<typeof setTimeout>) {
      timers.delete(id as unknown as number)
    },
    advance(milliseconds: number) {
      const target = now + milliseconds
      while (true) {
        const entry = [...timers.entries()].sort((a, b) => a[1].at - b[1].at).find(([, value]) => value.at <= target)
        if (!entry) break
        now = entry[1].at
        timers.delete(entry[0])
        entry[1].callback()
      }
      now = target
    },
    pending: () => timers.size,
  }
}
const ticks = async () => {
  for (let i = 0; i < 8; i++) await Promise.resolve()
}

test("default clock preserves the browser timer receiver", async () => {
  const original = globalThis.setTimeout
  globalThis.setTimeout = function(this: unknown, ...args: Parameters<typeof setTimeout>) {
    if (this !== undefined && this !== globalThis) throw new TypeError("Illegal invocation")
    return original(...args)
  } as typeof setTimeout
  const refresh = createRefreshScheduler(async () => {})
  try {
    await refresh.request()
  } finally {
    refresh.dispose()
    globalThis.setTimeout = original
  }
})

describe("one-flight refresh scheduler", () => {
  test("1000 invalidations coalesce, run at most every 500 ms, and keep one trailing refresh", async () => {
    const clock = fakeClock(),
      starts: number[] = [],
      finish: (() => void)[] = []
    const refresh = createRefreshScheduler(
      () => {
        starts.push(clock.now())
        return new Promise((resolve) => finish.push(resolve))
      },
      { clock },
    )
    const first = refresh.request()
    for (let i = 0; i < 1000; i++) expect(refresh.request()).toBe(first)
    clock.advance(0)
    const trailing = refresh.request()
    for (let i = 0; i < 1000; i++) expect(refresh.request()).toBe(trailing)
    clock.advance(100)
    finish.shift()!()
    await ticks()
    await first
    clock.advance(399)
    expect(starts).toEqual([0])
    clock.advance(1)
    expect(starts).toEqual([0, 500])
    finish.shift()!()
    await ticks()
    await trailing
    clock.advance(10000)
    expect(starts).toEqual([0, 500])
    expect(clock.pending()).toBe(0)
    refresh.dispose()
  })
  test("returning to a visible tab expedites a queued hidden refresh", async () => {
    const clock = fakeClock(),
      starts: number[] = []
    let hidden = true
    const refresh = createRefreshScheduler(
      async () => {
        starts.push(clock.now())
      },
      { clock, interval: () => (hidden ? 15000 : 500) },
    )
    void refresh.request()
    clock.advance(0)
    await ticks()
    void refresh.request()
    clock.advance(3000)
    expect(starts).toEqual([0])
    hidden = false
    void refresh.request()
    clock.advance(0)
    await ticks()
    expect(starts).toEqual([0, 3000])
    refresh.dispose()
  })
  test("a slow request cannot overlap and still gets a trailing update", async () => {
    const clock = fakeClock(),
      finish: (() => void)[] = []
    let calls = 0
    const refresh = createRefreshScheduler(
      () => {
        calls++
        return new Promise((resolve) => finish.push(resolve))
      },
      { clock },
    )
    void refresh.request()
    clock.advance(0)
    void refresh.request()
    clock.advance(9000)
    expect(calls).toBe(1)
    finish.shift()!()
    await ticks()
    clock.advance(0)
    expect(calls).toBe(2)
    finish.shift()!()
    await ticks()
    refresh.dispose()
  })
  test("dispose aborts in-flight reads and removes a queued trailing request", async () => {
    const clock = fakeClock()
    let signal: AbortSignal | undefined,
      finish!: () => void,
      calls = 0
    const refresh = createRefreshScheduler(
      (value) => {
        calls++
        signal = value
        return new Promise((resolve) => (finish = resolve))
      },
      { clock },
    )
    void refresh.request()
    clock.advance(0)
    const trailing = refresh.request()
    refresh.dispose()
    await trailing
    expect(signal?.aborted).toBe(true)
    finish()
    await ticks()
    clock.advance(10000)
    expect(calls).toBe(1)
    expect(clock.pending()).toBe(0)
  })
  test("hidden interval slows down polling and a failed request remains retryable", async () => {
    const clock = fakeClock(),
      starts: number[] = [],
      errors: unknown[] = []
    let hidden = false
    const refresh = createRefreshScheduler(
      async () => {
        starts.push(clock.now())
        if (starts.length === 1) throw new Error("offline")
      },
      {
        clock,
        interval: () => (hidden ? 15000 : 500),
        onError: (error) => errors.push(error),
      },
    )
    void refresh.request()
    clock.advance(0)
    await ticks()
    hidden = true
    void refresh.request()
    clock.advance(14999)
    expect(starts).toEqual([0])
    clock.advance(1)
    await ticks()
    expect(starts).toEqual([0, 15000])
    expect(errors).toHaveLength(1)
    refresh.dispose()
  })
})

describe("session response ownership", () => {
  test("late A responses cannot overwrite B or a newly selected A", () => {
    let selected = "A"
    const guard = createResponseGuard(() => selected)
    const originalA = guard.capture()
    guard.invalidate()
    selected = "B"
    const activeB = guard.capture()
    expect(originalA()).toBe(false)
    expect(activeB()).toBe(true)
    guard.invalidate()
    selected = "A"
    expect(originalA()).toBe(false)
    expect(activeB()).toBe(false)
    expect(guard.capture()()).toBe(true)
    const beforeUnmount = guard.capture()
    guard.invalidate()
    expect(beforeUnmount()).toBe(false)
  })
})
