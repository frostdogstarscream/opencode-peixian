import { Database } from "bun:sqlite"
import { mkdirSync } from "node:fs"
import { join } from "node:path"
import { createHash } from "node:crypto"

type Receipt = { id: string; session_id: string; message_id: string; digest: string; state: string; boot_id: string }

/** Durable admission only: an ambiguous or old-boot receipt never restarts provider work. */
export class ReceiptStore {
  private db: Database
  constructor(path: string, readonly bootID: string) {
    this.db = new Database(path, { create: true })
    this.db.exec("PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL; PRAGMA busy_timeout=1000")
    this.db.exec("CREATE TABLE IF NOT EXISTS admissions(id TEXT PRIMARY KEY,session_id TEXT NOT NULL,message_id TEXT NOT NULL UNIQUE,digest TEXT NOT NULL,state TEXT NOT NULL,boot_id TEXT NOT NULL)")
  }
  admit(id: string, sessionID: string, messageID: string, payload: unknown) {
    if (!/^[a-f0-9]{32}$/.test(id) || !/^msg_[a-zA-Z0-9]+$/.test(messageID)) throw new Error("Invalid managed receipt identity")
    const digest = createHash("sha256").update(JSON.stringify(payload)).digest("hex")
    return this.db.transaction(() => {
      const previous = this.db.query<Receipt, [string]>("SELECT * FROM admissions WHERE id=?").get(id)
      if (previous) {
        if (previous.digest !== digest || previous.session_id !== sessionID || previous.message_id !== messageID) throw new Error("Managed receipt conflict")
        return false
      }
      this.db.query("INSERT INTO admissions VALUES(?,?,?,?,?,?)").run(id, sessionID, messageID, digest, "accepted", this.bootID)
      return true
    })()
  }
  finish(id: string) {
    this.db.query("UPDATE admissions SET state='finished' WHERE id=? AND boot_id=?").run(id, this.bootID)
  }
  read(id: string) {
    const row = this.db.query<Receipt, [string]>("SELECT * FROM admissions WHERE id=?").get(id)
    if (!row) return null
    return { id: row.id, session_id: row.session_id, message_id: row.message_id,
      state: row.state === "accepted" && row.boot_id !== this.bootID ? "unknown" : row.state }
  }
  close() { this.db.close() }
}

let store: ReceiptStore | undefined
export function receipts() {
  if (store) return store
  if (!process.env.PEIXIAN_MANAGED_ROOT) throw new Error("Managed mode required")
  const root = join(process.env.XDG_STATE_HOME ?? join(process.env.HOME!, ".local/state"), "peixian")
  mkdirSync(root, { recursive: true, mode: 0o700 })
  return store = new ReceiptStore(join(root, "admissions.sqlite3"), crypto.randomUUID())
}
