import { describe, expect, test } from "bun:test"
import {
  connectEvents,
  createChangeBus,
  parseChange,
  readEvents,
  reconnectDelay,
  retryAfter,
  type ServerEvent,
} from "../src/events"

function stream(text: string, width = 1) {
  const bytes = new TextEncoder().encode(text)
  let offset = 0
  return new ReadableStream<Uint8Array>({
    pull(controller) {
      if (offset >= bytes.length) {
        controller.close()
        return
      }
      controller.enqueue(bytes.slice(offset, (offset += width)))
    },
  })
}
const controller = () => new AbortController()

test("a failing open callback cancels the body before reconnect", async () => {
  let cancelled = false
  const abort = controller()
  await connectEvents({
    url: "/events", signal: abort.signal,
    fetcher: (async () => new Response(new ReadableStream<Uint8Array>({ cancel() { cancelled = true } }),
      { headers: { "Content-Type": "text/event-stream" } })) as typeof fetch,
    onOpen() { throw new Error("Synthetic render failure") },
    onEvent() {}, onDisconnected() {}, onUnauthorized() {},
    wait: async () => { expect(cancelled).toBe(true); abort.abort() },
  })
  expect(cancelled).toBe(true)
})

describe("real SSE byte streams", () => {
  test("decodes split Chinese UTF-8, CRLF, comments and multiline data", async () => {
    const received: ServerEvent[] = []
    const body = stream(
      ': heartbeat\r\nevent: change\r\ndata: {"type":"updated",\r\ndata: "resources":["messages"],"label":"中文"}\r\n\r\n',
    )
    await readEvents(body, controller().signal, (event) => received.push(event))
    expect(received).toEqual([
      { event: "change", data: '{"type":"updated",\n"resources":["messages"],"label":"中文"}' },
    ])
    expect(body.locked).toBe(false)
  })
  test("handles lone CR, LF and discards incomplete event at EOF", async () => {
    const received: ServerEvent[] = []
    await readEvents(
      stream("data: one\r\revent: change\ndata: two\n\ndata: incomplete"),
      controller().signal,
      (event) => received.push(event),
    )
    expect(received).toEqual([
      { event: "message", data: "one" },
      { event: "change", data: "two" },
    ])
  })
  test("aborting a pending read cancels body and releases reader", async () => {
    let cancelled = false
    const body = new ReadableStream<Uint8Array>({
      cancel() {
        cancelled = true
      },
    })
    const abort = controller()
    const reading = readEvents(body, abort.signal, () => {
      throw new Error("Unexpected event")
    })
    abort.abort()
    await reading
    expect(cancelled).toBe(true)
    expect(body.locked).toBe(false)
  })
  test("abort during dispatch prevents later events in same chunk", async () => {
    const abort = controller(),
      received: string[] = []
    await readEvents(stream("data: first\n\ndata: second\n\n", 1000), abort.signal, (event) => {
      received.push(event.data)
      abort.abort()
    })
    expect(received).toEqual(["first"])
  })
  test("oversized unfinished line is rejected and body unlocked", async () => {
    const body = stream("data:" + "x".repeat(262145), 280000)
    await expect(readEvents(body, controller().signal, () => {})).rejects.toThrow("receive limit")
    expect(body.locked).toBe(false)
  })
})

describe("bounded reconnect and authentication", () => {
  test("401 ends connection without retries or model request replay", async () => {
    const requests: RequestInit[] = []
    let expired = 0
    await connectEvents({
      url: "/events",
      signal: controller().signal,
      fetcher: (async (_url, options) => {
        requests.push(options!)
        return new Response(null, { status: 401 })
      }) as typeof fetch,
      onEvent: () => {},
      onOpen: () => {},
      onDisconnected: () => {
        throw new Error("Must not reconnect")
      },
      onUnauthorized: () => expired++,
    })
    expect(expired).toBe(1)
    expect(requests).toHaveLength(1)
    expect(requests[0]).toMatchObject({
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
    })
    expect(requests[0].body).toBeUndefined()
  })
  test("429 and 503 honor Retry-After, then exponential backoff", async () => {
    const waits: number[] = [],
      statuses = [429, 503, 500, 401]
    let request = 0
    await connectEvents({
      url: "/events",
      signal: controller().signal,
      fetcher: (async () => {
        const status = statuses[request++]
        return new Response(null, { status, headers: { "Retry-After": status === 429 ? "3" : "1" } })
      }) as typeof fetch,
      wait: async (delay) => {
        waits.push(delay)
      },
      random: () => 0,
      onEvent: () => {},
      onOpen: () => {},
      onDisconnected: () => {},
      onUnauthorized: () => {},
    })
    expect(waits).toEqual([3000, 2000, 4000])
    expect([0, 1, 2, 3, 4, 9].map((attempt) => reconnectDelay(attempt, () => 0))).toEqual([
      1000, 2000, 4000, 8000, 15000, 15000,
    ])
    expect(reconnectDelay(0, () => 0.5)).toBe(1125)
    expect(retryAfter("Wed, 01 Jan 2025 00:00:03 GMT", Date.parse("2025-01-01T00:00:00Z"))).toBe(3000)
    expect(retryAfter("invalid")).toBeUndefined()
  })
  test("reconnected stream delivers events and cancellation stops retries", async () => {
    const abort = controller(),
      received: string[] = []
    let opened = 0,
      requests = 0
    await connectEvents({
      url: "/events",
      signal: abort.signal,
      fetcher: (async () => {
        requests++
        if (requests === 1) throw new Error("offline")
        return new Response(stream('event: change\ndata: {"type":"updated"}\n\n'), {
          headers: { "Content-Type": "text/event-stream" },
        })
      }) as typeof fetch,
      wait: async () => {},
      onEvent: (event) => {
        received.push(event.data)
        abort.abort()
      },
      onOpen: () => opened++,
      onDisconnected: () => {},
      onUnauthorized: () => {},
    })
    expect(requests).toBe(2)
    expect(opened).toBe(1)
    expect(received).toEqual(['{"type":"updated"}'])
  })
})

describe("resource invalidation contract", () => {
  test("legacy updated only refreshes messages and sessions; arbitrary resources ignored", () => {
    expect(parseChange({ event: "change", data: '{"type":"updated"}' })).toEqual({
      resources: ["messages", "sessions"],
    })
    expect(
      parseChange({
        event: "change",
        data: '{"type":"updated","resources":["messages","models","/admin/users","messages"],"session_id":"ses_123"}',
      }),
    ).toEqual({ resources: ["messages", "models"], session_id: "ses_123" })
    expect(parseChange({ event: "change", data: '{"type":"connected"}' })).toBeUndefined()
    expect(parseChange({ event: "change", data: "broken" })).toBeUndefined()
    expect(parseChange({ event: "other", data: '{"type":"updated"}' })).toBeUndefined()
  })
  test("message storms never trigger catalogs; callback cleanup and deduplication", () => {
    const bus = createChangeBus()
    let messages = 0,
      catalogs = 0
    const remove = bus.subscribe("messages", () => messages++)
    bus.subscribe("models", () => catalogs++)
    for (let i = 0; i < 1000; i++) bus.publish({ resources: ["messages", "sessions"] })
    expect(messages).toBe(1000)
    expect(catalogs).toBe(0)
    remove()
    bus.publish({ resources: ["messages"] })
    expect(messages).toBe(1000)
    let shared = 0
    const callback = () => shared++
    bus.subscribe("files", callback)
    bus.subscribe("skills", callback)
    bus.publish({ resources: ["files", "skills"] })
    expect(shared).toBe(1)
  })
})
