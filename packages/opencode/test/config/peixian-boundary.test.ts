import { afterEach, beforeEach, describe, expect, test } from "bun:test"
import fs from "fs/promises"
import os from "os"
import path from "path"
import { pathToFileURL } from "url"
import { ConfigPeixian } from "../../src/config/peixian"

let directory: string
let previous: string | undefined

beforeEach(async () => {
  previous = process.env.PEIXIAN_MANAGED_ROOT
  directory = await fs.realpath(await fs.mkdtemp(path.join(os.tmpdir(), "peixian-boundary-")))
  process.env.PEIXIAN_MANAGED_ROOT = path.join(directory, "published")
  await fs.mkdir(process.env.PEIXIAN_MANAGED_ROOT)
  await fs.writeFile(path.join(process.env.PEIXIAN_MANAGED_ROOT, "opencode.json"), "{}")
})

afterEach(async () => {
  if (previous === undefined) delete process.env.PEIXIAN_MANAGED_ROOT
  else process.env.PEIXIAN_MANAGED_ROOT = previous
  await fs.rm(directory, { force: true, recursive: true })
})

describe("managed publication filesystem boundary", () => {
  test("reads only the published config without modifying it", async () => {
    const loaded = await ConfigPeixian.read()
    expect(loaded.text).toBe("{}")
    expect(await fs.readdir(loaded.root)).toEqual(["opencode.json"])
    expect(() => ConfigPeixian.assertWritable()).toThrow("read-only")
  })

  test("unset mode retains normal writes; empty and relative roots fail closed", async () => {
    delete process.env.PEIXIAN_MANAGED_ROOT
    expect(ConfigPeixian.enabled()).toBe(false)
    expect(ConfigPeixian.root()).toBeUndefined()
    expect(() => ConfigPeixian.assertWritable()).not.toThrow()
    for (const value of ["", ".", "relative/path", "\0"]) {
      process.env.PEIXIAN_MANAGED_ROOT = value
      await expect(ConfigPeixian.read()).rejects.toThrow()
    }
  })

  test("missing config never falls back to another directory", async () => {
    const loaded = await ConfigPeixian.read()
    await fs.unlink(loaded.file)
    await fs.writeFile(path.join(directory, "opencode.json"), '{"username":"outside"}')
    await expect(ConfigPeixian.read()).rejects.toThrow()
  })

  test("variable substitution cannot reopen environment or file sources", async () => {
    for (const value of ["{env:PEIXIAN_TEST_TOKEN}", "{file:../private}"]) {
      await fs.writeFile(path.join(ConfigPeixian.root()!, "opencode.json"), JSON.stringify({ username: value }))
      await expect(ConfigPeixian.read()).rejects.toThrow("substitutions")
    }
  })

  test("allows only explicit file URLs to existing code inside the root", async () => {
    const loaded = await ConfigPeixian.read()
    const file = path.join(loaded.root, "approved.mjs")
    await fs.writeFile(file, "export default async () => ({})")
    expect(await ConfigPeixian.plugin(loaded.root, pathToFileURL(file).href)).toBe(pathToFileURL(file).href)
    for (const spec of [
      "example-plugin@1",
      "./approved.mjs",
      file,
      "https://example.invalid/plugin.js",
      pathToFileURL(file).href + "?x",
    ]) {
      await expect(ConfigPeixian.plugin(loaded.root, spec)).rejects.toThrow()
    }
    await expect(
      ConfigPeixian.plugin(loaded.root, pathToFileURL(path.join(loaded.root, "missing.js")).href),
    ).rejects.toThrow()
    await expect(ConfigPeixian.plugin(loaded.root, pathToFileURL(loaded.file).href)).rejects.toThrow("JavaScript")
  })

  test("rejects sibling-prefix paths and symlinked plugin directories", async () => {
    const loaded = await ConfigPeixian.read()
    const outside = path.join(directory, "published-other")
    await fs.mkdir(outside)
    await fs.writeFile(path.join(outside, "plugin.js"), "export default async () => ({})")
    await expect(
      ConfigPeixian.plugin(loaded.root, pathToFileURL(path.join(outside, "plugin.js")).href),
    ).rejects.toThrow("outside")
    await fs.symlink(outside, path.join(loaded.root, "escape"), process.platform === "win32" ? "junction" : "dir")
    await expect(
      ConfigPeixian.plugin(loaded.root, pathToFileURL(path.join(loaded.root, "escape/plugin.js")).href),
    ).rejects.toThrow("outside")
  })

  test("skills include only published SKILL.md files", async () => {
    const loaded = await ConfigPeixian.read()
    await fs.mkdir(path.join(loaded.root, "skills/approved"), { recursive: true })
    const file = path.join(loaded.root, "skills/approved/SKILL.md")
    await fs.writeFile(file, "---\nname: approved\ndescription: approved\n---\nRead me")
    await fs.mkdir(path.join(loaded.root, "plugins"), { recursive: true })
    await fs.writeFile(path.join(loaded.root, "plugins/SKILL.md"), "ignored")
    expect(await ConfigPeixian.skillFiles()).toEqual([file])
  })

  test("rejects skill symlinks outside skills and outside the publication", async () => {
    const loaded = await ConfigPeixian.read()
    await fs.mkdir(path.join(loaded.root, "skills"))
    const outside = path.join(directory, "external")
    await fs.mkdir(outside)
    await fs.writeFile(path.join(outside, "SKILL.md"), "outside")
    await fs.symlink(
      outside,
      path.join(loaded.root, "skills/escape"),
      process.platform === "win32" ? "junction" : "dir",
    )
    await expect(ConfigPeixian.skillFiles()).rejects.toThrow("outside")
  })
})
