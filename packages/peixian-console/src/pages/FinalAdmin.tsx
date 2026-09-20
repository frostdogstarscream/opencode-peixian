import { createEffect, createMemo, createSignal, For, Match, Show, Switch } from "solid-js"
import type { JSX } from "solid-js"
import { api, download, list, patch, post, remove, safeMessage } from "../api"
import { Button, ErrorLine, Field, formatDate, Icon, Modal, Status } from "../components"
import { useConsole } from "../context"
import type { Department, Invocation, Model, Role, User } from "../types"

type Section = "models" | "users" | "audit"

export default function FinalAdmin(props: { section: Section }) {
  const app = useConsole()
  const [models, setModels] = createSignal<Model[]>([]), [users, setUsers] = createSignal<User[]>([])
  const [departments, setDepartments] = createSignal<Department[]>([]), [invocations, setInvocations] = createSignal<Invocation[]>([])
  const [summary, setSummary] = createSignal({ users: 0, departments: 0, enabled: 0 }), [error, setError] = createSignal("")
  const [query, setQuery] = createSignal(""), [modelForm, setModelForm] = createSignal<Partial<Model>>()
  const [userForm, setUserForm] = createSignal<Partial<User>>(), [departmentForm, setDepartmentForm] = createSignal<Partial<Department>>()
  const [showDepartments, setShowDepartments] = createSignal(false), [connectionState, setConnectionState] = createSignal<"idle" | "testing" | "success">("idle")
  const [resetPasswordValue, setResetPasswordValue] = createSignal("")
  const [selectedInvocation, setSelectedInvocation] = createSignal<Invocation>()
  const [auditTotal, setAuditTotal] = createSignal(0)
  let modelFormElement!: HTMLFormElement

  const shownModels = createMemo(() => filter(models(), query(), (item) => `${item.name} ${item.model_id} ${item.provider}`))
  const shownDepartments = () => departments()
  const shownUsers = createMemo(() => filter(users(), query(), (item) => `${item.display_name} ${item.police_no} ${item.department?.name} ${item.username}`))
  const shownInvocations = createMemo(() => filter(invocations(), query(), (item) => `${item.display_name} ${item.department_name} ${item.query_summary} ${item.session_id}`))
  const userSummary = () => summary()

  async function refresh() {
    setError("")
    try {
      if (props.section === "models") setModels(await list<Model>("/admin/models"))
      if (props.section === "users") {
        const [values, tree, totals] = await Promise.all([
          list<User>("/admin/users"),
          api<{ items: Department[] }>("/admin/departments/tree"),
          api<{ users: number; departments: number; enabled: number; disabled: number }>("/admin/users/summary"),
        ])
        setUsers(values)
        setDepartments(flattenDepartments(tree.items))
        setSummary(totals)
      }
      if (props.section === "audit") {
        const values = await api<{ items: Invocation[]; total: number }>("/admin/invocations?page=1&page_size=100" + (query().trim() ? "&query=" + encodeURIComponent(query().trim()) : ""))
        setInvocations(values.items)
        setAuditTotal(values.total)
      }
    } catch (cause) { setError(safeMessage((cause as Error).message)) }
  }
  createEffect(() => { app.changed(); props.section; setQuery(""); void refresh() })

  function modelPayload(form: HTMLFormElement) {
    const data = Object.fromEntries(new FormData(form))
    return {
      name: String(data.name || ""),
      provider: String(data.provider || ""),
      model_id: String(data.model_id || ""),
      base_url: String(data.base_url || ""),
      api_key: data.api_key ? String(data.api_key) : undefined,
      description: String(data.description || ""),
      context_length: data.context_length ? Number(data.context_length) : null,
      access_mode: data.access_mode === "local" ? "local" : "api",
      supports_tools: data.supports_tools === "on",
      enabled: data.enabled === "on",
      is_default: data.is_default === "on",
    }
  }
  async function saveModel(event: SubmitEvent) {
    event.preventDefault()
    const payload = modelPayload(event.currentTarget as HTMLFormElement)
    try {
      if (modelForm()?.id) await patch("/admin/models/" + modelForm()!.id, payload)
      else await post("/admin/models", payload)
      await refresh()
      app.notify("模型配置已保存。")
      setModelForm(undefined)
    } catch (cause) { setError(safeMessage((cause as Error).message)) }
  }
  async function testModel(item: Model) {
    try { const result = await post<{ ok: boolean; message: string }>("/admin/models/" + item.id + "/test"); app.notify(result.message, result.ok ? "success" : "error"); await refresh() }
    catch (cause) { app.notify((cause as Error).message, "error") }
  }
  async function setModelEnabled(item: Model, enabled: boolean) {
    if (item.enabled === enabled) return
    try { await patch("/admin/models/" + item.id, { enabled }); await refresh(); app.notify(enabled ? "模型已启用。" : "模型已关停。") }
    catch (cause) { app.notify(safeMessage((cause as Error).message), "error") }
  }
  async function testDraftConnection() {
    setConnectionState("testing")
    try {
      const result = await post<{ ok: boolean; message: string; elapsed_ms: number }>("/admin/models/test", modelPayload(modelFormElement))
      setConnectionState(result.ok ? "success" : "idle")
      app.notify(`${result.message}（${result.elapsed_ms}ms）`, result.ok ? "success" : "error")
    } catch (cause) {
      setConnectionState("idle")
      app.notify(safeMessage((cause as Error).message), "error")
    }
  }
  async function saveUser(event: SubmitEvent) {
    event.preventDefault()
    const data = Object.fromEntries(new FormData(event.currentTarget as HTMLFormElement))
    const grants = { model_ids: userForm()?.model_ids ?? [], ...(app.can("plugins.manage") ? { plugin_ids: userForm()?.plugin_ids ?? [] } : {}) }
    const profile = {
      display_name: String(data.display_name || ""),
      police_no: String(data.police_no || ""),
      position: String(data.position || ""),
      ...(app.user().role === "super_admin" ? { department_id: data.department_id ? String(data.department_id) : null } : {}),
    }
    const payload = userForm()?.id ? { ...grants, ...profile, active: data.active === "on" } : { ...grants, ...profile, username: data.username, password: data.password || undefined, ...(app.can("admins.manage") ? { role: (data.system_role || "user") as Role } : {}) }
    try { if (userForm()?.id) await patch("/admin/users/" + userForm()!.id, payload); else await post("/admin/users", payload); setUserForm(undefined); await refresh(); app.notify("用户资料与授权已保存。") }
    catch (cause) { setError(safeMessage((cause as Error).message)) }
  }
  async function resetUserPassword(item: User) {
    try {
      const result = await post<{ password: string }>("/admin/users/" + item.id + "/reset-password")
      setResetPasswordValue(result.password)
    }
    catch (cause) { app.notify(safeMessage((cause as Error).message), "error") }
  }
  async function disableUser(item: User) {
    if (item.active === false) return
    try { await patch("/admin/users/" + item.id, { active: false }); await refresh(); app.notify("账号已禁用。") }
    catch (cause) { app.notify(safeMessage((cause as Error).message), "error") }
  }
  async function saveDepartment(event: SubmitEvent) {
    event.preventDefault()
    const data = Object.fromEntries(new FormData(event.currentTarget as HTMLFormElement))
    const payload = { name: String(data.name || ""), code: String(data.code || ""), parent_id: data.parent_id ? String(data.parent_id) : null, sort_order: Number(data.sort_order || 0) }
    try {
      if (departmentForm()?.id) await patch("/admin/departments/" + departmentForm()!.id, payload)
      else await post("/admin/departments", payload)
      setDepartmentForm(undefined)
      await refresh()
      app.notify("部门信息已保存。")
    } catch (cause) { setError(safeMessage((cause as Error).message)) }
  }
  async function deleteDepartment(item: Department) {
    if (!window.confirm(`确定删除部门“${item.name}”吗？`)) return
    try { await remove("/admin/departments/" + item.id); await refresh(); app.notify("部门已删除。") }
    catch (cause) { app.notify(safeMessage((cause as Error).message), "error") }
  }
  async function showInvocation(item: Invocation) {
    try { setSelectedInvocation(await api<Invocation>("/admin/invocations/" + item.id)) }
    catch (cause) { app.notify(safeMessage((cause as Error).message), "error") }
  }

  return <div class="police-admin-page">
    <Switch>
      <Match when={props.section === "models"}><AdminHero icon="skill" title="模型管理" text="统一配置平台可用大模型，控制接入方式、状态与可选范围。" action={<Button variant="primary" icon="plus" onClick={() => { setConnectionState("idle"); setModelForm({ enabled: true, supports_tools: true, access_mode: "api", context_length: 131072 }) }}>新增模型</Button>} /></Match>
      <Match when={props.section === "users"}><AdminHero icon="users" title="用户与部门" text="维护民警账号、所属部门与角色，支持权限边界与能力范围控制。" /></Match>
      <Match when={props.section === "audit"}><AdminHero icon="clock" title="调用审计" text="记录模型、Skill 与插件调用链路，支持问题追溯与安全审计。" action={<a class="button" href={download("/admin/invocations/export" + (query().trim() ? "?query=" + encodeURIComponent(query().trim()) : ""))} download="">导出记录</a>} /></Match>
    </Switch>
    <ErrorLine message={error()} />
    <Show when={props.section === "models"}><ModelsPage models={shownModels()} query={query()} setQuery={setQuery} edit={(item) => { setConnectionState("idle"); setModelForm(item) }} test={testModel} setEnabled={setModelEnabled} /></Show>
    <Show when={props.section === "users"}><UsersPage users={shownUsers()} departments={shownDepartments()} summary={userSummary()} query={query()} setQuery={setQuery} departmentsMode={showDepartments()} setDepartmentsMode={setShowDepartments} departmentsWritable={app.user().role === "super_admin"} editUser={setUserForm} editDepartment={setDepartmentForm} deleteDepartment={deleteDepartment} resetPassword={resetUserPassword} disableUser={disableUser} /></Show>
    <Show when={props.section === "audit"}><AuditPage items={shownInvocations()} total={auditTotal()} query={query()} setQuery={setQuery} show={showInvocation} /></Show>

    <Show when={modelForm()}><Modal title={modelForm()?.id ? "编辑模型" : "新增模型"} text="配置平台可调用的大模型信息与接入方式" wide onClose={() => setModelForm(undefined)}><form ref={modelFormElement} class="prototype-model-form" onSubmit={saveModel}><div class="form-grid"><Field label="模型名称" required><input name="name" required value={modelForm()?.name || ""} placeholder="请输入模型名称，如 Qwen3-32B-Instruct" /></Field><Field label="Provider" required><input name="provider" required value={modelForm()?.provider || ""} placeholder="例如 OpenAI、DeepSeek 或本地服务" /></Field><Field label="Model ID" required><input name="model_id" required value={modelForm()?.model_id || ""} placeholder="请输入模型的 ID" /></Field><Field label="Base URL" required><input name="base_url" type="url" required value={modelForm()?.base_url || ""} placeholder="请输入 Base URL，如 https://api.example.com/v1" /></Field><Field label="API Key"><div class="model-key-row"><input name="api_key" type="password" placeholder={modelForm()?.api_key_configured ? "已配置，留空保持不变" : "无鉴权服务可留空"} /><Button type="button" icon="refresh" onClick={() => void testDraftConnection()}>连接测试</Button></div><small class={"connection-result " + connectionState()}>{connectionState() === "testing" ? "正在测试连接..." : connectionState() === "success" ? "● 连接成功" : "● 尚未测试"}</small></Field><Field label="上下文长度"><input name="context_length" type="number" min="256" max="2000000" value={modelForm()?.context_length ?? 131072} /></Field></div><div class="model-options-grid"><div><strong>接入方式</strong><div class="radio-cards"><label><input type="radio" name="access_mode" value="api" checked={modelForm()?.access_mode !== "local"} /> API 接入</label><label><input type="radio" name="access_mode" value="local" checked={modelForm()?.access_mode === "local"} /> 本地部署</label></div></div><OptionSwitch name="supports_tools" title="是否支持工具调用" text="支持 Function Call、工具调用等能力" checked={modelForm()?.supports_tools !== false} /><OptionSwitch name="is_default" title="默认模型" text="新建对话时优先使用" checked={!!modelForm()?.is_default} /><OptionSwitch name="enabled" title="状态" text="停用后普通用户不可选择" checked={modelForm()?.enabled !== false} /></div><Field label="模型说明"><textarea name="description" rows="3" value={modelForm()?.description || ""} placeholder="请输入模型简介、能力特点或使用说明..." /></Field><div class="modal-actions"><Button type="button" onClick={() => setModelForm(undefined)}>取消</Button><Button type="submit" variant="primary">保存模型</Button></div></form></Modal></Show>
    <Show when={userForm()}><Modal title={userForm()?.id ? "编辑用户" : "新增用户"} wide onClose={() => setUserForm(undefined)}><form onSubmit={saveUser}><div class="form-grid"><Field label="账号" required><input name="username" required disabled={!!userForm()?.id} value={userForm()?.username || ""} /></Field><Field label="初始密码"><input name="password" type="password" minlength="12" /></Field><Field label="姓名"><input name="display_name" value={userForm()?.display_name || ""} /></Field><Field label="警号"><input name="police_no" value={userForm()?.police_no || ""} /></Field><Field label="部门"><select name="department_id"><option value="">未分配</option><For each={shownDepartments()}>{(item) => <option value={item.id} selected={item.id === userForm()?.department_id}>{item.name}</option>}</For></select></Field><Field label="警务职务"><input name="position" value={userForm()?.position || ""} /></Field><Field label="系统权限"><select name="system_role"><option value="user">普通用户</option><option value="admin">管理员</option></select></Field></div><label><input name="active" type="checkbox" checked={userForm()?.active !== false} /> 启用账号</label><div class="modal-actions"><Button type="button" onClick={() => setUserForm(undefined)}>取消</Button><Button type="submit" variant="primary">保存用户</Button></div></form></Modal></Show>
    <Show when={departmentForm()}><Modal title={departmentForm()?.id ? "编辑部门" : "新增部门"} onClose={() => setDepartmentForm(undefined)}><form onSubmit={saveDepartment}><Field label="部门名称" required><input name="name" required value={departmentForm()?.name || ""} /></Field><Field label="组织编码"><input name="code" value={departmentForm()?.code || ""} /></Field><Field label="上级部门"><select name="parent_id"><option value="">无</option><For each={shownDepartments().filter((item) => item.id !== departmentForm()?.id)}>{(item) => <option value={item.id} selected={item.id === departmentForm()?.parent_id}>{item.name}</option>}</For></select></Field><Field label="排序"><input name="sort_order" type="number" value={departmentForm()?.sort_order ?? 0}/></Field><div class="modal-actions"><Button type="button" onClick={() => setDepartmentForm(undefined)}>取消</Button><Button type="submit" variant="primary">保存部门</Button></div></form></Modal></Show>
    <Show when={resetPasswordValue()}><Modal title="密码已重置" text="新初始密码仅在本次响应中显示，请立即通过安全渠道交付。" onClose={() => setResetPasswordValue("")}><Field label="新初始密码"><input readonly value={resetPasswordValue()} /></Field><div class="modal-actions"><Button onClick={() => void navigator.clipboard.writeText(resetPasswordValue())}>复制密码</Button><Button variant="primary" onClick={() => setResetPasswordValue("")}>我已保存</Button></div></Modal></Show>
    <Show when={selectedInvocation()}>{item => <Modal title="调用详情" text={`执行 ${item().run_id}`} wide onClose={() => setSelectedInvocation(undefined)}><dl class="invocation-detail"><div><dt>用户</dt><dd>{item().display_name || item().username}</dd></div><div><dt>部门</dt><dd>{item().department_name || "—"}</dd></div><div><dt>模型</dt><dd>{item().model_name || item().model_id || "—"}</dd></div><div><dt>状态</dt><dd><Status value={item().status}/></dd></div><div><dt>请求类型</dt><dd>{item().query_summary}</dd></div><div><dt>核验证据</dt><dd>{item().record_count} 项</dd></div><div><dt>选择插件</dt><dd>{item().plugin_ids?.join("、") || "—"}</dd></div><div><dt>实际插件</dt><dd>{item().actual_plugin_ids?.join("、") || "—"}</dd></div></dl><Show when={item().steps?.length}><div class="invocation-steps"><For each={item().steps}>{step => <div><Status value={step.status}/><strong>{step.name}</strong><span>{step.output_summary || step.input_summary}</span></div>}</For></div></Show></Modal>}</Show>
  </div>
}

function ModelsPage(props: { models: Model[]; query: string; setQuery: (value: string) => void; edit: (item: Model) => void; test: (item: Model) => Promise<void> | void; setEnabled: (item: Model, enabled: boolean) => Promise<void> | void }) {
  return <section class="admin-content-card"><FilterBar query={props.query} setQuery={props.setQuery} placeholder="搜索模型名称、ID 或描述..." selects={["全部 Provider", "全部状态"]} /><Table><thead><tr><th>模型名称</th><th>Provider</th><th>Model ID</th><th>上下文长度</th><th>接入方式</th><th>状态</th><th>默认</th><th>更新时间</th><th>操作</th></tr></thead><tbody><For each={props.models}>{(item) => <tr><td><div class="model-cell"><span class="model-logo">{item.name.slice(0, 1)}</span><span><strong>{item.name}</strong><small>{item.description}</small></span></div></td><td><span class="provider-tag">{item.provider || "其他"}</span></td><td>{item.model_id}</td><td>{Math.round((item.context_length ?? 131072) / 1024)}K</td><td><span class="access-tag">{item.access_mode === "local" ? "本地部署" : "API 接入"}</span></td><td><div class="status-actions"><Button class={item.enabled ? "selected" : ""} disabled={item.enabled} onClick={() => void props.setEnabled(item, true)}>启用</Button><Button class={!item.enabled ? "selected danger-selected" : ""} disabled={!item.enabled} onClick={() => void props.setEnabled(item, false)}>关停</Button></div></td><td>{item.is_default ? <span class="default-tag">默认模型</span> : "—"}</td><td>{formatDate(item.updated_at)}</td><td><div class="row-actions"><Button onClick={() => props.edit(item)}>编辑</Button><Button variant="ghost" onClick={() => void props.test(item)}>测试</Button></div></td></tr>}</For></tbody></Table><TableFooter total={props.models.length} /></section>
}
function UsersPage(props: { users: User[]; departments: Department[]; summary: { users: number; departments: number; enabled: number }; query: string; setQuery: (value: string) => void; departmentsMode: boolean; setDepartmentsMode: (value: boolean) => void; departmentsWritable: boolean; editUser: (item: Partial<User>) => void; editDepartment: (item: Partial<Department>) => void; deleteDepartment: (item: Department) => Promise<void> | void; resetPassword: (item: User) => Promise<void> | void; disableUser: (item: User) => Promise<void> | void }) {
  return <><div class="admin-summary-cards"><Summary icon="users" label="用户总数" value={props.summary.users} note="当前接口实时数据" /><Summary icon="skill" label="部门总数" value={props.summary.departments} note="当前接口实时数据" /><Summary icon="shield" label="启用账号" value={props.summary.enabled} note="当前接口实时数据" /></div><section class="admin-content-card"><div class="subsection-tabs"><button class={!props.departmentsMode ? "active" : ""} onClick={() => props.setDepartmentsMode(false)}>用户管理</button><button class={props.departmentsMode ? "active" : ""} onClick={() => props.setDepartmentsMode(true)}>部门管理</button></div><div class="admin-list-toolbar"><FilterBar query={props.query} setQuery={props.setQuery} placeholder="搜索姓名、警号或部门..." selects={["全部部门", "全部角色", "全部状态"]} compact /><Show when={!props.departmentsMode || props.departmentsWritable}><Button variant="primary" icon="plus" onClick={() => props.departmentsMode ? props.editDepartment({ sort_order: 0 }) : props.editUser({ active: true, role: "user" })}>{props.departmentsMode ? "新增部门" : "新增用户"}</Button></Show></div><Show when={!props.departmentsMode} fallback={<Show when={props.departments.length} fallback={<p class="empty-copy">暂无部门。</p>}><Table><thead><tr><th>部门名称</th><th>组织编码</th><th>上级部门</th><th>排序</th><th>操作</th></tr></thead><tbody><For each={props.departments}>{(item) => <tr><td><strong>{item.name}</strong></td><td>{item.code || "—"}</td><td>{props.departments.find((value) => value.id === item.parent_id)?.name || "—"}</td><td>{item.sort_order}</td><td><Show when={props.departmentsWritable} fallback="只读"><div class="row-actions"><Button onClick={() => props.editDepartment(item)}>编辑</Button><Button variant="danger" onClick={() => void props.deleteDepartment(item)}>删除</Button></div></Show></td></tr>}</For></tbody></Table></Show>}><Table><thead><tr><th>姓名</th><th>警号</th><th>所属部门</th><th>角色</th><th>账号状态</th><th>最近登录</th><th>操作</th></tr></thead><tbody><For each={props.users}>{(item, index) => <tr><td><div class="officer-cell"><span class="officer-avatar">警</span><strong>{item.display_name || item.username}</strong></div></td><td>{item.police_no || item.username}</td><td>{item.department?.name || "—"}</td><td><span class={index() === 3 ? "role-tag leader" : "role-tag"}>{item.position || item.role}</span></td><td><Status value={item.active ? "enabled" : "disabled"} /></td><td>{formatDate(item.last_login_at)}</td><td><div class="row-actions"><Button onClick={() => props.editUser(item)}>编辑</Button><Button variant="ghost" onClick={() => void props.resetPassword(item)}>重置密码</Button><Button variant="danger" disabled={item.active === false} onClick={() => void props.disableUser(item)}>禁用</Button></div></td></tr>}</For></tbody></Table><TableFooter total={props.users.length} /></Show></section></>
}
function AuditPage(props: { items: Invocation[]; total: number; query: string; setQuery: (value: string) => void; show: (item: Invocation) => Promise<void> | void }) {
  return <section class="admin-content-card"><FilterBar query={props.query} setQuery={props.setQuery} placeholder="搜索用户名或脱敏摘要..." selects={["开始日期　~　结束日期", "全部模型", "全部状态"]} /><Table><thead><tr><th>时间</th><th>用户</th><th>部门</th><th>模型</th><th>请求类型</th><th>证据数</th><th>结果状态</th><th>操作</th></tr></thead><tbody><For each={props.items}>{(item) => <tr><td>{formatDate(item.created_at ?? item.created)}</td><td>{item.display_name || item.username}</td><td>{item.department_name || "—"}</td><td>{item.model_name || "—"}</td><td><span class="audit-question" title={item.query_summary}>{item.query_summary}</span></td><td>{item.record_count}</td><td><Status value={item.status} /></td><td><Button onClick={() => void props.show(item)}>查看详情</Button></td></tr>}</For></tbody></Table><TableFooter total={props.total} /></section>
}
function AdminHero(props: { icon: string; title: string; text: string; action?: JSX.Element }) { return <section class="admin-page-hero"><div class="admin-page-title"><span><Icon name={props.icon} size={28} /></span><div><h1>{props.title}</h1><p>{props.text}</p></div></div>{props.action}</section> }
function FilterBar(props: { query: string; setQuery: (value: string) => void; placeholder: string; selects: string[]; compact?: boolean }) { return <div class={"prototype-filter-bar " + (props.compact ? "compact" : "")}><label class="search-box"><Icon name="search" size={17} /><input value={props.query} onInput={(event) => props.setQuery(event.currentTarget.value)} placeholder={props.placeholder} /></label><For each={props.selects}>{(label) => <select aria-label={label}><option>{label}</option></select>}</For><Button icon="refresh">重置</Button></div> }
function Summary(props: { icon: string; label: string; value: number; note: string }) { return <div><span class="summary-icon"><Icon name={props.icon} /></span><span><small>{props.label}</small><strong>{props.value}</strong><em>{props.note}</em></span></div> }
function TableFooter(props: { total: number }) { return <div class="prototype-pagination"><strong>共 {props.total} 条记录</strong><div><button disabled>‹</button><button class="active">1</button><button>2</button><button>3</button><button>›</button><select><option>10 条/页</option></select></div></div> }
function Table(props: { children: JSX.Element }) { return <div class="admin-table-scroll"><table class="prototype-table">{props.children}</table></div> }
function OptionSwitch(props: { name: string; title: string; text: string; checked: boolean }) { return <label class="switch-option"><span><strong>{props.title}</strong><small>{props.text}</small></span><input name={props.name} type="checkbox" checked={props.checked} /></label> }
function filter<T>(items: T[], query: string, content: (item: T) => string) { const value = query.trim().toLowerCase(); return value ? items.filter((item) => content(item).toLowerCase().includes(value)) : items }
function flattenDepartments(items: Department[]): Department[] { return items.flatMap((item) => [item, ...flattenDepartments(item.children ?? [])]) }
