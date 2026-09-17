import { describe, expect, test } from "bun:test"
import { canSend, runtimeNotice } from "../src/runtime-view"

describe("runtime status does not bypass admission", () => {
  test("on-demand admission and administrator pause are authoritative", () => {
    expect(canSend({ status: "ready", gate_policy: "open", runtime_mode: "on_demand", ready: false })).toBe(false)
    expect(runtimeNotice({ status: "unprovisioned", runtime_mode: "on_demand", manual_stop_reason: "none", allowed_actions: ["start"] })).toContain("启动助手")
    expect(runtimeNotice({ status: "paused", runtime_mode: "on_demand", manual_stop_reason: "admin" })).toContain("管理员")
  })
  test("ready is insufficient until the gate has acknowledged opening", () => {
    expect(canSend({ status: "ready", gate_policy: "open_pending" })).toBe(false)
    expect(canSend({ status: "ready", gate_policy: "open" })).toBe(true)
    expect(canSend({ status: "ready", gate_policy: "open", security_blocked: true })).toBe(false)
    expect(canSend({ status: "ready", gate_policy: "open", recovery_required: true })).toBe(false)
  })
  test("pending configuration leaves the old version usable", () => {
    const runtime = { status: "ready", gate_policy: "open", revision: 10, desired: 11 }
    expect(canSend(runtime)).toBe(true)
    expect(runtimeNotice(runtime)).toContain("已生效的配置")
  })
  test("unknown cancellation is never labelled completed", () => {
    expect(runtimeNotice({ status: "draining", security_blocked: true })).toContain("停止待确认")
    expect(runtimeNotice({ status: "draining", phase: "awaiting_action" })).toContain("超级管理员")
  })
})
