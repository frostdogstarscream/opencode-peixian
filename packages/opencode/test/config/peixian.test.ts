import { describe, expect } from "bun:test"
import { Effect, Exit, Layer } from "effect"
import { HttpClient } from "effect/unstable/http"
import { LayerNode } from "@opencode-ai/core/effect/layer-node"
import { AppNodeBuilder } from "@opencode-ai/core/effect/app-node-builder"
import { httpClient } from "@opencode-ai/core/effect/app-node-platform"
import { CrossSpawnSpawner } from "@opencode-ai/core/cross-spawn-spawner"
import { Global } from "@opencode-ai/core/global"
import { FSUtil } from "@opencode-ai/core/fs-util"
import { Npm } from "@opencode-ai/core/npm"
import { Config } from "../../src/config/config"
import { ConfigPaths } from "../../src/config/paths"
import { Auth } from "../../src/auth"
import { Account } from "../../src/account/account"
import { Skill } from "../../src/skill"
import { Plugin } from "../../src/plugin"
import { PluginLoader } from "../../src/plugin/loader"
import { Permission } from "../../src/permission"
import { RuntimeFlags } from "../../src/effect/runtime-flags"
import { TestInstance } from "../fixture/fixture"
import { testEffect } from "../lib/effect"
import path from "path"
import fs from "fs/promises"
import { pathToFileURL } from "url"

const it = testEffect(
  AppNodeBuilder.build(LayerNode.group([Config.node, Skill.node, Plugin.node, FSUtil.node, CrossSpawnSpawner.node]), [
    [Auth.node, Layer.mock(Auth.Service)({ all: () => Effect.die("managed mode read auth") })],
    [Account.node, Layer.mock(Account.Service)({ active: () => Effect.die("managed mode read account") })],
    [Npm.node, Layer.mock(Npm.Service)({ install: () => Effect.die("managed mode installed dependencies") })],
    [
      httpClient,
      Layer.succeed(
        HttpClient.HttpClient,
        HttpClient.make(() => Effect.die("managed mode fetched HTTP")),
      ),
    ],
    [RuntimeFlags.node, RuntimeFlags.layer({ pure: true, disableDefaultPlugins: false, disableExternalSkills: false })],
  ]),
)

const env = Effect.fnUntraced(function* (values: Record<string, string | undefined>) {
  yield* Effect.acquireRelease(
    Effect.sync(() => {
      const before = Object.fromEntries(Object.keys(values).map((key) => [key, process.env[key]]))
      for (const [key, value] of Object.entries(values)) {
        if (value === undefined) delete process.env[key]
        else process.env[key] = value
      }
      return before
    }),
    (before) =>
      Effect.sync(() => {
        for (const [key, value] of Object.entries(before)) {
          if (value === undefined) delete process.env[key]
          else process.env[key] = value
        }
      }),
  )
})

const publish = Effect.fnUntraced(function* (value: object = {}) {
  const test = yield* TestInstance
  const root = path.join(test.directory, "published")
  yield* Effect.promise(() => Bun.write(path.join(root, "opencode.json"), JSON.stringify(value)))
  yield* env({ PEIXIAN_MANAGED_ROOT: root })
  return root
})

const replaceFile = Effect.fnUntraced(function* (file: string, text: string) {
  yield* Effect.acquireRelease(
    Effect.promise(async () => {
      const before = await fs.readFile(file).catch((error: NodeJS.ErrnoException) => {
        if (error.code === "ENOENT") return undefined
        throw error
      })
      await Bun.write(file, text)
      return before
    }),
    (before) =>
      Effect.promise(async () => {
        if (before === undefined) await fs.unlink(file)
        else await fs.writeFile(file, before)
      }),
  )
})

describe("managed Config, Skill and Plugin services", () => {
  it.instance("loads only complete published config and never reads other config sources", () =>
    Effect.gen(function* () {
      const test = yield* TestInstance
      const config = yield* Config.Service
      const root = yield* publish({
        username: "published",
        permission: { "*": "deny" },
        plugin: [],
        enabled_providers: [],
      })
      const content = yield* Effect.promise(() => Bun.file(path.join(root, "opencode.json")).text())
      yield* replaceFile(path.join(test.directory, "opencode.json"), "{ broken project JSON")
      yield* replaceFile(path.join(Global.Path.config, "opencode.json"), "{ broken home JSON")
      yield* replaceFile(
        path.join(process.env.OPENCODE_TEST_MANAGED_CONFIG_DIR!, "opencode.json"),
        "{ broken system JSON",
      )
      yield* env({
        OPENCODE_CONFIG_CONTENT: "{ broken inline JSON",
        OPENCODE_CONFIG: path.join(test.directory, "missing-env-config.json"),
        OPENCODE_CONFIG_DIR: path.join(test.directory, "untrusted-config"),
        OPENCODE_PERMISSION: '{"*":"allow"}',
      })
      const actual = yield* config.get()
      expect(actual.username).toBe("published")
      expect(actual.permission).toEqual({ "*": "deny" })
      expect(yield* config.getGlobal()).toEqual(actual)
      expect(yield* config.directories()).toEqual([])
      expect(yield* ConfigPaths.directories(test.directory)).toEqual([])
      yield* config.waitForDependencies()
      expect(yield* Effect.promise(() => Bun.file(path.join(root, "opencode.json")).text())).toBe(content)
      expect(yield* Effect.promise(() => fs.readdir(root))).toEqual(["opencode.json"])
    }),
  )

  for (const text of [
    "{",
    '{"username":3}',
    '{"unknown_control":true}',
    '{"plugin":["npm-package@1"]}',
    '{"skills":{"urls":["https://example.invalid"]}}',
    '{"skills":{"paths":["../escape"]}}',
  ]) {
    it.instance("rejects invalid publication without global or local fallback: " + text.slice(0, 45), () =>
      Effect.gen(function* () {
        const root = yield* publish()
        yield* Effect.promise(() => Bun.write(path.join(root, "opencode.json"), text))
        const config = yield* Config.Service
        expect(Exit.isFailure(yield* Effect.exit(config.get()))).toBe(true)
        expect(Exit.isFailure(yield* Effect.exit(config.getGlobal()))).toBe(true)
      }),
    )
  }

  it.instance("rejects both native config mutation methods without writes", () =>
    Effect.gen(function* () {
      const root = yield* publish({ username: "published" })
      const config = yield* Config.Service
      expect(Exit.isFailure(yield* Effect.exit(config.update({ username: "changed" })))).toBe(true)
      expect(Exit.isFailure(yield* Effect.exit(config.updateGlobal({ username: "changed" })))).toBe(true)
      expect((yield* config.getGlobal()).username).toBe("published")
      expect(yield* Effect.promise(() => fs.readdir(root))).toEqual(["opencode.json"])
    }),
  )

  it.instance("loads only managed skills, excludes built-in and automatic home/project sources", () =>
    Effect.gen(function* () {
      const root = yield* publish()
      const test = yield* TestInstance
      const text = "---\nname: approved\ndescription: Published skill\n---\nApproved"
      yield* Effect.promise(() => Bun.write(path.join(root, "skills/approved/SKILL.md"), text))
      yield* Effect.promise(() =>
        Bun.write(
          path.join(test.directory, ".opencode/skills/untrusted/SKILL.md"),
          text.replaceAll("approved", "untrusted"),
        ),
      )
      yield* replaceFile(
        path.join(Global.Path.home, ".agents/skills/home/SKILL.md"),
        text.replaceAll("approved", "home"),
      )
      const skill = yield* Skill.Service
      expect((yield* skill.all()).map((item) => item.name)).toEqual(["approved"])
    }),
  )

  it.instance("invalid published Skill fails closed", () =>
    Effect.gen(function* () {
      const root = yield* publish()
      yield* Effect.promise(() => Bun.write(path.join(root, "skills/invalid/SKILL.md"), "missing frontmatter"))
      const skill = yield* Skill.Service
      expect(Exit.isFailure(yield* Effect.exit(skill.all()))).toBe(true)
    }),
  )

  it.instance("loads exact approved plugin despite pure mode, without default or auto plugins", () =>
    Effect.gen(function* () {
      const root = yield* publish()
      const file = path.join(root, "approved.js")
      yield* Effect.promise(() =>
        Bun.write(file, 'export default async () => ({ "config": config => { config.username = "plugin-loaded" } })'),
      )
      yield* Effect.promise(() =>
        Bun.write(path.join(root, "plugins/auto.js"), 'throw new Error("automatic plugin executed")'),
      )
      yield* Effect.promise(() =>
        Bun.write(path.join(root, "package.json"), '{"exports":{"opencode":"../outside.js"}}'),
      )
      yield* Effect.promise(() =>
        Bun.write(path.join(root, "opencode.json"), JSON.stringify({ plugin: [pathToFileURL(file).href] })),
      )
      const plugin = yield* Plugin.Service
      expect((yield* plugin.list()).length).toBe(1)
      const config = yield* Config.Service
      expect((yield* config.get()).username).toBe("plugin-loaded")
    }),
  )

  it.instance("managed loader rejects arbitrary npm declarations even when called directly", () =>
    Effect.gen(function* () {
      const root = yield* publish()
      expect(
        Exit.isFailure(
          yield* Effect.exit(
            Effect.promise(() =>
              PluginLoader.loadManaged([
                { spec: "unapproved-package", source: path.join(root, "opencode.json"), scope: "global" },
              ]),
            ),
          ),
        ),
      ).toBe(true)
    }),
  )
})

it.instance("preserves published permission order so file and skill tools remain visible", () =>
  Effect.gen(function* () {
    const permission = {
      "*": "deny",
      read: { "*": "allow", "../*": "deny", "../files/*": "allow", "/*": "deny" },
      edit: { "*": "allow", "../*": "deny", "/*": "deny" },
      glob: "allow",
      grep: "allow",
      skill: "allow",
      question: "allow",
      external_directory: { "*": "deny", "/files/*": "allow" },
      peixian_marker: "allow",
    } as const
    yield* publish({ permission })
    const config = yield* Config.Service
    const loaded = yield* config.get()
    expect(Object.keys(loaded.permission!)).toEqual(Object.keys(permission))
    expect(Object.keys((yield* config.getGlobal()).permission!)).toEqual(Object.keys(permission))
    const rules = Permission.fromConfig(loaded.permission!)
    const tools = [
      "read",
      "write",
      "edit",
      "glob",
      "grep",
      "skill",
      "question",
      "peixian_marker",
      "bash",
      "task",
      "webfetch",
      "websearch",
    ]
    expect([...Permission.disabled(tools, rules)]).toEqual(["bash", "task", "webfetch", "websearch"])
    expect(Permission.evaluate("read", "result.txt", rules).action).toBe("allow")
    expect(Permission.evaluate("edit", "result.txt", rules).action).toBe("allow")
    expect(Permission.evaluate("read", "../files/source.txt", rules).action).toBe("allow")
    expect(Permission.evaluate("read", "../home/private", rules).action).toBe("deny")
    expect(Permission.evaluate("edit", "../files/source.txt", rules).action).toBe("deny")
    expect(Permission.evaluate("read", "/managed/opencode.json", rules).action).toBe("deny")
  }),
)
