type Clock = {
  now: () => number
  set: (callback: () => void, delay: number) => ReturnType<typeof setTimeout>
  clear: (timer: ReturnType<typeof setTimeout>) => void
}
const clock: Clock = {
  now: () => Date.now(),
  set: (callback, delay) => setTimeout(callback, delay),
  clear: (timer) => clearTimeout(timer),
}

// One request per resource at a time, with one coalesced trailing refresh.
export function createRefreshScheduler(
  load: (signal: AbortSignal) => Promise<void>,
  options: { interval?: () => number; onError?: (error: unknown) => void; clock?: Clock } = {},
) {
  const time = options.clock ?? clock
  const abort = new AbortController()
  let last = -Infinity,
    running = false,
    pending = false,
    disposed = false
  let timer: ReturnType<typeof setTimeout> | undefined
  let completion: { promise: Promise<void>; resolve: () => void } | undefined
  function schedule() {
    if (disposed || running || !pending) return
    if (timer !== undefined) time.clear(timer)
    timer = time.set(
      () => {
        timer = undefined
        void run()
      },
      Math.max(0, last + (options.interval?.() ?? 500) - time.now()),
    )
  }
  async function run() {
    if (disposed) return
    running = true
    pending = false
    last = time.now()
    const complete = completion
    completion = undefined
    try {
      await load(abort.signal)
    } catch (error) {
      if (!disposed) options.onError?.(error)
    } finally {
      running = false
      complete?.resolve()
      schedule()
    }
  }
  return {
    request() {
      if (disposed) return Promise.resolve()
      if (completion) {
        schedule()
        return completion.promise
      }
      pending = true
      let resolve!: () => void
      const promise = new Promise<void>((done) => {
        resolve = done
      })
      completion = { promise, resolve }
      schedule()
      return promise
    },
    dispose() {
      disposed = true
      abort.abort()
      if (timer !== undefined) time.clear(timer)
      completion?.resolve()
      completion = undefined
    },
  }
}

export function createResponseGuard<T>(current: () => T) {
  let generation = 0
  return {
    invalidate() {
      generation++
    },
    capture() {
      const value = current(),
        revision = generation
      return () => current() === value && generation === revision
    },
  }
}
