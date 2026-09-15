import { createSignal, For, Show } from "solid-js"
import { api, list, patch, post, remove } from "../api"
import { Button, Empty, ErrorLine, Field, Icon, JobNote, Modal, Spinner, Toggle } from "../components"
import { useConsole } from "../context"
import { connectionBody, connectionDraft, connectionMethods, connectionTestPaths } from "../connections"
import type { ConnectionAliases, Plugin, ServiceConnection } from "../types"

export default function Connections(props: { items: ServiceConnection[]; onRefresh: () => Promise<void> }) {
  const app = useConsole()
  const [editing, setEditing] = createSignal<{ existing?: ServiceConnection }>()
  const [draft, setDraft] = createSignal(connectionDraft())
  const [paths, setPaths] = createSignal("/health")
  const [error, setError] = createSignal("")
  const [busy, setBusy] = createSignal(false)
  const [test, setTest] = createSignal<ServiceConnection>()
  const [method, setMethod] = createSignal("GET")
  const [testPath, setTestPath] = createSignal("")
  const [result, setResult] = createSignal<unknown>()
  function edit(existing?: ServiceConnection) {
    setDraft(connectionDraft(existing))
    setPaths((existing?.allowed_paths ?? ["/health"]).join("\n"))
    setError("")
    setEditing({ existing })
  }
  function closeEditor() {
    if (busy()) return
    setEditing(undefined)
    setDraft(connectionDraft())
    setError("")
  }
  async function save(event: SubmitEvent) {
    event.preventDefault()
    setBusy(true)
    setError("")
    try {
      const body = connectionBody({ ...draft(), allowed_paths: paths().split(/\r?\n/) }, editing()?.existing)
      const existing = editing()?.existing
      if (existing) await patch("/admin/connections/" + existing.id, body)
      else await post("/admin/connections", body)
      setEditing(undefined)
      setDraft(connectionDraft())
      app.notify("服务连接已保存。已安装此服务插件的空间将按配置更新流程生效。")
      await props.onRefresh()
    } catch (error) {
      setError((error as Error).message)
    } finally {
      setBusy(false)
    }
  }
  async function toggle(item: ServiceConnection, enabled: boolean) {
    setBusy(true)
    try {
      await patch("/admin/connections/" + item.id, { enabled })
      app.notify("连接状态已保存，相关空间将更新配置。")
      await props.onRefresh()
    } catch (error) {
      app.notify((error as Error).message, "error")
    } finally {
      setBusy(false)
    }
  }
  async function deleteConnection(item: ServiceConnection) {
    if (!window.confirm("确定删除“" + item.name + "”吗？仍被插件绑定的连接不能删除，请先调整绑定。")) return
    setBusy(true)
    try {
      await remove("/admin/connections/" + item.id)
      await props.onRefresh()
      app.notify("服务连接已删除。")
    } catch (error) {
      app.notify((error as Error).message, "error")
    } finally {
      setBusy(false)
    }
  }
  function openTest(item: ServiceConnection) {
    setTest(item)
    setMethod("GET")
    setTestPath(connectionTestPaths(item)[0] ?? "")
    setResult(undefined)
    setError("")
  }
  async function runTest(event: SubmitEvent) {
    event.preventDefault()
    setBusy(true)
    setResult(undefined)
    setError("")
    try {
      setResult(await post("/admin/connections/" + test()!.id + "/test", { method: method(), path: testPath() }))
    } catch (error) {
      setError((error as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <>
      <div class="info-strip">
        <Icon name="shield" size={18} />
        <span>配置插件可访问的服务与请求范围，再到“插件发布”按版本绑定。公共凭据由平台保管，不向普通用户展示。</span>
      </div>
      <div class="section-toolbar">
        <span class="muted small">{props.items.length} 个服务连接</span>
        <Button variant="primary" icon="plus" onClick={() => edit()}>
          添加服务连接
        </Button>
      </div>
      <div class="card-grid">
        <For
          each={props.items}
          fallback={<Empty icon="plugin" title="尚未配置服务连接" text="先添加内网服务，再为插件选择对应的连接。" />}
        >
          {(item) => (
            <article class="resource-card connection-card">
              <div class="resource-head">
                <span class="resource-icon blue">
                  <Icon name="plugin" />
                </span>
                <Toggle
                  checked={!!item.enabled}
                  disabled={busy()}
                  label={item.enabled ? "已启用" : "已停用"}
                  onChange={(enabled) => void toggle(item, enabled)}
                />
              </div>
              <h3>{item.name}</h3>
              <p class="connection-address">{item.base_url}</p>
              <div class="resource-meta">
                <span>
                  {item.auth_type === "none"
                    ? "无需凭据"
                    : item.secret_configured
                      ? "访问凭据已配置"
                      : "待填写访问凭据"}
                </span>
                <span>配置版本 {item.revision}</span>
              </div>
              <div class="connection-summary">
                <span>{item.allowed_methods.join(" · ")}</span>
                <span>{item.allowed_paths.length} 条允许路径</span>
              </div>
              <div class="resource-actions">
                <Button onClick={() => edit(item)}>编辑配置</Button>
                <Button variant="ghost" disabled={busy() || !item.enabled} onClick={() => openTest(item)}>
                  连接测试
                </Button>
                <button
                  class="icon-button"
                  aria-label={"删除连接 " + item.name}
                  disabled={busy()}
                  onClick={() => void deleteConnection(item)}
                >
                  <Icon name="trash" size={16} />
                </button>
              </div>
            </article>
          )}
        </For>
      </div>
      <Show when={editing()}>
        <Modal
          title={editing()?.existing ? "编辑服务连接" : "添加服务连接"}
          text="保存后为指定插件绑定；只更新受影响用户的空间。"
          onClose={closeEditor}
          wide
        >
          <form onSubmit={save}>
            <ErrorLine message={error()} />
            <Field label="服务名称" required>
              <input
                required
                maxlength={100}
                value={draft().name}
                onInput={(event) => setDraft({ ...draft(), name: event.currentTarget.value })}
                placeholder="例如：资料查询服务"
              />
            </Field>
            <Field label="服务地址" required hint="填写由平台维护的固定地址。不要包含访问凭据或查询参数。">
              <input
                type="url"
                required
                value={draft().base_url}
                onInput={(event) => setDraft({ ...draft(), base_url: event.currentTarget.value })}
                placeholder="https://service.example.internal"
              />
            </Field>
            <div class="form-grid">
              <Field label="鉴权方式">
                <select
                  value={draft().auth_type}
                  onChange={(event) =>
                    setDraft({
                      ...draft(),
                      auth_type: event.currentTarget.value as ServiceConnection["auth_type"],
                      secret: "",
                    })
                  }
                >
                  <option value="none">无需鉴权</option>
                  <option value="bearer">Bearer 访问令牌</option>
                  <option value="api_key">请求头 API Key</option>
                </select>
              </Field>
              <Show when={draft().auth_type === "api_key"}>
                <Field label="凭据请求头" required>
                  <input
                    required
                    value={draft().header_name}
                    onInput={(event) => setDraft({ ...draft(), header_name: event.currentTarget.value })}
                    placeholder="X-API-Key"
                  />
                </Field>
              </Show>
            </div>
            <Show when={draft().auth_type !== "none"}>
              <Field
                label="访问凭据"
                hint={
                  editing()?.existing?.secret_configured && editing()?.existing?.auth_type === draft().auth_type
                    ? "已配置。留空保留当前凭据，填写后替换。"
                    : "凭据加密保存，保存后不再显示明文。"
                }
              >
                <input
                  type="password"
                  autocomplete="new-password"
                  value={draft().secret}
                  onInput={(event) => setDraft({ ...draft(), secret: event.currentTarget.value })}
                />
              </Field>
            </Show>
            <fieldset class="connection-methods">
              <legend>允许的请求方法</legend>
              <div>
                <For each={connectionMethods}>
                  {(method) => (
                    <label>
                      <input
                        type="checkbox"
                        checked={draft().allowed_methods.includes(method)}
                        onChange={(event) =>
                          setDraft({
                            ...draft(),
                            allowed_methods: event.currentTarget.checked
                              ? [...draft().allowed_methods, method]
                              : draft().allowed_methods.filter((value) => value !== method),
                          })
                        }
                      />
                      {method}
                    </label>
                  )}
                </For>
              </div>
            </fieldset>
            <Field
              label="允许的请求路径"
              required
              hint="每行一条，以 / 开头。默认精确匹配，末尾 /* 表示允许该目录下的子路径。"
            >
              <textarea
                required
                rows={4}
                value={paths()}
                onInput={(event) => setPaths(event.currentTarget.value)}
                placeholder={"/health\n/records"}
              />
            </Field>
            <div class="form-grid">
              <Field label="请求超时（秒）">
                <input
                  type="number"
                  required
                  min={1}
                  max={60}
                  step={1}
                  value={draft().timeout_seconds}
                  onInput={(event) => setDraft({ ...draft(), timeout_seconds: event.currentTarget.valueAsNumber })}
                />
              </Field>
              <Field label="最大响应（KiB）">
                <input
                  type="number"
                  required
                  min={1}
                  max={10240}
                  step={1}
                  value={draft().max_response_bytes / 1024}
                  onInput={(event) =>
                    setDraft({ ...draft(), max_response_bytes: Math.round(event.currentTarget.valueAsNumber * 1024) })
                  }
                />
              </Field>
            </div>
            <div class="modal-actions between">
              <Toggle
                checked={draft().enabled}
                onChange={(enabled) => setDraft({ ...draft(), enabled })}
                label="启用此连接"
              />
              <div>
                <Button type="button" disabled={busy()} onClick={closeEditor}>
                  取消
                </Button>
                <Button type="submit" variant="primary" busy={busy()}>
                  保存连接
                </Button>
              </div>
            </div>
          </form>
        </Modal>
      </Show>
      <Show when={test()}>
        {(item) => (
          <Modal
            title={"测试连接 · " + item().name}
            text="测试仅检查已允许的读取路径。需要业务参数或写操作的服务，请使用插件自身的测试功能。"
            onClose={() => {
              if (!busy()) {
                setTest(undefined)
                setError("")
              }
            }}
          >
            <form onSubmit={runTest}>
              <ErrorLine message={error()} />
              <Show
                when={item().allowed_methods.some((value) => value === "GET")}
                fallback={<div class="notice">此连接没有开放 GET 读取方法，请通过已绑定插件进行测试。</div>}
              >
                <Field label="测试方法">
                  <select value={method()} onChange={(event) => setMethod(event.currentTarget.value)}>
                    <For each={item().allowed_methods.filter((value) => value === "GET")}>
                      {(value) => <option value={value}>{value}</option>}
                    </For>
                  </select>
                </Field>
                <Field label="测试路径" required hint="输入明确的读取路径；平台仍会校验它是否处于允许范围。">
                  <input
                    required
                    value={testPath()}
                    onInput={(event) => setTestPath(event.currentTarget.value)}
                    placeholder="/health"
                  />
                </Field>
              </Show>
              <Show when={result() !== undefined}>
                <JobNote value={result()} />
              </Show>
              <div class="modal-actions">
                <Button type="button" disabled={busy()} onClick={() => setTest(undefined)}>
                  关闭
                </Button>
                <Button
                  type="submit"
                  variant="primary"
                  busy={busy()}
                  disabled={!testPath() || !item().allowed_methods.some((value) => value === "GET")}
                >
                  开始测试
                </Button>
              </div>
            </form>
          </Modal>
        )}
      </Show>
    </>
  )
}

export function PluginConnections(props: {
  plugin: Plugin
  version: string
  onClose: () => void
  onSaved: () => Promise<void>
}) {
  const app = useConsole()
  const [loading, setLoading] = createSignal(true)
  const [loaded, setLoaded] = createSignal(false)
  const [error, setError] = createSignal("")
  const [busy, setBusy] = createSignal(false)
  const [items, setItems] = createSignal<ServiceConnection[]>([])
  const [aliases, setAliases] = createSignal<ConnectionAliases>({})
  const [bindings, setBindings] = createSignal<Record<string, string>>({})
  const endpoint = "/admin/plugins/" + props.plugin.id + "/" + encodeURIComponent(props.version) + "/connections"
  async function load() {
    setLoading(true)
    setError("")
    try {
      const result = await Promise.all([
        list<ServiceConnection>("/admin/connections"),
        api<{ bindings: Record<string, string>; aliases: ConnectionAliases }>(endpoint),
      ])
      setItems(result[0])
      setBindings(result[1].bindings)
      setAliases(result[1].aliases)
      setLoaded(true)
    } catch (error) {
      setError((error as Error).message)
    } finally {
      setLoading(false)
    }
  }
  void load()
  async function save(event: SubmitEvent) {
    event.preventDefault()
    setBusy(true)
    setError("")
    try {
      await api(endpoint, {
        method: "PUT",
        body: JSON.stringify({ bindings: Object.fromEntries(Object.entries(bindings()).filter(([, value]) => value)) }),
      })
      app.notify("服务绑定已保存，相关用户空间将更新配置。")
      await props.onSaved()
      props.onClose()
    } catch (error) {
      setError((error as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <Modal
      title={"服务绑定 · " + props.plugin.name}
      text={"插件版本 " + props.version + "。服务连接由超级管理员维护，普通用户只配置自己的使用参数。"}
      onClose={() => {
        if (!busy()) props.onClose()
      }}
    >
      <ErrorLine message={error()} />
      <Show
        when={!loading()}
        fallback={
          <div class="loading">
            <Spinner />
          </div>
        }
      >
        <Show when={loaded()} fallback={<Button onClick={load}>重新加载</Button>}>
          <form onSubmit={save}>
            <For each={Object.entries(aliases())} fallback={<div class="notice">此插件版本无需平台服务连接。</div>}>
              {([alias, declaration]) => (
                <Field label={declaration.description || alias} hint={"插件连接标识：" + alias}>
                  <select
                    value={bindings()[alias] ?? ""}
                    onChange={(event) => setBindings({ ...bindings(), [alias]: event.currentTarget.value })}
                  >
                    <option value="">暂不绑定（此插件将待配置）</option>
                    <For each={items()}>
                      {(connection) => (
                        <option value={connection.id}>
                          {connection.name}
                          {connection.enabled ? "" : "（已停用）"}
                        </option>
                      )}
                    </For>
                  </select>
                </Field>
              )}
            </For>
            <Show when={Object.keys(aliases()).length && !items().length}>
              <div class="notice">请先到“服务连接”添加服务，再返回此处完成绑定。</div>
            </Show>
            <div class="modal-actions">
              <Button type="button" onClick={props.onClose} disabled={busy()}>
                关闭
              </Button>
              <Show when={Object.keys(aliases()).length}>
                <Button type="submit" variant="primary" busy={busy()}>
                  保存并应用
                </Button>
              </Show>
            </div>
          </form>
        </Show>
      </Show>
    </Modal>
  )
}
