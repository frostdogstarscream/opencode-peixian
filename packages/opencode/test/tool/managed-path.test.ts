import { afterEach, beforeEach, describe, expect, test } from "bun:test"
import fs from "fs/promises"
import os from "os"
import path from "path"
import { assertManagedPath } from "../../src/tool/managed-path"

let directory: string
let roots: string[]

beforeEach(async () => {
  directory = await fs.realpath(await fs.mkdtemp(path.join(os.tmpdir(), "peixian-files-")))
  roots = [path.join(directory, "workspace"), path.join(directory, "files")]
  await Promise.all(roots.map((root) => fs.mkdir(root)))
})

afterEach(async () => {
  await fs.rm(directory, { recursive: true, force: true })
})

describe("managed file realpath boundary", () => {
  test("allows roots, existing content and nested new output paths", async () => {
    for (const root of roots) {
      await fs.writeFile(path.join(root, "existing.txt"), "synthetic")
      await assertManagedPath(root, roots)
      await assertManagedPath(path.join(root, "existing.txt"), roots)
      await assertManagedPath(path.join(root, "new", "nested", "result.txt"), roots)
    }
  })

  test("rejects relative, NUL, sibling-prefix and normalized parent escape paths", async () => {
    for (const target of [
      "relative.txt",
      roots[0] + "\0",
      roots[0] + "-other/file",
      path.join(roots[0], "..", "private"),
    ]) {
      await expect(assertManagedPath(target, roots)).rejects.toThrow()
    }
  })

  test("rejects existing files and new outputs through an escaping directory link", async () => {
    const outside = path.join(directory, "private")
    await fs.mkdir(outside)
    await fs.writeFile(path.join(outside, "existing.txt"), "private")
    const link = path.join(roots[0], "link")
    await fs.symlink(outside, link, process.platform === "win32" ? "junction" : "dir")
    for (const tail of ["", "existing.txt", "new/deep/result.txt"]) {
      await expect(assertManagedPath(path.join(link, tail), roots)).rejects.toThrow("outside")
    }
    expect(await fs.readFile(path.join(outside, "existing.txt"), "utf8")).toBe("private")
  })

  test("allows links whose real destination remains in either allowed root", async () => {
    const target = path.join(roots[1], "existing")
    await fs.mkdir(target)
    await fs.writeFile(path.join(target, "source.txt"), "synthetic")
    const link = path.join(roots[0], "inputs")
    await fs.symlink(target, link, process.platform === "win32" ? "junction" : "dir")
    await assertManagedPath(path.join(link, "source.txt"), roots)
    await assertManagedPath(path.join(link, "new.txt"), roots)
  })

  test("rejects dangling directory links instead of treating them as a new parent", async () => {
    const missing = path.join(directory, "missing")
    const link = path.join(roots[0], "dangling")
    await fs.symlink(missing, link, process.platform === "win32" ? "junction" : "dir")
    await expect(assertManagedPath(path.join(link, "new.txt"), roots)).rejects.toThrow()
  })

  test("rejects a missing or symlinked allowed root", async () => {
    await fs.rmdir(roots[1])
    await expect(assertManagedPath(path.join(roots[0], "new.txt"), roots)).rejects.toThrow()
    await fs.symlink(roots[0], roots[1], process.platform === "win32" ? "junction" : "dir")
    await expect(assertManagedPath(path.join(roots[0], "new.txt"), roots)).rejects.toThrow("real directory")
  })
})
