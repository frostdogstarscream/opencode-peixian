import { createEffect, createMemo, createSignal, For, onCleanup, onMount, Show, Switch, Match } from "solid-js"
import { api, ApiError, BASE, onUnauthorized, post, safeMessage, setAuth } from "./api"
import type { Auth, User } from "./types"
import { Button, ErrorLine, Field, Icon, Spinner, Status } from "./components"
import { Context } from "./context"
import { brand } from "./brand"
import Chat from "./pages/Chat"
import Files from "./pages/Files"
import Skills from "./pages/Skills"
import Plugins from "./pages/Plugins"
import Settings from "./pages/Settings"
import Admin from "./pages/Admin"
const pages = [
  { id: "chat", name: "智能对话", icon: "chat" },
  { id: "files", name: "我的文件", icon: "file" },
  { id: "skills", name: "分析技能", icon: "skill" },
  { id: "plugins", name: "业务插件", icon: "plugin" },
  { id: "settings", name: "个人设置", icon: "settings" },
]
export default function App() {
  const [auth, setSession] = createSignal<Auth>()
  const [loading, setLoading] = createSignal(true)
  const [initialError, setInitialError] = createSignal("")
  const [page, setPage] = createSignal("chat")
  const [menu, setMenu] = createSignal(false)
  const [changed, setChanged] = createSignal(0)
  const [disconnected, setDisconnected] = createSignal(false)
  const [toast, setToast] = createSignal<{ message: string; kind: string }>()
  const [dark, setDark] = createSignal(localStorage.getItem(brand.themeKey) === "dark")
  let timer: ReturnType<typeof setTimeout> | undefined
  function notify(message: string, kind = "success") {
    clearTimeout(timer)
    setToast({ message: safeMessage(message), kind })
    timer = setTimeout(() => setToast(undefined), 5500)
  }
  function accept(value: Auth) {
    setAuth(value)
    setSession(value)
    if (value.user.role === "admin" && !value.user.runtime) setPage("admin")
  }
  async function refreshUser() {
    const first = !auth()
    const data = await api<Auth>("/me")
    setAuth(data)
    setSession(data)
    if (first && data.user.role === "admin" && !data.user.runtime) setPage("admin")
  }
  async function initialize() {
    setLoading(true)
    setInitialError("")
    try {
      await refreshUser()
    } catch (error) {
      if (!(error instanceof ApiError && error.status === 401)) setInitialError(safeMessage((error as Error).message))
    } finally {
      setLoading(false)
    }
  }
  onMount(() => {
    onUnauthorized(() => {
      setAuth()
      setSession(undefined)
    })
    void initialize()
  })
  onCleanup(() => clearTimeout(timer))
  createEffect(() => {
    document.documentElement.dataset.theme = dark() ? "dark" : "light"
    localStorage.setItem(brand.themeKey, dark() ? "dark" : "light")
  })
  const eventIdentity = createMemo(() => {
    const user = auth()?.user
    return user &&
      !user.must_change_password &&
      ["ready", "running", "healthy", "updating", "applying"].includes(user.runtime?.status ?? "")
      ? user.id
      : undefined
  })
  createEffect(() => {
    if (!eventIdentity()) {
      setDisconnected(false)
      return
    }
    const events = new EventSource(BASE + "/events", { withCredentials: true })
    let debounce: ReturnType<typeof setTimeout> | undefined
    events.onopen = () => setDisconnected(false)
    events.onerror = () => setDisconnected(true)
    const update = () => {
      if (debounce) return
      debounce = setTimeout(() => {
        debounce = undefined
        setChanged((value) => value + 1)
        void refreshUser().catch(() => {})
      }, 250)
    }
    events.addEventListener("change", update)
    onCleanup(() => {
      clearTimeout(debounce)
      events.close()
    })
  })
  const accountPoll = setInterval(() => {
    const user = auth()?.user
    if (!user || user.must_change_password) return
    void refreshUser().catch(() => {})
    if (
      user.role === "admin" ||
      !["ready", "running", "healthy", "updating", "applying"].includes(user.runtime?.status ?? "")
    )
      setChanged((value) => value + 1)
  }, 5000)
  onCleanup(() => clearInterval(accountPoll))
  async function logout() {
    try {
      await post("/auth/logout")
      setAuth()
      setSession(undefined)
      setMenu(false)
    } catch (error) {
      notify((error as Error).message, "error")
    }
  }
  return (
    <Show
      when={!loading()}
      fallback={
        <div class="boot">
          <Spinner />
          <p>正在打开工作台</p>
        </div>
      }
    >
      <Show when={auth()} fallback={<Login onSuccess={accept} initialError={initialError()} onRetry={initialize} />}>
        {(session) => (
          <Show
            when={!session().user.must_change_password}
            fallback={<PasswordGate user={session().user} onDone={refreshUser} />}
          >
            <Context.Provider value={{ user: () => auth()!.user, notify, refreshUser, changed }}>
              <div class="app-shell">
                <Show when={menu()}>
                  <button class="nav-overlay" aria-label="关闭导航" onClick={() => setMenu(false)} />
                </Show>
                <aside class={"sidebar " + (menu() ? "open" : "")}>
                  <a
                    class="brand"
                    href="#"
                    onClick={(event) => {
                      event.preventDefault()
                      setPage("chat")
                      setMenu(false)
                    }}
                  >
                    <span class="brand-mark">{brand.mark}</span>
                    <span>
                      <strong>{brand.name}</strong>
                      <small>{brand.tagline}</small>
                    </span>
                  </a>
                  <div class="space-label">
                    个人工作空间 <Icon name="lock" size={12} />
                  </div>
                  <nav aria-label="主导航">
                    <For each={pages}>
                      {(item) => (
                        <button
                          class={page() === item.id ? "active" : ""}
                          onClick={() => {
                            setPage(item.id)
                            setMenu(false)
                          }}
                          aria-current={page() === item.id ? "page" : undefined}
                        >
                          <Icon name={item.icon} />
                          <span>{item.name}</span>
                          <Show when={page() === item.id}>
                            <span class="nav-dot" />
                          </Show>
                        </button>
                      )}
                    </For>
                    <Show when={session().user.role === "admin"}>
                      <div class="nav-separator" />
                      <button
                        class={page() === "admin" ? "active" : ""}
                        onClick={() => {
                          setPage("admin")
                          setMenu(false)
                        }}
                      >
                        <Icon name="shield" />
                        <span>管理中心</span>
                      </button>
                    </Show>
                  </nav>
                  <div class="sidebar-bottom">
                    <div class="privacy-note">
                      <Icon name="shield" size={17} />
                      <span>文件与对话在你的独立空间中保存</span>
                    </div>
                    <div class="account-row">
                      <span class="avatar">{session().user.username.slice(0, 1).toUpperCase()}</span>
                      <span>
                        <strong>{session().user.username}</strong>
                        <small>{session().user.role === "admin" ? "系统管理员" : "工作台用户"}</small>
                      </span>
                      <button
                        class="icon-button"
                        aria-label={dark() ? "切换浅色" : "切换深色"}
                        onClick={() => setDark(!dark())}
                      >
                        <Icon name={dark() ? "sun" : "moon"} size={18} />
                      </button>
                      <button class="icon-button" aria-label="退出登录" onClick={logout}>
                        <Icon name="logout" size={18} />
                      </button>
                    </div>
                  </div>
                </aside>
                <main class="main-area">
                  <header class="topbar">
                    <div>
                      <button class="icon-button mobile-menu" aria-label="打开导航" onClick={() => setMenu(true)}>
                        <Icon name="menu" />
                      </button>
                      <span class="breadcrumb">
                        工作台 <span>/</span> {pages.find((item) => item.id === page())?.name ?? "管理中心"}
                      </span>
                    </div>
                    <div class="topbar-status">
                      <Show when={disconnected()}>
                        <span class="connection-note">正在恢复连接</span>
                      </Show>
                      <Status value={auth()?.user.runtime?.status} />
                    </div>
                  </header>
                  <div class={"page-body " + (page() === "chat" ? "chat-page-body" : "")}>
                    <div class="chat-preserved" hidden={page() !== "chat"}>
                      <Chat />
                    </div>
                    <Switch>
                      <Match when={page() === "files"}>
                        <Files />
                      </Match>
                      <Match when={page() === "skills"}>
                        <Skills />
                      </Match>
                      <Match when={page() === "plugins"}>
                        <Plugins />
                      </Match>
                      <Match when={page() === "settings"}>
                        <Settings />
                      </Match>
                      <Match when={page() === "admin" && session().user.role === "admin"}>
                        <Admin />
                      </Match>
                    </Switch>
                  </div>
                </main>
              </div>
              <Show when={toast()}>
                {(value) => (
                  <div class={"toast " + value().kind} role="status">
                    <Icon name={value().kind === "error" ? "close" : "check"} size={17} />
                    {value().message}
                    <button aria-label="关闭提示" onClick={() => setToast(undefined)}>
                      ×
                    </button>
                  </div>
                )}
              </Show>
            </Context.Provider>
          </Show>
        )}
      </Show>
    </Show>
  )
}
function Login(props: { onSuccess: (value: Auth) => void; initialError: string; onRetry: () => Promise<void> }) {
  const [username, setUsername] = createSignal("")
  const [password, setPassword] = createSignal("")
  const [busy, setBusy] = createSignal(false)
  const [error, setError] = createSignal("")
  async function submit(event: SubmitEvent) {
    event.preventDefault()
    setBusy(true)
    setError("")
    try {
      const data = await post<Auth>("/auth/login", { username: username().trim(), password: password() })
      setPassword("")
      props.onSuccess(data)
    } catch (error) {
      setError((error as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div class="login-shell">
      <div class="login-story">
        <span class="brand-mark">{brand.mark}</span>
        <div class="eyebrow">{brand.name}</div>
        <h1>{brand.tagline}</h1>
        <p>
          围绕资料展开对话，使用专业技能完成分析。
          <br />
          你的文件、思考与成果，在独立空间中有序留存。
        </p>
        <div class="story-art">
          <span />
          <span />
          <span />
          <div>
            <Icon name="skill" size={42} />
          </div>
        </div>
        <small>专属空间 · 按需分析 · 结果可追溯</small>
      </div>
      <div class="login-side">
        <form class="login-card" onSubmit={submit}>
          <div class="eyebrow">欢迎回来</div>
          <h2>登录工作台</h2>
          <p>使用管理员为你开通的账号继续。</p>
          <ErrorLine message={error() || props.initialError} />
          <Field label="账号">
            <input
              required
              autocomplete="username"
              value={username()}
              onInput={(event) => setUsername(event.currentTarget.value)}
              placeholder="请输入账号"
            />
          </Field>
          <Field label="密码">
            <input
              required
              type="password"
              autocomplete="current-password"
              value={password()}
              onInput={(event) => setPassword(event.currentTarget.value)}
              placeholder="请输入密码"
            />
          </Field>
          <Button type="submit" variant="primary" busy={busy()} class="full">
            登录 <Icon name="arrow" size={16} />
          </Button>
          <Show when={props.initialError}>
            <Button type="button" variant="ghost" onClick={props.onRetry}>
              重新连接
            </Button>
          </Show>
          <small>账号或密码有问题，请联系管理员。</small>
        </form>
        <div class="login-foot">{brand.name} · 专属工作空间</div>
      </div>
    </div>
  )
}
function PasswordGate(props: { user: User; onDone: () => Promise<void> }) {
  const [old, setOld] = createSignal("")
  const [password, setPassword] = createSignal("")
  const [confirm, setConfirm] = createSignal("")
  const [busy, setBusy] = createSignal(false)
  const [error, setError] = createSignal("")
  async function save(event: SubmitEvent) {
    event.preventDefault()
    if (password() !== confirm()) {
      setError("两次输入的新密码不一致。")
      return
    }
    setBusy(true)
    setError("")
    try {
      await post("/me/password", { current_password: old(), password: password() })
      await props.onDone()
    } catch (error) {
      setError((error as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div class="password-gate">
      <form class="login-card" onSubmit={save}>
        <span class="empty-icon">
          <Icon name="lock" />
        </span>
        <h2>设置你的登录密码</h2>
        <p>{props.user.username}，首次登录需要更换初始密码。</p>
        <ErrorLine message={error()} />
        <Field label="当前密码">
          <input
            type="password"
            required
            autocomplete="current-password"
            value={old()}
            onInput={(e) => setOld(e.currentTarget.value)}
          />
        </Field>
        <Field label="新密码" hint="至少 12 个字符，建议组合使用字母、数字与符号。">
          <input
            type="password"
            required
            minlength={12}
            autocomplete="new-password"
            value={password()}
            onInput={(e) => setPassword(e.currentTarget.value)}
          />
        </Field>
        <Field label="确认新密码">
          <input
            type="password"
            required
            minlength={12}
            autocomplete="new-password"
            value={confirm()}
            onInput={(e) => setConfirm(e.currentTarget.value)}
          />
        </Field>
        <Button variant="primary" busy={busy()} type="submit" class="full">
          保存并进入工作台
        </Button>
      </form>
    </div>
  )
}
