import { createEffect, createSignal, For, Show } from "solid-js"
import { api, list, post } from "../api"
import { Button, Empty, ErrorLine, Field, Icon, JobNote, Modal, PageHead, Spinner, Status, Toggle } from "../components"
import { useConsole } from "../context"
import type { Json, Plugin, Schema } from "../types"
import { SchemaFields, supportsSchema } from "../SchemaFields"
function defaults(schema: Schema, value: Record<string, Json> = {}): Record<string, Json> {
  const result = Object.fromEntries(Object.entries(value).filter(([key]) => key in (schema.properties ?? {})))
  for (const [key, field] of Object.entries(schema.properties ?? {})) {
    if (result[key] === undefined && field.default !== undefined) result[key] = field.default
    if (field.type === "object" && field.properties)
      result[key] = defaults(
        field,
        result[key] && typeof result[key] === "object" && !Array.isArray(result[key])
          ? (result[key] as Record<string, Json>)
          : {},
      )
  }
  return result
}
function cleanConfig(schema: Schema, value: Record<string, Json>): Record<string, Json> {
  return Object.fromEntries(
    Object.entries(value).flatMap(([key, value]) => {
      const field = schema.properties?.[key]
      if ((field?.writeOnly || field?.format === "password") && value === "") return []
      if (field?.type === "object" && value && typeof value === "object" && !Array.isArray(value))
        return [[key, cleanConfig(field, value)]]
      return [[key, value]]
    }),
  )
}
function schemaFor(item: Plugin, version: string): Schema {
  return item.schemas?.[version] ?? item.config_schema ?? { type: "object", properties: {} }
}
export default function Plugins() {
  const app = useConsole()
  const locked = () => ["updating", "applying"].includes(app.user().runtime?.status ?? "")
  const [items, setItems] = createSignal<Plugin[]>([])
  const [loading, setLoading] = createSignal(true)
  const [error, setError] = createSignal("")
  const [selected, setSelected] = createSignal<Plugin>()
  const [version, setVersion] = createSignal("")
  const [config, setConfig] = createSignal<Record<string, Json>>({})
  const [enabled, setEnabled] = createSignal(true)
  const [saving, setSaving] = createSignal(false)
  const [working, setWorking] = createSignal("")
  const [test, setTest] = createSignal<unknown>()
  async function refresh() {
    try {
      setItems(await list<Plugin>("/plugins"))
      setError("")
    } catch (error) {
      setError((error as Error).message)
    } finally {
      setLoading(false)
    }
  }
  createEffect(() => {
    app.changed()
    void refresh()
  })
  function configure(item: Plugin) {
    const version =
      item.installed?.version && (!item.schemas || item.schemas[item.installed.version])
        ? item.installed.version
        : item.version
    setSelected(item)
    setVersion(version)
    setConfig(defaults(schemaFor(item, version), item.installed?.config ?? {}))
    setEnabled(item.installed?.enabled ?? true)
    setError("")
  }
  async function save(event: SubmitEvent) {
    event.preventDefault()
    if (locked()) {
      setError("配置正在更新，完成后可提交修改。")
      return
    }
    setSaving(true)
    try {
      const cleaned = cleanConfig(schemaFor(selected()!, version()), config())
      await api("/plugins/" + selected()!.id, {
        method: "PUT",
        body: JSON.stringify({ version: version(), enabled: enabled(), config: cleaned }),
      })
      setSelected(undefined)
      app.notify("插件配置已保存，正在应用到你的工作空间。")
      await refresh()
    } catch (error) {
      setError((error as Error).message)
    } finally {
      setSaving(false)
    }
  }
  async function action(item: Plugin, operation: "toggle" | "test" | "rollback") {
    if (locked()) {
      app.notify("配置正在更新，完成后可提交修改。", "error")
      return
    }
    setWorking(item.id)
    try {
      if (operation === "toggle") {
        await api("/plugins/" + item.id, {
          method: "PUT",
          body: JSON.stringify({
            version: item.installed?.version ?? item.version,
            enabled: !item.installed?.enabled,
            config: item.installed?.config ?? {},
          }),
        })
      } else {
        const result = await post("/plugins/" + item.id + "/" + operation)
        if (operation === "test") setTest(result)
        else app.notify("已提交插件版本回退。")
      }
      await refresh()
    } catch (error) {
      app.notify((error as Error).message, "error")
    } finally {
      setWorking("")
    }
  }
  return (
    <div class="content-page">
      <PageHead eyebrow="已发布的业务能力" title="业务插件" text="选择管理员授权的插件，按需配置并接入你的分析流程。" />
      <ErrorLine message={error()} />
      <Show when={locked()}>
        <div class="notice">配置正在更新，当前可以查看或编辑草稿，完成后再提交修改。</div>
      </Show>
      <div class="info-strip">
        <Icon name="shield" size={18} />
        <span>这里仅展示已发布并授权给你的插件。配置和凭据在你的个人空间内生效。</span>
      </div>
      <Show
        when={!loading()}
        fallback={
          <div class="loading">
            <Spinner />
          </div>
        }
      >
        <div class="card-grid">
          <For
            each={items()}
            fallback={
              <Empty icon="plugin" title="暂无授权插件" text="管理员发布并授权业务插件后，你可以在这里安装和配置。" />
            }
          >
            {(item) => (
              <article class="resource-card">
                <div class="resource-head">
                  <span class="resource-icon blue">
                    <Icon name="plugin" />
                  </span>
                  <Show when={item.installed} fallback={<span class="pill">可安装</span>}>
                    <Toggle
                      checked={item.installed?.enabled}
                      disabled={locked() || working() === item.id}
                      onChange={() => void action(item, "toggle")}
                      label={item.installed?.enabled ? "已启用" : "已停用"}
                    />
                  </Show>
                </div>
                <h3>{item.name}</h3>
                <p>{item.description || "为分析工作提供可复用的业务能力。"}</p>
                <div class="resource-meta">
                  <span>版本 {item.installed?.version ?? item.version}</span>
                  <Show when={item.installed?.state}>
                    <Status value={item.installed?.state} />
                  </Show>
                </div>
                <Show when={item.installed?.state === "unavailable"}>
                  <div class="notice">此版本已停用，请在配置中选择可用版本。</div>
                </Show>
                <div class="resource-actions">
                  <Button icon={item.installed ? "settings" : "plus"} onClick={() => configure(item)}>
                    {item.installed ? "配置" : "安装插件"}
                  </Button>
                  <Show when={item.installed}>
                    <Button
                      variant="ghost"
                      disabled={locked()}
                      busy={working() === item.id}
                      onClick={() => void action(item, "test")}
                    >
                      连接测试
                    </Button>
                    <button
                      class="icon-button"
                      title="回到上一个版本"
                      aria-label={"回滚 " + item.name}
                      disabled={locked() || working() === item.id}
                      onClick={() => void action(item, "rollback")}
                    >
                      <Icon name="refresh" size={16} />
                    </button>
                  </Show>
                </div>
              </article>
            )}
          </For>
        </div>
      </Show>
      <Show when={selected()}>
        {(item) => (
          <Modal
            title={(item().installed ? "配置 · " : "安装 · ") + item().name}
            text={item().description}
            onClose={() => {
              if (!saving()) setSelected(undefined)
            }}
          >
            <form onSubmit={save}>
              <ErrorLine message={error()} />
              <Show when={locked()}>
                <div class="notice">配置正在更新，当前可以查看或编辑草稿，完成后再提交修改。</div>
              </Show>
              <Field label="插件版本">
                <select
                  value={version()}
                  onChange={(event) => {
                    const value = event.currentTarget.value
                    setVersion(value)
                    setConfig(defaults(schemaFor(item(), value), config()))
                  }}
                >
                  <For
                    each={[
                      ...new Set([
                        item().version,
                        ...(item().versions ?? []).map((value) => (typeof value === "string" ? value : value.version)),
                        ...(item().installed && (!item().schemas || item().schemas?.[item().installed!.version])
                          ? [item().installed!.version]
                          : []),
                      ]),
                    ]}
                  >
                    {(value) => <option value={value}>{value}</option>}
                  </For>
                </select>
              </Field>
              <Show
                when={Object.keys(schemaFor(item(), version()).properties ?? {}).length}
                fallback={<div class="notice">这个插件无需额外配置，安装后即可启用。</div>}
              >
                <SchemaFields
                  schema={schemaFor(item(), version())}
                  value={config()}
                  onChange={setConfig}
                  configured={item().installed?.credentials_configured}
                />
              </Show>
              <div class="modal-actions between">
                <Toggle checked={enabled()} onChange={setEnabled} label="应用后启用" />
                <div>
                  <Button type="button" onClick={() => setSelected(undefined)} disabled={saving()}>
                    取消
                  </Button>
                  <Button
                    type="submit"
                    variant="primary"
                    busy={saving()}
                    disabled={locked() || !supportsSchema(schemaFor(item(), version()))}
                  >
                    保存并应用
                  </Button>
                </div>
              </div>
            </form>
          </Modal>
        )}
      </Show>
      <Show when={test() !== undefined}>
        <Modal title="插件测试结果" onClose={() => setTest(undefined)}>
          <JobNote value={test()} />
          <div class="modal-actions">
            <Button onClick={() => setTest(undefined)}>关闭</Button>
          </div>
        </Modal>
      </Show>
    </div>
  )
}
