import { createEffect, createSignal, For, Show, Switch, Match } from "solid-js"
import { api, list, patch, post, remove, safeMessage } from "../api"
import {
  Button,
  Empty,
  ErrorLine,
  Field,
  formatDate,
  Icon,
  JobNote,
  Modal,
  PageHead,
  Spinner,
  Status,
  Toggle,
} from "../components"
import { useConsole } from "../context"
import type { Audit, Job, Model, Plugin, Skill, User } from "../types"
export default function Admin() {
  const app = useConsole()
  const [tab, setTab] = createSignal("users")
  const [users, setUsers] = createSignal<User[]>([])
  const [models, setModels] = createSignal<Model[]>([])
  const [plugins, setPlugins] = createSignal<Plugin[]>([])
  const [templates, setTemplates] = createSignal<Skill[]>([])
  const [jobs, setJobs] = createSignal<Job[]>([])
  const [audit, setAudit] = createSignal<Audit[]>([])
  const [loading, setLoading] = createSignal(true)
  const [error, setError] = createSignal("")
  const [busy, setBusy] = createSignal(false)
  const [test, setTest] = createSignal<unknown>()
  const [secret, setSecret] = createSignal<{ username: string; password: string }>()
  const [userForm, setUserForm] = createSignal<Partial<User>>()
  const [username, setUsername] = createSignal("")
  const [password, setPassword] = createSignal("")
  const [modelIds, setModelIds] = createSignal<string[]>([])
  const [pluginIds, setPluginIds] = createSignal<string[]>([])
  const [modelForm, setModelForm] = createSignal<Partial<Model>>()
  const [modelName, setModelName] = createSignal("")
  const [modelDesc, setModelDesc] = createSignal("")
  const [baseUrl, setBaseUrl] = createSignal("")
  const [modelId, setModelId] = createSignal("")
  const [apiKey, setApiKey] = createSignal("")
  const [modelEnabled, setModelEnabled] = createSignal(true)
  const [defaultModel, setDefaultModel] = createSignal(false)
  const [templateForm, setTemplateForm] = createSignal<Partial<Skill>>()
  const [templateName, setTemplateName] = createSignal("")
  const [templateDesc, setTemplateDesc] = createSignal("")
  const [templateContent, setTemplateContent] = createSignal("")
  const [reset, setReset] = createSignal<User>()
  const [resetPassword, setResetPassword] = createSignal("")
  let zipInput!: HTMLInputElement
  async function refresh() {
    try {
      const result = await Promise.all([
        list<User>("/admin/users"),
        list<Model>("/admin/models"),
        list<Plugin>("/admin/plugins"),
        list<Skill>("/admin/templates"),
        list<Job>("/admin/jobs"),
        list<Audit>("/admin/audit"),
      ])
      setUsers(result[0])
      setModels(result[1].map((item) => ({ ...item, enabled: !!item.enabled, is_default: !!item.is_default })))
      const catalog = new Map<string, Plugin>()
      for (const item of result[2]) {
        const existing = catalog.get(item.id)
        const version = { version: item.version, enabled: !!item.enabled }
        if (existing) existing.versions?.push(version)
        else catalog.set(item.id, { ...item, enabled: !!item.enabled, versions: [version] })
      }
      setPlugins([...catalog.values()])
      setTemplates(result[3])
      setJobs(result[4])
      setAudit(result[5])
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
  function editUser(value: Partial<User> = {}) {
    setUserForm(value)
    setUsername(value.username ?? "")
    setPassword("")
    setModelIds(value.model_ids ?? [])
    setPluginIds(value.plugin_ids ?? [])
    setError("")
  }
  function editModel(value: Partial<Model> = {}) {
    setModelForm(value)
    setModelName(value.name ?? "")
    setModelDesc(value.description ?? "")
    setBaseUrl(value.base_url ?? "")
    setModelId(value.model_id ?? "")
    setApiKey("")
    setModelEnabled(value.enabled ?? true)
    setDefaultModel(value.is_default ?? false)
    setError("")
  }
  function editTemplate(value: Partial<Skill> = {}) {
    setTemplateForm(value)
    setTemplateName(value.name ?? "")
    setTemplateDesc(value.description ?? "")
    setTemplateContent(value.content ?? "")
    setError("")
  }
  function selectPermission(id: string, kind: "models" | "plugins") {
    const setter = kind === "models" ? setModelIds : setPluginIds
    setter((values) => (values.includes(id) ? values.filter((value) => value !== id) : [...values, id]))
  }
  async function saveUser(event: SubmitEvent) {
    event.preventDefault()
    setBusy(true)
    try {
      if (userForm()?.id) {
        await patch("/admin/users/" + userForm()!.id, { model_ids: modelIds(), plugin_ids: pluginIds() })
      } else {
        const result = await post<{ user: User; password?: string }>("/admin/users", {
          username: username().trim(),
          password: password() || undefined,
          model_ids: modelIds(),
          plugin_ids: pluginIds(),
        })
        if (result.password) setSecret({ username: result.user.username, password: result.password })
      }
      setUserForm(undefined)
      setPassword("")
      app.notify("账号设置已保存，空间准备进度可在任务列表中查看。")
      await refresh()
    } catch (error) {
      setError((error as Error).message)
    } finally {
      setBusy(false)
    }
  }
  async function saveModel(event: SubmitEvent) {
    event.preventDefault()
    setBusy(true)
    try {
      const body = {
        name: modelName().trim(),
        description: modelDesc().trim(),
        base_url: baseUrl().trim(),
        model_id: modelId().trim(),
        api_key: apiKey() || undefined,
        enabled: modelEnabled(),
        is_default: defaultModel(),
      }
      if (modelForm()?.id) await patch("/admin/models/" + modelForm()!.id, body)
      else await post("/admin/models", body)
      setApiKey("")
      setModelForm(undefined)
      app.notify("模型配置已保存。")
      await refresh()
    } catch (error) {
      setError((error as Error).message)
    } finally {
      setBusy(false)
    }
  }
  async function saveTemplate(event: SubmitEvent) {
    event.preventDefault()
    setBusy(true)
    try {
      const body = { name: templateName().trim(), description: templateDesc().trim(), content: templateContent() }
      if (templateForm()?.id) await patch("/admin/templates/" + templateForm()!.id, body)
      else await post("/admin/templates", body)
      setTemplateForm(undefined)
      app.notify("技能模板已保存。")
      await refresh()
    } catch (error) {
      setError((error as Error).message)
    } finally {
      setBusy(false)
    }
  }
  async function operation(path: string, body: unknown = {}, showResult = false) {
    setBusy(true)
    try {
      const result = await post(path, body)
      if (showResult) setTest(result)
      else app.notify("操作已提交，可在任务进度中查看结果。")
      await refresh()
    } catch (error) {
      app.notify((error as Error).message, "error")
    } finally {
      setBusy(false)
    }
  }
  async function toggleAccount(user: User) {
    if (user.id === app.user().id) {
      app.notify("不能在这里停用当前登录账号。", "error")
      return
    }
    try {
      await patch("/admin/users/" + user.id, { active: user.active === false })
      await refresh()
    } catch (error) {
      app.notify((error as Error).message, "error")
    }
  }
  async function resetUser(event: SubmitEvent) {
    event.preventDefault()
    setBusy(true)
    try {
      const result = await post<{ password?: string }>("/admin/users/" + reset()!.id + "/reset-password", {
        password: resetPassword() || undefined,
      })
      if (result.password) setSecret({ username: reset()!.username, password: result.password })
      else app.notify("密码已重置，用户下次登录需重新设置。")
      setReset(undefined)
      setResetPassword("")
    } catch (error) {
      app.notify((error as Error).message, "error")
    } finally {
      setBusy(false)
    }
  }
  async function publish(file?: File) {
    if (!file) return
    setBusy(true)
    try {
      const body = new FormData()
      body.append("file", file)
      await api("/admin/plugins", { method: "POST", body })
      app.notify("插件包已提交并完成发布检查。")
      await refresh()
    } catch (error) {
      app.notify((error as Error).message, "error")
    } finally {
      setBusy(false)
      zipInput.value = ""
    }
  }
  async function enablePlugin(item: Plugin, version: string, enabled: boolean) {
    try {
      await patch("/admin/plugins/" + item.id + "/" + encodeURIComponent(version), { enabled })
      await refresh()
    } catch (error) {
      app.notify((error as Error).message, "error")
    }
  }
  async function deleteTemplate(item: Skill) {
    if (!window.confirm("确定删除这个模板吗？用户已复制的个人技能会保留。")) return
    try {
      await remove("/admin/templates/" + item.id)
      await refresh()
    } catch (error) {
      app.notify((error as Error).message, "error")
    }
  }
  async function copySecret() {
    try {
      await navigator.clipboard.writeText(secret()!.password)
      app.notify("初始密码已复制。")
    } catch {
      app.notify("请手动选择并复制密码。", "error")
    }
  }
  const tabs = [
    { id: "users", label: "账号与空间" },
    { id: "models", label: "模型管理" },
    { id: "plugins", label: "插件发布" },
    { id: "templates", label: "技能模板" },
    { id: "audit", label: "操作审计" },
  ]
  return (
    <div class="content-page admin-page">
      <PageHead eyebrow="系统管理" title="管理中心" text="统一管理账号、授权能力和独立工作空间。">
        <Button icon="refresh" onClick={refresh}>
          刷新状态
        </Button>
      </PageHead>
      <div class="stats-grid">
        <div>
          <span>账号总数</span>
          <strong>{users().length}</strong>
          <small>各账号数据独立</small>
        </div>
        <div>
          <span>运行中的空间</span>
          <strong>
            {users().filter((user) => ["ready", "running", "healthy"].includes(user.runtime?.status ?? "")).length}
            <i> / 4</i>
          </strong>
          <small>默认同时运行上限</small>
        </div>
        <div>
          <span>等待处理的任务</span>
          <strong>
            {jobs().filter((job) => ["queued", "pending", "running", "processing"].includes(job.status)).length}
          </strong>
          <small>开通与配置变更</small>
        </div>
        <div>
          <span>可用模型</span>
          <strong>{models().filter((model) => model.enabled !== false).length}</strong>
          <small>由管理员按账号授权</small>
        </div>
      </div>
      <ErrorLine message={error()} />
      <div class="section-toolbar">
        <div class="tabs scroll-tabs">
          <For each={tabs}>
            {(item) => (
              <button class={tab() === item.id ? "active" : ""} onClick={() => setTab(item.id)}>
                {item.label}
              </button>
            )}
          </For>
        </div>
        <Switch>
          <Match when={tab() === "users"}>
            <Button variant="primary" icon="plus" onClick={() => editUser()}>
              创建账号
            </Button>
          </Match>
          <Match when={tab() === "models"}>
            <Button variant="primary" icon="plus" onClick={() => editModel()}>
              添加模型
            </Button>
          </Match>
          <Match when={tab() === "plugins"}>
            <Button variant="primary" icon="upload" busy={busy()} onClick={() => zipInput.click()}>
              发布插件包
            </Button>
          </Match>
          <Match when={tab() === "templates"}>
            <Button variant="primary" icon="plus" onClick={() => editTemplate()}>
              创建模板
            </Button>
          </Match>
        </Switch>
      </div>
      <input
        ref={zipInput}
        type="file"
        accept=".zip"
        class="visually-hidden"
        aria-label="选择插件 ZIP 包"
        onChange={(event) => void publish(event.currentTarget.files?.[0])}
      />
      <Show
        when={!loading()}
        fallback={
          <div class="loading">
            <Spinner />
          </div>
        }
      >
        <Switch>
          <Match when={tab() === "users"}>
            <div class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>账号</th>
                    <th>空间状态</th>
                    <th>账号状态</th>
                    <th>已授权</th>
                    <th class="align-right">操作</th>
                  </tr>
                </thead>
                <tbody>
                  <For each={users()}>
                    {(user) => (
                      <tr>
                        <td>
                          <div class="user-cell">
                            <span class="avatar">{user.username.slice(0, 1).toUpperCase()}</span>
                            <div>
                              <strong>{user.username}</strong>
                              <small>{user.role === "admin" ? "管理员" : "普通用户"}</small>
                            </div>
                          </div>
                        </td>
                        <td>
                          <Status value={user.runtime?.status} />
                        </td>
                        <td>
                          <Status value={user.active === false ? "disabled" : "active"} />
                        </td>
                        <td>
                          <span class="muted">
                            {user.model_ids?.length ?? 0} 个模型 · {user.plugin_ids?.length ?? 0} 个插件
                          </span>
                        </td>
                        <td>
                          <div class="table-actions wrap">
                            <Button variant="ghost" onClick={() => editUser(user)}>
                              授权
                            </Button>
                            <Button
                              variant="ghost"
                              onClick={() => {
                                setReset(user)
                                setResetPassword("")
                              }}
                            >
                              重置密码
                            </Button>
                            <Show when={user.runtime}>
                              <Button
                                variant="ghost"
                                disabled={busy()}
                                onClick={() =>
                                  void operation(
                                    "/admin/users/" +
                                      user.id +
                                      "/runtime/" +
                                      (["ready", "running", "healthy"].includes(user.runtime?.status ?? "")
                                        ? "pause"
                                        : user.runtime?.status === "failed"
                                          ? "retry"
                                          : "resume"),
                                  )
                                }
                              >
                                {["ready", "running", "healthy"].includes(user.runtime?.status ?? "")
                                  ? "暂停"
                                  : user.runtime?.status === "failed"
                                    ? "重试"
                                    : "恢复"}
                              </Button>
                              <Button
                                variant="ghost"
                                disabled={busy()}
                                onClick={() => void operation("/admin/users/" + user.id + "/runtime/apply")}
                              >
                                应用配置
                              </Button>
                            </Show>
                            <Button
                              variant={user.active === false ? "ghost" : "danger"}
                              disabled={user.id === app.user().id}
                              onClick={() => void toggleAccount(user)}
                            >
                              {user.active === false ? "启用账号" : "停用"}
                            </Button>
                          </div>
                        </td>
                      </tr>
                    )}
                  </For>
                </tbody>
              </table>
            </div>
            <section class="settings-card">
              <div class="settings-heading">
                <div>
                  <h2>空间任务</h2>
                  <p>开通与配置更新会进入任务队列，失败后可由管理员重试。</p>
                </div>
              </div>
              <Show when={jobs().length} fallback={<Empty icon="clock" title="暂无空间任务" />}>
                <div class="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>任务</th>
                        <th>账号</th>
                        <th>状态</th>
                        <th>提交时间</th>
                        <th>说明</th>
                      </tr>
                    </thead>
                    <tbody>
                      <For each={jobs().slice(0, 30)}>
                        {(job) => (
                          <tr>
                            <td>
                              {(
                                {
                                  create: "开通空间",
                                  provision: "开通空间",
                                  apply: "应用配置",
                                  pause: "暂停空间",
                                  resume: "恢复空间",
                                  retry: "恢复任务",
                                } as Record<string, string>
                              )[job.action ?? job.type ?? ""] ?? "空间维护"}
                            </td>
                            <td>
                              {job.username ??
                                users().find((user) => user.id === (job.user_id ?? job.uid))?.username ??
                                "—"}
                            </td>
                            <td>
                              <Status value={job.status} />
                            </td>
                            <td>{formatDate(job.created_at ?? job.created)}</td>
                            <td class="muted">{job.error ? safeMessage(job.error) : "—"}</td>
                          </tr>
                        )}
                      </For>
                    </tbody>
                  </table>
                </div>
              </Show>
            </section>
          </Match>
          <Match when={tab() === "models"}>
            <div class="card-grid">
              <For
                each={models()}
                fallback={<Empty icon="skill" title="尚未配置模型" text="添加模型并按账号授权后，用户即可选择使用。" />}
              >
                {(item) => (
                  <article class="resource-card">
                    <div class="resource-head">
                      <span class="resource-icon blue">
                        <Icon name="skill" />
                      </span>
                      <Status value={item.enabled === false ? "disabled" : "enabled"} />
                    </div>
                    <h3>
                      {item.name}
                      <Show when={item.is_default}>
                        <span class="pill">默认</span>
                      </Show>
                    </h3>
                    <p>{item.description || "供授权用户使用的模型能力。"}</p>
                    <div class="resource-meta">{item.api_key_configured ? "访问凭据已配置" : "未配置访问凭据"}</div>
                    <div class="resource-actions">
                      <Button onClick={() => editModel(item)}>编辑配置</Button>
                      <Button
                        variant="ghost"
                        busy={busy()}
                        onClick={() => void operation("/admin/models/" + item.id + "/test", {}, true)}
                      >
                        连接测试
                      </Button>
                    </div>
                  </article>
                )}
              </For>
            </div>
          </Match>
          <Match when={tab() === "plugins"}>
            <div class="info-strip">
              <Icon name="shield" size={18} />
              <span>插件包通过发布检查后，才可授权给普通用户安装。用户不能上传可执行插件代码。</span>
            </div>
            <div class="card-grid">
              <For
                each={plugins()}
                fallback={<Empty icon="plugin" title="尚未发布插件" text="上传符合发布规范的 ZIP 插件包。" />}
              >
                {(item) => (
                  <article class="resource-card">
                    <div class="resource-head">
                      <span class="resource-icon">
                        <Icon name="plugin" />
                      </span>
                      <span class="pill">已发布目录</span>
                    </div>
                    <h3>{item.name}</h3>
                    <p>{item.description || "已发布的业务插件。"}</p>
                    <div class="plugin-versions">
                      <For
                        each={
                          item.versions?.length ? item.versions : [{ version: item.version, enabled: item.enabled }]
                        }
                      >
                        {(version) => {
                          const number = typeof version === "string" ? version : version.version
                          const enabled = typeof version === "string" ? true : version.enabled !== false
                          return (
                            <div>
                              <span>版本 {number}</span>
                              <Toggle
                                checked={enabled}
                                label={enabled ? "可用" : "停用"}
                                onChange={(value) => void enablePlugin(item, number, value)}
                              />
                            </div>
                          )
                        }}
                      </For>
                    </div>
                  </article>
                )}
              </For>
            </div>
          </Match>
          <Match when={tab() === "templates"}>
            <div class="card-grid">
              <For each={templates()} fallback={<Empty icon="skill" title="尚未发布技能模板" />}>
                {(item) => (
                  <article class="resource-card">
                    <span class="resource-icon">
                      <Icon name="skill" />
                    </span>
                    <h3>{item.name}</h3>
                    <p>{item.description || "可供用户复制并个性化的技能文本。"}</p>
                    <div class="resource-actions">
                      <Button onClick={() => editTemplate(item)}>编辑模板</Button>
                      <Button variant="danger" onClick={() => void deleteTemplate(item)}>
                        删除
                      </Button>
                    </div>
                  </article>
                )}
              </For>
            </div>
          </Match>
          <Match when={tab() === "audit"}>
            <Show when={audit().length} fallback={<Empty icon="shield" title="暂无操作记录" />}>
              <div class="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>时间</th>
                      <th>操作人</th>
                      <th>操作</th>
                      <th>对象</th>
                      <th>记录状态</th>
                    </tr>
                  </thead>
                  <tbody>
                    <For each={audit()}>
                      {(item) => (
                        <tr>
                          <td class="nowrap">{formatDate(item.created_at ?? item.created)}</td>
                          <td>{item.username ?? item.actor ?? "系统"}</td>
                          <td>
                            {(
                              {
                                "password.changed": "修改登录密码",
                                "user.create": "创建账号",
                                "user.update": "修改账号授权",
                                "user.password_reset": "重置账号密码",
                                "runtime.pause": "暂停空间",
                                "runtime.resume": "恢复空间",
                                "runtime.retry": "重试空间任务",
                                "runtime.apply": "应用空间配置",
                                "plugin.configure": "配置业务插件",
                                "plugin.publish": "发布插件版本",
                                "model.create": "添加授权模型",
                                "model.update": "更新模型配置",
                              } as Record<string, string>
                            )[item.action ?? ""] ?? "管理操作"}
                          </td>
                          <td>{safeMessage(item.target, "—")}</td>
                          <td>
                            <Status value={item.status ?? "recorded"} />
                          </td>
                        </tr>
                      )}
                    </For>
                  </tbody>
                </table>
              </div>
            </Show>
          </Match>
        </Switch>
      </Show>
      <Show when={userForm()}>
        <Modal
          title={userForm()?.id ? "账号授权" : "创建账号与独立空间"}
          text="每个账号对应一个独立工作空间，开通结果请查看任务进度。"
          wide
          onClose={() => {
            if (!busy()) setUserForm(undefined)
          }}
        >
          <form onSubmit={saveUser}>
            <ErrorLine message={error()} />
            <div class="form-grid">
              <Field label="账号" required>
                <input
                  required
                  maxlength={64}
                  disabled={!!userForm()?.id}
                  value={username()}
                  onInput={(event) => setUsername(event.currentTarget.value)}
                  autocomplete="off"
                />
              </Field>
              <Show when={!userForm()?.id}>
                <Field label="初始密码" hint="留空由系统生成，完整密码仅创建后显示一次。">
                  <input
                    type="password"
                    minlength={12}
                    value={password()}
                    onInput={(event) => setPassword(event.currentTarget.value)}
                    autocomplete="new-password"
                  />
                </Field>
              </Show>
            </div>
            <fieldset class="permission-picker">
              <legend>授权模型</legend>
              <For each={models()} fallback={<p class="muted">还没有模型，请先在模型管理中添加。</p>}>
                {(item) => (
                  <label>
                    <input
                      type="checkbox"
                      checked={modelIds().includes(item.id)}
                      onChange={() => selectPermission(item.id, "models")}
                    />
                    {item.name}
                  </label>
                )}
              </For>
            </fieldset>
            <fieldset class="permission-picker">
              <legend>授权插件</legend>
              <For each={plugins()} fallback={<p class="muted">暂时没有已发布插件。</p>}>
                {(item) => (
                  <label>
                    <input
                      type="checkbox"
                      checked={pluginIds().includes(item.id)}
                      onChange={() => selectPermission(item.id, "plugins")}
                    />
                    {item.name}
                  </label>
                )}
              </For>
            </fieldset>
            <div class="modal-actions">
              <Button type="button" onClick={() => setUserForm(undefined)}>
                取消
              </Button>
              <Button type="submit" variant="primary" busy={busy()}>
                {userForm()?.id ? "保存授权" : "创建并开通"}
              </Button>
            </div>
          </form>
        </Modal>
      </Show>
      <Show when={modelForm()}>
        <Modal
          title={modelForm()?.id ? "编辑授权模型" : "添加授权模型"}
          text="连接参数仅管理员可见，普通用户只能选择被授权的模型名称。"
          wide
          onClose={() => {
            if (!busy()) {
              setModelForm(undefined)
              setApiKey("")
            }
          }}
        >
          <form onSubmit={saveModel}>
            <ErrorLine message={error()} />
            <div class="form-grid">
              <Field label="显示名称" required>
                <input required value={modelName()} onInput={(e) => setModelName(e.currentTarget.value)} />
              </Field>
              <Field label="简短说明">
                <input value={modelDesc()} onInput={(e) => setModelDesc(e.currentTarget.value)} />
              </Field>
              <Field label="兼容接口地址" required hint="提供 OpenAI 兼容协议的接口根地址，通常以 /v1 结尾。">
                <input
                  required
                  type="url"
                  value={baseUrl()}
                  onInput={(e) => setBaseUrl(e.currentTarget.value)}
                  placeholder="https://model.example/v1"
                />
              </Field>
              <Field label="模型标识" required hint="填写推理服务实际提供的模型 ID。">
                <input required value={modelId()} onInput={(e) => setModelId(e.currentTarget.value)} />
              </Field>
            </div>
            <Field
              label="访问密钥"
              hint={modelForm()?.api_key_configured ? "已配置，留空保留现有密钥。" : "如接口需要认证，请填写访问密钥。"}
            >
              <input
                type="password"
                autocomplete="new-password"
                value={apiKey()}
                onInput={(e) => setApiKey(e.currentTarget.value)}
              />
            </Field>
            <div class="inline-toggles">
              <Toggle checked={modelEnabled()} onChange={setModelEnabled} label="允许使用" />
              <Toggle checked={defaultModel()} onChange={setDefaultModel} label="设为默认模型" />
            </div>
            <div class="modal-actions">
              <Button
                type="button"
                onClick={() => {
                  setModelForm(undefined)
                  setApiKey("")
                }}
              >
                取消
              </Button>
              <Button type="submit" variant="primary" busy={busy()}>
                保存模型
              </Button>
            </div>
          </form>
        </Modal>
      </Show>
      <Show when={templateForm()}>
        <Modal
          title={templateForm()?.id ? "编辑技能模板" : "发布技能模板"}
          wide
          onClose={() => setTemplateForm(undefined)}
        >
          <form onSubmit={saveTemplate}>
            <ErrorLine message={error()} />
            <div class="form-grid">
              <Field label="模板名称" required>
                <input required value={templateName()} onInput={(e) => setTemplateName(e.currentTarget.value)} />
              </Field>
              <Field label="模板说明">
                <input value={templateDesc()} onInput={(e) => setTemplateDesc(e.currentTarget.value)} />
              </Field>
            </div>
            <Field label="模板内容" required>
              <textarea
                class="skill-editor"
                required
                value={templateContent()}
                onInput={(e) => setTemplateContent(e.currentTarget.value)}
              />
            </Field>
            <div class="modal-actions">
              <Button type="submit" variant="primary" busy={busy()}>
                保存模板
              </Button>
            </div>
          </form>
        </Modal>
      </Show>
      <Show when={reset()}>
        <Modal
          title={"重置密码 · " + reset()?.username}
          text="用户下次登录时需要设置新的个人密码。"
          onClose={() => setReset(undefined)}
        >
          <form onSubmit={resetUser}>
            <Field label="新初始密码" hint="留空由系统生成。">
              <input
                type="password"
                minlength={12}
                autocomplete="new-password"
                value={resetPassword()}
                onInput={(e) => setResetPassword(e.currentTarget.value)}
              />
            </Field>
            <div class="modal-actions">
              <Button type="submit" variant="primary" busy={busy()}>
                确认重置
              </Button>
            </div>
          </form>
        </Modal>
      </Show>
      <Show when={secret()}>
        <Modal
          title={"保存初始密码 · " + secret()?.username}
          text="完整密码仅显示一次，请通过适当方式交给账号本人。"
          onClose={() => setSecret(undefined)}
        >
          <input class="secret-once" readonly value={secret()?.password} aria-label="一次性初始密码" />
          <div class="modal-actions">
            <Button icon="copy" onClick={copySecret}>
              复制密码
            </Button>
            <Button variant="primary" onClick={() => setSecret(undefined)}>
              我已保存
            </Button>
          </div>
        </Modal>
      </Show>
      <Show when={test() !== undefined}>
        <Modal title="连接测试结果" onClose={() => setTest(undefined)}>
          <JobNote value={test()} />
          <div class="modal-actions">
            <Button onClick={() => setTest(undefined)}>关闭</Button>
          </div>
        </Modal>
      </Show>
    </div>
  )
}
