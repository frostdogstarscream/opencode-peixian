import { createSignal, For, Show } from "solid-js"
import { api, patch } from "../api"
import { Button, Empty, ErrorLine, Field, Icon, Modal, Toggle } from "../components"
import { useConsole } from "../context"
import type { ProviderEndpoint } from "../types"

export default function ProviderEndpoints(props: { items: ProviderEndpoint[]; onRefresh: () => Promise<void> }) {
  const app = useConsole()
  const [busy, setBusy] = createSignal(false)
  const [editing, setEditing] = createSignal<ProviderEndpoint>()
  const [path, setPath] = createSignal("")
  const [error, setError] = createSignal("")
  async function toggle(item: ProviderEndpoint, enabled: boolean) {
    const shared = props.items.filter((other) => other.plugin_id === item.plugin_id).length > 1
    if (
      !enabled &&
      !window.confirm(
        "停用后模型将看不到“" +
          item.name +
          "”这项查询" +
          (shared ? "（同一插件的其他查询方式也会一起停用）" : "") +
          "，确定停用吗？",
      )
    )
      return
    setBusy(true)
    try {
      await patch("/admin/plugins/" + item.plugin_id + "/" + encodeURIComponent(item.plugin_version), { enabled })
      app.notify(enabled ? "接口已启用，相关空间将更新配置。" : "接口已停用，相关空间将更新配置。")
      await props.onRefresh()
    } catch (failure) {
      app.notify((failure as Error).message, "error")
    } finally {
      setBusy(false)
    }
  }
  function edit(item: ProviderEndpoint) {
    setEditing(item)
    setPath(item.path)
    setError("")
  }
  async function save(value: string | null) {
    const item = editing()
    if (!item) return
    setBusy(true)
    setError("")
    try {
      await api("/admin/provider-endpoints", {
        method: "PUT",
        body: JSON.stringify({ key: item.key, path: value }),
      })
      setEditing(undefined)
      app.notify("请求路径已保存，相关空间将更新配置。")
      await props.onRefresh()
    } catch (failure) {
      setError((failure as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <>
      <div class="info-strip">
        <Icon name="shield" size={18} />
        <span>
          每项业务数据接口可单独启停、修改请求路径。地址和登录方式在“服务连接”里配置；字段对应关系由平台维护。
        </span>
      </div>
      <div class="card-grid">
        <For each={props.items} fallback={<Empty icon="plugin" title="暂无业务数据接口" />}>
          {(item) => (
            <article class="resource-card connection-card">
              <div class="resource-head">
                <span class="resource-icon blue">
                  <Icon name="plugin" />
                </span>
                <Toggle
                  checked={item.enabled}
                  disabled={busy() || !item.published}
                  label={!item.published ? "未发布" : item.enabled ? "已启用" : "已停用"}
                  onChange={(enabled) => void toggle(item, enabled)}
                />
              </div>
              <h3>{item.name}</h3>
              <p class="connection-address">
                {item.method} {item.path}
              </p>
              <div class="resource-meta">
                <span>{item.connection_name ?? "尚未绑定连接"}</span>
                <span>{item.path === item.default_path ? "默认路径" : "已改为自定义路径"}</span>
              </div>
              <div class="resource-actions">
                <Button disabled={busy() || !item.connection_id} onClick={() => edit(item)}>
                  修改路径
                </Button>
              </div>
            </article>
          )}
        </For>
      </div>
      <Show when={editing()}>
        {(item) => (
          <Modal
            title={"修改请求路径 · " + item().name}
            text={"默认路径 " + item().default_path + "。保存后只影响使用此接口的空间。"}
            onClose={() => {
              if (!busy()) setEditing(undefined)
            }}
          >
            <form
              onSubmit={(event) => {
                event.preventDefault()
                void save(path().trim())
              }}
            >
              <ErrorLine message={error()} />
              <Field
                label="请求路径"
                required
                hint={
                  item().default_path.endsWith("{person}")
                    ? "以 / 开头，最后一段保留 {person}，查询时替换为人员身份号码。"
                    : "以 / 开头，不包含查询参数。"
                }
              >
                <input
                  required
                  maxlength={1000}
                  value={path()}
                  onInput={(event) => setPath(event.currentTarget.value)}
                />
              </Field>
              <div class="modal-actions between">
                <Button
                  type="button"
                  variant="ghost"
                  disabled={busy() || item().path === item().default_path}
                  onClick={() => void save(null)}
                >
                  恢复默认
                </Button>
                <div>
                  <Button type="button" disabled={busy()} onClick={() => setEditing(undefined)}>
                    取消
                  </Button>
                  <Button type="submit" variant="primary" busy={busy()} disabled={!path().trim()}>
                    保存
                  </Button>
                </div>
              </div>
            </form>
          </Modal>
        )}
      </Show>
    </>
  )
}
