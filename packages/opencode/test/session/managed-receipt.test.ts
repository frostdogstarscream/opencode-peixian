import { test, expect } from "bun:test"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { ReceiptStore } from "../../src/session/managed-receipt"

test("durable admission deduplicates across restart without restarting unknown work", () => {
  const dir = mkdtempSync(join(tmpdir(), "receipt-"))
  const path = join(dir,"receipt.db")
  const id = "a".repeat(32)
  const payload = { parts: [{type:"text",text:"synthetic"}] }
  let store = new ReceiptStore(path,"boot-a")
  try {
    expect(store.admit(id,"ses_demo","msg_demo",payload)).toBe(true)
    expect(store.admit(id,"ses_demo","msg_demo",payload)).toBe(false)
    expect(() => store.admit(id,"ses_other","msg_demo",payload)).toThrow()
    expect(() => store.admit(id,"ses_demo","msg_demo",{})).toThrow()
    store.close()
    store = new ReceiptStore(path,"boot-b")
    expect(store.read(id)?.state).toBe("unknown")
    expect(store.admit(id,"ses_demo","msg_demo",payload)).toBe(false)
    store.finish(id)
    expect(store.read(id)?.state).toBe("unknown")
    const next = "b".repeat(32)
    expect(store.admit(next,"ses_demo","msg_next",payload)).toBe(true)
    store.finish(next)
    expect(store.read(next)?.state).toBe("finished")
  } finally {store.close();rmSync(dir,{recursive:true,force:true})}
})
