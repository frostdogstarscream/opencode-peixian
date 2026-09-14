import { afterEach, describe, expect } from "bun:test"
import path from "path"
import { Server } from "../../src/server/server"
import { Effect, Fiber } from "effect"
import { resetDatabase } from "../fixture/db"
import { disposeAllInstances, tmpdir } from "../fixture/fixture"
import { it } from "../lib/effect"
import { waitGlobalBusEvent } from "./global-bus"

function app() {
  return Server.Default().app
}

function waitDisposed(directory: string) {
  return waitGlobalBusEvent({
    message: "timed out waiting for instance disposal",
    predicate: (event) => event.payload.type === "server.instance.disposed" && event.directory === directory,
  })
}

const tmpdirEffect = (options: Parameters<typeof tmpdir>[0]) =>
  Effect.acquireRelease(
    Effect.promise(() => tmpdir(options)),
    (tmp) => Effect.promise(() => tmp[Symbol.asyncDispose]()),
  )

afterEach(async () => {
  await disposeAllInstances()
  await resetDatabase()
})

describe("config HttpApi", () => {
  it.live(
    "serves config update through the default server app",
    Effect.gen(function* () {
      const tmp = yield* tmpdirEffect({ config: { formatter: false, lsp: false } })
      const disposed = yield* waitDisposed(tmp.path).pipe(Effect.forkScoped({ startImmediately: true }))

      const response = yield* Effect.promise(() =>
        Promise.resolve(
          app().request("/config", {
            method: "PATCH",
            headers: {
              "content-type": "application/json",
              "x-opencode-directory": tmp.path,
            },
            body: JSON.stringify({ username: "patched-user", formatter: false, lsp: false }),
          }),
        ),
      )

      expect(response.status).toBe(200)
      expect(yield* Effect.promise(() => response.json())).toMatchObject({
        username: "patched-user",
        formatter: false,
        lsp: false,
      })
      yield* Fiber.join(disposed)
      expect(yield* Effect.promise(() => Bun.file(path.join(tmp.path, "config.json")).json())).toMatchObject({
        username: "patched-user",
        formatter: false,
        lsp: false,
      })
    }),
  )

  it.live(
    "serves config with active provider model status",
    Effect.gen(function* () {
      const tmp = yield* tmpdirEffect({
        config: {
          formatter: false,
          lsp: false,
          provider: {
            omniroute: {
              models: {
                "gpt-4o": {
                  status: "active",
                },
              },
            },
          },
        },
      })

      const response = yield* Effect.promise(() =>
        Promise.resolve(
          app().request("/config", {
            headers: {
              "x-opencode-directory": tmp.path,
            },
          }),
        ),
      )

      expect(response.status).toBe(200)
      expect(yield* Effect.promise(() => response.json())).toMatchObject({
        provider: {
          omniroute: {
            models: {
              "gpt-4o": {
                status: "active",
              },
            },
          },
        },
      })
    }),
  )
})

it.live("managed mode denies local and global config PATCH with declared 403 responses", () =>
  Effect.gen(function* () {
    const tmp = yield* tmpdirEffect({ config: { username: "original" } })
    yield* Effect.acquireRelease(
      Effect.sync(() => {
        const previous = process.env.PEIXIAN_MANAGED_ROOT
        process.env.PEIXIAN_MANAGED_ROOT = tmp.path
        return previous
      }),
      (previous) =>
        Effect.sync(() => {
          if (previous === undefined) delete process.env.PEIXIAN_MANAGED_ROOT
          else process.env.PEIXIAN_MANAGED_ROOT = previous
        }),
    )
    for (const endpoint of ["/config", "/global/config"]) {
      const response = yield* Effect.promise(() =>
        Promise.resolve(
          app().request(endpoint, {
            method: "PATCH",
            headers: { "content-type": "application/json", "x-opencode-directory": tmp.path },
            body: JSON.stringify({ username: "changed" }),
          }),
        ),
      )
      expect(response.status).toBe(403)
    }
    expect(yield* Effect.promise(() => Bun.file(path.join(tmp.path, "opencode.json")).json())).toMatchObject({
      username: "original",
    })
    expect(yield* Effect.promise(() => Bun.file(path.join(tmp.path, "config.json")).exists())).toBe(false)
  }),
)
