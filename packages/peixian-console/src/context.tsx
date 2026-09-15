import { createContext, useContext } from "solid-js"
import type { Accessor } from "solid-js"
import type { Capability, User } from "./types"
export type ConsoleContext = {
  user: Accessor<User>
  capabilities: Accessor<Capability[]>
  can: (capability: Capability) => boolean
  notify: (message: string, kind?: "success" | "error") => void
  refreshUser: () => Promise<void>
  changed: Accessor<number>
}
export const Context = createContext<ConsoleContext>()
export function useConsole() {
  const value = useContext(Context)
  if (!value) throw new Error("Console context is missing")
  return value
}
