import fs from "fs/promises"
import path from "path"

function contains(root: string, target: string) {
  const relative = path.relative(root, target)
  return relative === "" || (!path.isAbsolute(relative) && relative !== ".." && !relative.startsWith(`..${path.sep}`))
}

export async function assertManagedPath(target: string, roots: readonly string[]) {
  if (!path.isAbsolute(target) || target.includes("\0")) throw new Error("Invalid managed file path")
  const full = path.resolve(target)
  const logical = roots.map((root) => path.resolve(root))
  if (!logical.some((root) => contains(root, full))) throw new Error("Managed file path is outside allowed roots")
  const real = await Promise.all(
    logical.map(async (root) => {
      const info = await fs.lstat(root)
      if (!info.isDirectory() || info.isSymbolicLink()) throw new Error("Managed file root must be a real directory")
      return fs.realpath(root)
    }),
  )
  let cursor = full
  while (true) {
    const info = await fs.lstat(cursor).catch((error: NodeJS.ErrnoException) => {
      if (error.code === "ENOENT") return undefined
      throw error
    })
    if (info) {
      const resolved = await fs.realpath(cursor)
      if (!real.some((root) => contains(root, resolved))) {
        throw new Error("Managed file path resolves outside allowed roots")
      }
      return
    }
    const parent = path.dirname(cursor)
    if (parent === cursor) throw new Error("Managed file parent is unavailable")
    cursor = parent
  }
}
