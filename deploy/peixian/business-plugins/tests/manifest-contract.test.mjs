import assert from "node:assert/strict"
import { readdir, readFile } from "node:fs/promises"
import test from "node:test"
import { dirname, join } from "node:path"
import { fileURLToPath, pathToFileURL } from "node:url"


const root = dirname(dirname(fileURLToPath(import.meta.url)))
const directories = (await readdir(root, { withFileTypes: true })).filter((item) => item.isDirectory() && item.name.startsWith("peixian-"))

for (const directory of directories) {
  test(`${directory.name} manifest tools match the runtime export`, async () => {
    const path = join(root, directory.name)
    const manifest = JSON.parse(await readFile(join(path, "manifest.json"), "utf8"))
    const module = await import(pathToFileURL(join(path, manifest.entry)).href)
    const loaded = await module.default({}, { max_items: 50 }, { connections: { request() { throw new Error("not called during registration") } } })
    assert.deepEqual(Object.keys(loaded.tool).sort(), [...manifest.tools].sort())
  })
}
