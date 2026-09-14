import { createEffect, createSignal, For, Show } from "solid-js"
import { list, post, remove } from "../api"
import { Button, Empty, ErrorLine, Field, formatDate, Icon, Modal, PageHead } from "../components"
import { useConsole } from "../context"
type Token = { id: string; name: string; created_at?: string; created?: number; expires?: number }
export default function Settings() {
  const app = useConsole()
  const [old, setOld] = createSignal("")
  const [password, setPassword] = createSignal("")
  const [confirm, setConfirm] = createSignal("")
  const [busy, setBusy] = createSignal(false)
  const [error, setError] = createSignal("")
  const [tokens, setTokens] = createSignal<Token[]>([])
  const [tokenName, setTokenName] = createSignal("")
  const [create, setCreate] = createSignal(false)
  const [secret, setSecret] = createSignal("")
  const [creating, setCreating] = createSignal(false)
  async function refresh() {
    try {
      setTokens(await list<Token>("/tokens"))
    } catch (error) {
      setError((error as Error).message)
    }
  }
  createEffect(() => {
    app.changed()
    void refresh()
  })
  async function changePassword(event: SubmitEvent) {
    event.preventDefault()
    if (password() !== confirm()) {
      setError("两次输入的新密码不一致。")
      return
    }
    setBusy(true)
    setError("")
    try {
      await post("/me/password", { current_password: old(), password: password() })
      setOld("")
      setPassword("")
      setConfirm("")
      await app.refreshUser()
      app.notify("登录密码已更新。")
    } catch (error) {
      setError((error as Error).message)
    } finally {
      setBusy(false)
    }
  }
  async function createToken(event: SubmitEvent) {
    event.preventDefault()
    setCreating(true)
    try {
      const result = await post<{ token: string; item: Token }>("/tokens", { name: tokenName().trim() })
      setSecret(result.token)
      setCreate(false)
      setTokenName("")
      await refresh()
    } catch (error) {
      app.notify((error as Error).message, "error")
    } finally {
      setCreating(false)
    }
  }
  async function revoke(item: Token) {
    if (!window.confirm("确定撤销此访问令牌吗？使用它的程序将无法继续连接。")) return
    try {
      await remove("/tokens/" + item.id)
      await refresh()
      app.notify("访问令牌已撤销。")
    } catch (error) {
      app.notify((error as Error).message, "error")
    }
  }
  async function copy() {
    try {
      await navigator.clipboard.writeText(secret())
      app.notify("已复制，请妥善保存。")
    } catch {
      app.notify("复制未完成，请手动选择令牌并复制。", "error")
    }
  }
  return (
    <div class="content-page">
      <PageHead eyebrow="账号与访问" title="个人设置" text="管理登录凭据和你的程序访问权限。" />
      <ErrorLine message={error()} />
      <section class="settings-card">
        <div class="settings-heading">
          <span class="resource-icon">
            <Icon name="users" />
          </span>
          <div>
            <h2>账号信息</h2>
            <p>账号由管理员开通，工作空间按账号独立。</p>
          </div>
        </div>
        <div class="account-summary">
          <div>
            <small>账号</small>
            <strong>{app.user().username}</strong>
          </div>
          <div>
            <small>角色</small>
            <strong>{app.user().role === "admin" ? "管理员" : "普通用户"}</strong>
          </div>
          <div>
            <small>空间状态</small>
            <strong>
              {["ready", "running", "healthy"].includes(app.user().runtime?.status ?? "") ? "已就绪" : "准备或维护中"}
            </strong>
          </div>
        </div>
      </section>
      <section class="settings-card">
        <div class="settings-heading">
          <span class="resource-icon">
            <Icon name="lock" />
          </span>
          <div>
            <h2>修改登录密码</h2>
            <p>至少 12 个字符，建议组合使用字母、数字和符号。</p>
          </div>
        </div>
        <form onSubmit={changePassword}>
          <div class="form-grid three">
            <Field label="当前密码">
              <input
                required
                type="password"
                autocomplete="current-password"
                value={old()}
                onInput={(event) => setOld(event.currentTarget.value)}
              />
            </Field>
            <Field label="新密码">
              <input
                required
                minlength={12}
                type="password"
                autocomplete="new-password"
                value={password()}
                onInput={(event) => setPassword(event.currentTarget.value)}
              />
            </Field>
            <Field label="确认新密码">
              <input
                required
                minlength={12}
                type="password"
                autocomplete="new-password"
                value={confirm()}
                onInput={(event) => setConfirm(event.currentTarget.value)}
              />
            </Field>
          </div>
          <Button variant="primary" type="submit" busy={busy()}>
            更新密码
          </Button>
        </form>
      </section>
      <section class="settings-card">
        <div class="settings-heading">
          <span class="resource-icon blue">
            <Icon name="plugin" />
          </span>
          <div>
            <h2>程序访问令牌</h2>
            <p>用于 Python 等客户端，只能访问你有权限的数据。完整令牌仅创建时显示一次。</p>
          </div>
          <Button icon="plus" onClick={() => setCreate(true)}>
            创建令牌
          </Button>
        </div>
        <Show
          when={tokens().length}
          fallback={<Empty icon="lock" title="暂未创建访问令牌" text="浏览器登录不需要创建令牌。" />}
        >
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>名称</th>
                  <th>创建时间</th>
                  <th>到期时间</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                <For each={tokens()}>
                  {(item) => (
                    <tr>
                      <td>
                        <strong>{item.name}</strong>
                      </td>
                      <td>{formatDate(item.created_at ?? item.created)}</td>
                      <td>{formatDate(item.expires)}</td>
                      <td class="align-right">
                        <Button variant="danger" onClick={() => void revoke(item)}>
                          撤销
                        </Button>
                      </td>
                    </tr>
                  )}
                </For>
              </tbody>
            </table>
          </div>
        </Show>
      </section>
      <Show when={create()}>
        <Modal title="创建访问令牌" text="用容易辨认的名称记录用途，便于日后撤销。" onClose={() => setCreate(false)}>
          <form onSubmit={createToken}>
            <Field label="令牌名称">
              <input
                required
                maxlength={80}
                value={tokenName()}
                onInput={(event) => setTokenName(event.currentTarget.value)}
                placeholder="例如：个人 Python 客户端"
              />
            </Field>
            <div class="modal-actions">
              <Button variant="primary" type="submit" busy={creating()}>
                创建令牌
              </Button>
            </div>
          </form>
        </Modal>
      </Show>
      <Show when={secret()}>
        <Modal
          title="保存你的访问令牌"
          text="仅此时可查看完整令牌。请妥善保存，不要发送给其他人。"
          onClose={() => setSecret("")}
        >
          <textarea class="secret-once" readonly rows={3} aria-label="一次性访问令牌" value={secret()} />
          <div class="modal-actions">
            <Button icon="copy" onClick={copy}>
              复制令牌
            </Button>
            <Button variant="primary" onClick={() => setSecret("")}>
              我已保存
            </Button>
          </div>
        </Modal>
      </Show>
    </div>
  )
}
