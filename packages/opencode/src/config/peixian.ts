export * as ConfigPeixian from "./peixian"

import fs from "fs/promises"
import path from "path"
import { fileURLToPath, pathToFileURL } from "url"

export function enabled() {
  return process.env.PEIXIAN_MANAGED_ROOT !== undefined
}

export function root() {
  const value = process.env.PEIXIAN_MANAGED_ROOT
  if (value === undefined) return undefined
  if (!value || !path.isAbsolute(value) || value.includes("\0")) {
    throw new Error("PEIXIAN_MANAGED_ROOT must be an absolute directory")
  }
  return path.resolve(value)
}

export function assertWritable() {
  if (enabled()) throw new Error("Managed OpenCode configuration is read-only")
}

function contains(root: string, target: string) {
  const relative = path.relative(root, target)
  return relative === "" || (!path.isAbsolute(relative) && relative !== ".." && !relative.startsWith(`..${path.sep}`))
}

export async function resolveInside(root: string, target: string) {
  if (!contains(root, path.resolve(target))) throw new Error("Managed path is outside the published root")
  const resolved = await fs.realpath(target)
  if (!contains(root, resolved)) throw new Error("Managed path resolves outside the published root")
  return resolved
}

export async function plugin(root: string, spec: string) {
  if (!spec.startsWith("file://")) throw new Error("Managed plugins must use explicit file:// URLs")
  const url = new URL(spec)
  if (url.search || url.hash || url.username || url.password) throw new Error("Invalid managed plugin URL")
  const file = await resolveInside(root, fileURLToPath(url))
  if (!(await fs.stat(file)).isFile() || !/\.(?:[cm]?js|[cm]?ts)$/.test(file)) {
    throw new Error("Managed plugins must reference a JavaScript or TypeScript file")
  }
  return pathToFileURL(file).href
}

export async function read() {
  const requested = root()
  if (requested === undefined) throw new Error("Managed root is not configured")
  const directory = await fs.realpath(requested)
  if (!(await fs.stat(directory)).isDirectory()) throw new Error("Managed root is not a directory")
  const file = await resolveInside(directory, path.join(directory, "opencode.json"))
  const text = await fs.readFile(file, "utf8")
  // Published configuration is complete. Expansion would reopen environment and filesystem sources.
  if (/\{(?:env|file):/.test(text)) throw new Error("Managed configuration cannot contain variable substitutions")
  return { root: directory, file, text }
}

export async function skillFiles() {
  const config = await read()
  const base = path.join(config.root, "skills")
  const exists = await fs.lstat(base).catch((error: NodeJS.ErrnoException) => {
    if (error.code === "ENOENT") return undefined
    throw error
  })
  if (!exists) return []
  if (exists.isSymbolicLink()) throw new Error("Managed skills directory must not be a symlink")
  const directory = await resolveInside(config.root, base)
  if (!(await fs.stat(directory)).isDirectory()) throw new Error("Managed skills path is not a directory")
  const visited = new Set<string>()
  const files: string[] = []
  const scan = async (current: string): Promise<void> => {
    const resolved = await resolveInside(directory, current)
    if (visited.has(resolved)) return
    visited.add(resolved)
    for (const item of await fs.readdir(resolved, { withFileTypes: true })) {
      const file = await resolveInside(directory, path.join(resolved, item.name))
      const stat = await fs.stat(file)
      if (stat.isDirectory()) await scan(file)
      if (stat.isFile() && item.name === "SKILL.md") files.push(file)
    }
  }
  await scan(directory)
  return files.toSorted()
}
