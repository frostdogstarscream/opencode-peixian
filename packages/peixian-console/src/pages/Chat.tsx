import EvidencePanel, { type Evidence } from "../EvidencePanel"
import { createEffect, createMemo, createSignal, For, onCleanup, Show } from "solid-js"
import { api, ApiError, list, patch, post, remove, safeMessage } from "../api"
import { Button, Empty, ErrorLine, Field, Icon, Markdown, Modal, Spinner, Status } from "../components"
import { useConsole } from "../context"
import BusinessConfirmations from "../BusinessConfirmations"
import type { FileItem, Message, Model, Session, Skill, Plugin } from "../types"
import { createRefreshScheduler, createResponseGuard } from "../refresh"
import { canSend, canObserve, canContinue, runtimeNotice } from "../runtime-view"
import Skills from "./Skills"
import Plugins from "./Plugins"
import Files from "./Files"
import { capabilityCatalog, type CapabilityEntry } from "../capability-catalog"
export default function Chat() {
  const app = useConsole()
  const [sessions, setSessions] = createSignal<Session[]>([])
  const [evidence, setEvidence] = createSignal<Evidence>()
  const [evidenceError, setEvidenceError] = createSignal("")
  const [messages, setMessages] = createSignal<Message[]>([])
  const [expandedTools, setExpandedTools] = createSignal<Record<string, boolean>>({})
  const [models, setModels] = createSignal<Model[]>([])
  const [files, setFiles] = createSignal<FileItem[]>([])
  const [plugins, setPlugins] = createSignal<Plugin[]>([])
  const [manager, setManager] = createSignal<"skills" | "plugins" | "files">()
  const [skills, setSkills] = createSignal<Skill[]>([])
  const [selected, setSelected] = createSignal<string>()
  const [model, setModel] = createSignal("")
  const [draft, setDraft] = createSignal("")
  const [selectedFiles, setSelectedFiles] = createSignal<string[]>([])
  const [selectedSkills, setSelectedSkills] = createSignal<string[]>([])
  const [busy, setBusy] = createSignal(false)
  const [sending, setSending] = createSignal(false)
  const [uncertain, setUncertain] = createSignal(false)
  const [loading, setLoading] = createSignal(true)
  const [error, setError] = createSignal("")
  const [picker, setPicker] = createSignal<"files" | "capabilities">()
  const [search, setSearch] = createSignal("")
  const [showHistory, setShowHistory] = createSignal(false)
  const [rename, setRename] = createSignal<Session>()
  const [title, setTitle] = createSignal("")
  let scroll!: HTMLDivElement
  let textarea!: HTMLTextAreaElement
  const selection = createResponseGuard(selected)
  let disposed = false
  const [capabilityKind, setCapabilityKind] = createSignal<"all" | "skill" | "plugin">("all")
  const shownSessions = sessions
  const shownModels = models
  const shownCapabilities = createMemo(() => capabilityCatalog(skills(), plugins()))
  const slashQuery = createMemo(() => draft().match(/^\s*\/([^\s]*)$/)?.[1]?.toLowerCase())
  const slashCapabilities = createMemo(() => slashQuery() === undefined ? [] : shownCapabilities().filter((item) =>
    !slashQuery() || (item.name + (item.description ?? "")).toLowerCase().includes(slashQuery()!)).slice(0, 7))
  const active = createMemo(() => sessions().find((s) => s.id === selected()))
  const ready = createMemo(() => canSend(app.user().runtime))
  const available = createMemo(() => canObserve(app.user().runtime))
  const continuing = createMemo(() => canContinue(app.user().runtime))
  let observationGeneration = 0
  const account = createMemo(() => app.user().id)
  createEffect(() => { account(); available(); observationGeneration++; selection.invalidate(); setEvidence(undefined); setEvidenceError("") })
  const notice = createMemo(() => runtimeNotice(app.user().runtime))
  const interval = () => (document.hidden ? 15000 : 500)
  const messageRefresh = createRefreshScheduler(
    async (signal) => {
      const id = selected(),
        current = selection.capture()
      const generation = observationGeneration
      if (!available() || !id) return
      try {
        const data = await list<Message>("/sessions/" + id + "/messages", { signal })
        if (!disposed && current() && available() && generation === observationGeneration) setMessages(data)
        try {
          const facts = await api<Evidence>("/sessions/" + id + "/evidence", { signal })
          if (!disposed && current() && available() && generation === observationGeneration) { setEvidence(facts); setEvidenceError("") }
        } catch {
          if (!disposed && current() && available() && generation === observationGeneration) { setEvidence(undefined); setEvidenceError("资料视图暂未读取成功，请重试。") }
        }
      } catch (error) {
        if (!disposed && current() && available() && generation === observationGeneration) setError((error as Error).message)
      }
    },
    { interval },
  )
  const sessionRefresh = createRefreshScheduler(
    async (signal) => {
      if (!available()) return
      const generation = observationGeneration
      const values = await list<Session>("/sessions", { signal })
      if (disposed || !available() || generation !== observationGeneration) return
      setSessions(values)
      if (selected())
        setBusy(["busy", "retry"].includes(values.find((item) => item.id === selected())?.status ?? "idle"))
    },
    { interval, onError: (error) => setError((error as Error).message) },
  )
  const modelRefresh = createRefreshScheduler(
    async (signal) => {
      const values = await list<Model>("/models", { signal })
      if (disposed) return
      setModels(values)
      if (!values.some((item) => item.id === model()))
        setModel(values.find((item) => item.is_default)?.id ?? values[0]?.id ?? "")
    },
    { interval },
  )
  const fileRefresh = createRefreshScheduler(
    async (signal) => {
      if (!available()) return
      const generation = observationGeneration
      const values = await list<FileItem>("/files", { signal })
      if (!disposed && available() && generation === observationGeneration) {
        setFiles(values)
        setSelectedFiles((current) => current.filter((id) => values.some((item) => item.id === id && item.status === "ready")))
      }
    },
    { interval },
  )
  const skillRefresh = createRefreshScheduler(
    async (signal) => {
      const values = await list<Skill>("/skills", { signal })
      if (!disposed) {
        setSkills(values)
        setSelectedSkills((current) => current.filter((id) => values.some((item) => item.id === id && item.enabled)))
      }
    },
    { interval },
  )
  const pluginRefresh = createRefreshScheduler(async (signal) => {
    const values = await list<Plugin>("/plugins", { signal })
    if (!disposed) setPlugins(values)
  }, { interval, onError: (error) => setError((error as Error).message) })
  const refresh = async () => {
    await Promise.all([sessionRefresh.request(), messageRefresh.request()])
  }
  const calibrate = async () => {
    await Promise.all([refresh(), modelRefresh.request(), fileRefresh.request(), skillRefresh.request(), pluginRefresh.request()])
    if (!disposed) setLoading(false)
  }
  const subscriptions = [
    app.subscribe("messages", (event) => {
      if (!event.session_id || event.session_id === selected()) void messageRefresh.request()
    }),
    app.subscribe("sessions", () => {
      void sessionRefresh.request()
    }),
    app.subscribe("models", () => {
      void modelRefresh.request()
    }),
    app.subscribe("files", () => {
      void fileRefresh.request()
    }),
    app.subscribe("skills", () => {
      void skillRefresh.request()
    }),
    app.subscribe("plugins", () => { void pluginRefresh.request() }),
    app.subscribe("runtime", () => {
      void calibrate()
    }),
  ]
  createEffect(() => {
    available()
    void calibrate()
  })
  const poll = setInterval(() => {
    if (busy() && !document.hidden) void refresh()
  }, 2000)
  const calibration = setInterval(() => {
    if (!document.hidden) void calibrate()
  }, 30000)
  onCleanup(() => {
    disposed = true
    selection.invalidate()
    clearInterval(poll)
    clearInterval(calibration)
    subscriptions.forEach((dispose) => dispose())
    ;[messageRefresh, sessionRefresh, modelRefresh, fileRefresh, skillRefresh, pluginRefresh].forEach((scheduler) =>
      scheduler.dispose(),
    )
  })
  createEffect(() => {
    messages()
    busy()
    queueMicrotask(() => {
      if (scroll) scroll.scrollTop = scroll.scrollHeight
    })
  })
  async function choose(id: string) {
    if (sending()) return
    selection.invalidate()
    setSelected(id)
    setMessages([])
    setEvidence(undefined)
    setEvidenceError("")
    setError("")
    setShowHistory(false)
    setBusy(["busy", "retry"].includes(sessions().find((item) => item.id === id)?.status ?? "idle"))
    try {
      await messageRefresh.request()
    } catch (error) {
      setError((error as Error).message)
    }
  }
  function fresh() {
    if (sending()) return
    selection.invalidate()
    setSelected(undefined)
    setMessages([])
    setEvidence(undefined)
    setEvidenceError("")
    if (!uncertain()) setDraft("")
    setSelectedFiles([])
    setSelectedSkills([])
    setError("")
    setShowHistory(false)
    setBusy(false)
    textarea?.focus()
  }
  async function send() {
    if (!draft().trim() || sending() || uncertain() || busy() || !ready() || !models().length) return
    const text = draft()
    const payload = { text: text.trim(), model_id: model() || undefined, skill_ids: [...selectedSkills()], file_ids: [...selectedFiles()] }
    const uid = app.user().id
    setSending(true)
    setError("")
    let submitting = false
    let accepted = false
    try {
      let id = selected()
      if (!id) {
        const session = await post<Session>("/sessions", { title: text.trim().slice(0, 35) })
        if (disposed || app.user().id !== uid) return
        id = session.id
        selection.invalidate()
        setSelected(id)
      }
      if (!ready()) return
      submitting = true
      const result = await post<{ accepted: boolean }>("/sessions/" + id + "/messages", payload)
      if (disposed || app.user().id !== uid) return
      if (result?.accepted !== true) throw new ApiError("提交结果待确认，请核对历史记录。", 0, "unknown_submission")
      accepted = true
      if (draft() === text) setDraft("")
      setBusy(true)
      // run_id is not a durable Run API in the milestone; refresh real history only.
      await refresh()
    } catch (error) {
      if (disposed || app.user().id !== uid) return
      if (accepted) {
        setError("消息已受理，历史记录暂未刷新；请等待恢复，不要重复发送。")
      } else if (submitting && error instanceof ApiError && (error.status === 0 || error.status >= 500)) {
        setUncertain(true)
        setError("提交结果待确认，草稿已保留。请先检查历史和当前任务状态，避免重复调用。")
      } else setError((error as Error).message)
    } finally {
      if (!disposed && app.user().id === uid) setSending(false)
    }
  }
  async function abort() {
    if (!continuing() || !selected()) return
    const id = selected(), current = selection.capture(), uid = app.user().id
    try {
      await post("/sessions/" + id + "/abort")
      if (disposed || !current() || app.user().id !== uid) return
      await refresh()
      app.notify("已提交停止请求，正在核对任务状态。")
    } catch (error) {
      if (disposed || !current() || app.user().id !== uid) return
      setError((error as Error).message)
    }
  }
  async function deleteSession(item: Session) {
    if (sending()) return
    if (!window.confirm("确定删除这条对话及其消息吗？")) return
    try {
      await remove("/sessions/" + item.id)
      if (selected() === item.id) fresh()
      await refresh()
    } catch (error) {
      app.notify((error as Error).message, "error")
    }
  }
  async function saveTitle(event: SubmitEvent) {
    event.preventDefault()
    try {
      await patch("/sessions/" + rename()!.id, { title: title().trim() })
      setRename(undefined)
      await refresh()
    } catch (error) {
      app.notify((error as Error).message, "error")
    }
  }
  function toggle(id: string, type: "files" | "skills") {
    const setter = type === "files" ? setSelectedFiles : setSelectedSkills
    const current = type === "files" ? selectedFiles() : selectedSkills()
    if (!current.includes(id) && current.length >= 5) {
      app.notify("每次最多选择五个文件和五个技能。", "error")
      return
    }
    setter(current.includes(id) ? current.filter((value) => value !== id) : [...current, id])
  }
  function manage(value: "files" | "skills" | "plugins") {
    setPicker(undefined)
    setManager(value)
  }
  function toggleCapability(item: CapabilityEntry) {
    if (item.kind === "plugin") return manage("plugins")
    toggle(item.id, "skills")
  }
  function chooseSlashCapability(item: CapabilityEntry) {
    toggleCapability(item)
    setDraft("")
    queueMicrotask(() => textarea?.focus())
  }
  return (
    <div class="chat-layout">
      <aside class={"history-panel " + (showHistory() ? "visible" : "")}>
        <div class="history-head">
          <strong>研判记录</strong>
          <button class="icon-button" aria-label="新建研判" onClick={fresh}>
            <Icon name="plus" />
          </button>
        </div>
        <Button class="new-chat" icon="plus" onClick={fresh}>
          新建研判
        </Button>
        <label class="search-box">
          <Icon name="search" size={16} />
          <input
            aria-label="搜索对话"
            placeholder="搜索对话"
            value={search()}
            onInput={(event) => setSearch(event.currentTarget.value)}
          />
        </label>
        <div class="history-list">
          <Show
            when={!loading()}
            fallback={
              <div class="loading">
                <Spinner />
              </div>
            }
          >
            <For
              each={shownSessions().filter((item) => item.title?.includes(search()))}
              fallback={<p class="quiet">你的研判记录会保存在这里</p>}
            >
              {(item) => (
                <div class={"history-item " + (selected() === item.id ? "selected" : "")}>
                  <button onClick={() => void choose(item.id)}>
                    <Icon name="chat" size={16} />
                    <span>{item.title || "未命名对话"}</span>
                  </button>
                  <div class="history-actions">
                    <button
                      class="icon-button"
                      aria-label="重命名对话"
                      onClick={() => {
                        setRename(item)
                        setTitle(item.title)
                      }}
                    >
                      <Icon name="edit" size={14} />
                    </button>
                    <button class="icon-button" aria-label="删除对话" onClick={() => void deleteSession(item)}>
                      <Icon name="trash" size={14} />
                    </button>
                  </div>
                </div>
              )}
            </For>
          </Show>
        </div>
        <div class="history-foot">
          <Icon name="lock" size={13} />
          仅你可见
        </div>
      </aside>
      <section class="conversation">
        <div class="conversation-head">
          <div>
            <button
              class="icon-button history-toggle"
              aria-label="显示对话记录"
              onClick={() => setShowHistory(!showHistory())}
            >
              <Icon name="clock" />
            </button>
            <h2>{active()?.title || "新建研判"}</h2>
          </div>
          <div class="conversation-head-actions">
            <div class="model-choice">
              <span class="model-dot" />
              <select
                aria-label="选择授权模型"
                value={model() || shownModels()[0]?.id}
                disabled={busy() || sending()}
                onChange={(event) => setModel(event.currentTarget.value)}
              >
                <For each={shownModels()}>
                  {(item) => (
                    <option value={item.id}>
                      {item.name}
                      {item.is_default ? " · 默认" : ""}
                    </option>
                  )}
                </For>
              </select>
            </div>
            <span class="quiet">对话与结果仅本人可见</span>
          </div>
        </div>
        <Show when={notice()}><div class="runtime-banner" role="status"><Icon name="clock" size={17} /><span>{notice()}</span></div></Show>
        <Show when={!models().length && !loading()}><div class="runtime-banner">暂无获授权模型，请联系管理员配置。</div></Show>
        <div class="messages-scroll" ref={scroll}>
          <EvidencePanel summary value={evidence()} onRetry={() => void messageRefresh.request()} />
          <Show
            when={messages().length}
            fallback={<div class="conversation-blank" aria-label="空白研判对话区" />}
          >
            <div class="messages">
              <For each={messages()}>
                {(message) => (
                  <article id={"message-" + message.info.id} class={"message " + (message.info.role === "user" ? "user" : "assistant")}>
                    <div class="message-avatar">
                      <Show when={message.info.role === "user"} fallback={<Icon name="skill" size={17} />}>
                        {app.user().username.slice(0, 1).toUpperCase()}
                      </Show>
                    </div>
                    <div class="message-content">
                      <div class="message-author">{message.info.role === "user" ? "你" : "智能助手"}</div>
                      <For each={message.parts}>
                        {(part) => (
                          <>
                            <Show when={part.type === "text" && part.text}>
                              <Markdown text={part.text ?? ""} />
                            </Show>
                            <Show when={part.type === "tool"}>
                              <details
                                class="tool-detail"
                                open={expandedTools()[message.info.id + ":" + (part.id ?? part.tool)] ?? false}
                                onToggle={(event) => {
                                  const key = message.info.id + ":" + (part.id ?? part.tool)
                                  const open = event.currentTarget.open
                                  setExpandedTools((current) =>
                                    current[key] === open ? current : { ...current, [key]: open },
                                  )
                                }}
                              >
                                <summary>
                                  <Icon name={part.state?.status === "completed" ? "check" : "clock"} size={14} />
                                  <span>{safeMessage(part.state?.title || part.tool, "处理业务资料")}</span>
                                  <Status value={part.state?.status} />
                                </summary>
                                <For
                                  each={[
                                    { title: "输入条件", fields: part.details?.inputs },
                                    { title: "处理结果", fields: part.details?.outputs },
                                  ]}
                                >
                                  {(section) => (
                                    <Show when={Object.keys(section.fields ?? {}).length}>
                                      <div class="business-detail">
                                        <strong>{section.title}</strong>
                                        <dl>
                                          <For each={Object.entries(section.fields ?? {})}>
                                            {([name, value]) => (
                                              <div>
                                                <dt>{safeMessage(name)}</dt>
                                                <dd>
                                                  {safeMessage(
                                                    typeof value === "boolean" ? (value ? "是" : "否") : String(value),
                                                  )}
                                                </dd>
                                              </div>
                                            )}
                                          </For>
                                        </dl>
                                      </div>
                                    </Show>
                                  )}
                                </For>
                                <Show when={part.state?.error}>
                                  <ErrorLine message={part.state?.error} />
                                </Show>
                              </details>
                            </Show>
                          </>
                        )}
                      </For>
                      <Show when={message.info.error}>
                        <ErrorLine
                          message={
                            message.info.error?.data?.message ||
                            message.info.error?.message ||
                            "本次生成未完成，请检查工作空间状态后重试。"
                          }
                        />
                      </Show>
                    </div>
                  </article>
                )}
              </For>
              <Show when={busy() && available()}>
                <div class="thinking">
                  <Spinner />
                  <span>正在整理思路与资料…</span>
                  <button disabled={!continuing()} onClick={abort}>停止</button>
                </div>
              </Show>
            </div>
          </Show>
        </div>
        <div class="composer-area">
          <Show when={!available() && selected()}><p role="status">状态暂不可更新，最后已知任务状态和历史内容已保留。</p></Show>
          <BusinessConfirmations sessionID={selected()} available={available()} canContinue={continuing()} onAnswered={() => void refresh()} />
          <ErrorLine message={error()} />
          <Show when={uncertain()}><div class="runtime-banner" role="status"><span>结果待确认。刷新不会自动重发本次问题。</span><Button onClick={() => void refresh()}>刷新历史</Button><Button onClick={() => { if (window.confirm("请确认已核对原会话历史及任务状态。重新发送可能产生重复调用，是否解除发送保护？")) { setUncertain(false); setError("") } }}>已核对，解除保护</Button></div></Show>
          <Show when={selectedFiles().length || selectedSkills().length}>
            <div class="selection-chips">
              <For each={selectedFiles()}>
                {(id) => (
                  <button onClick={() => toggle(id, "files")}>
                    <Icon name="file" size={13} />
                    {files().find((x) => x.id === id)?.name ?? "已选文件"}
                    <Icon name="close" size={12} />
                  </button>
                )}
              </For>
              <For each={selectedSkills()}>
                {(id) => (
                  <button onClick={() => toggle(id, "skills")}>
                    <Icon name="skill" size={13} />
                    {shownCapabilities().find((x) => x.id === id)?.name ?? skills().find((x) => x.id === id)?.name ?? "已选技能"}
                    <Icon name="close" size={12} />
                  </button>
                )}
              </For>

            </div>
          </Show>
          <Show when={slashQuery() !== undefined}>
            <div class="slash-command-menu">
              <div class="slash-command-head"><strong>/ 选择技能</strong><span>输入名称可筛选</span></div>
              <For each={slashCapabilities()} fallback={<p>没有匹配的可用能力</p>}>
                {(item) => <button onClick={() => chooseSlashCapability(item)}><span class={"slash-kind " + item.kind}><Icon name={item.kind === "skill" ? "skill" : "plugin"} size={16} /></span><span><strong>{item.name}</strong><small>{item.description}</small></span><em>{item.kind === "skill" ? "Skill" : "插件"}</em></button>}
              </For>
            </div>
          </Show>
          <div class="composer">
            <textarea
              ref={textarea}
              aria-label="输入消息"
              maxlength={32000}
              placeholder="输入研判内容，使用 / 选择已启用技能…"
              value={draft()}
              rows={3}
              onInput={(event) => setDraft(event.currentTarget.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
                  event.preventDefault()
                  void send()
                }
              }}
            />
            <div class="composer-tools">
              <div>
                <button onClick={() => setPicker("capabilities")}>
                  <Icon name="skill" size={17} />
                  能力
                </button>
                <button onClick={() => setPicker("files")}>
                  <Icon name="file" size={17} />
                  文件
                </button>
              </div>
              <Show
                when={busy() && available()}
                fallback={
                  <Button
                    variant="primary"
                    icon="send"
                    busy={sending()}
                    disabled={!draft().trim() || uncertain() || !ready() || !shownModels().length}
                    onClick={send}
                  >
                    发送
                  </Button>
                }
              >
                <Button icon="stop" disabled={!continuing()} onClick={abort}>
                  停止生成
                </Button>
              </Show>
            </div>
          </div>
          <div class="composer-hint">
            Enter 发送 · Shift + Enter 换行 <span>重要信息请结合原始资料核验</span>
          </div>
        </div>
      </section>
      <EvidencePanel value={evidence()} error={evidenceError()} onRetry={() => void messageRefresh.request()} />
<aside class="related-capabilities">
        <div class="related-capabilities-head"><div><strong>技能与插件</strong><small>个人技能与已获授权插件</small></div><span>{shownCapabilities().length}</span></div>
        <div class="capability-management-actions"><Button onClick={() => manage("skills")}>管理技能</Button><Button onClick={() => manage("plugins")}>管理插件</Button></div>
        <div class="related-capabilities-list">
          <For each={shownCapabilities()}>
            {(item, index) => <button class={selectedSkills().includes(item.id) ? "selected" : ""} onClick={() => toggleCapability(item)}><span class={"capability-icon tone-" + (index() % 5)}><Icon name={item.kind === "skill" ? "skill" : "plugin"} size={18} /></span><span><strong>{item.name}<em>v{item.version}</em></strong><small>{item.description}</small><i>{item.kind === "skill" ? "个人 Skill" : item.state}</i></span><b>{item.kind === "plugin" ? "配置" : selectedSkills().includes(item.id) ? "已选" : "使用"}</b></button>}
          </For>
        </div>
      </aside>
      <Show when={picker()}>
        {(type) => (
          <Modal
            title={type() === "files" ? "关联文件" : "能力选择"}
            text={type() === "files" ? "仅可选择已完成解析的个人文件。" : "Skill 可随消息选用。插件在个人环境应用后由助手按需调用，配置不代表已经生效。"}
            onClose={() => setPicker(undefined)}
          >
            <Show when={type() === "capabilities"}>
              <div class="capability-toolbar"><label class="search-box"><Icon name="search" size={16} /><input placeholder="搜索能力名称或描述" value={search()} onInput={(event) => setSearch(event.currentTarget.value)} /></label><div class="segmented"><button class={capabilityKind() === "all" ? "active" : ""} onClick={() => setCapabilityKind("all")}>全部</button><button class={capabilityKind() === "skill" ? "active" : ""} onClick={() => setCapabilityKind("skill")}>分析 Skill</button><button class={capabilityKind() === "plugin" ? "active" : ""} onClick={() => setCapabilityKind("plugin")}>插件工具</button></div></div>
            </Show>
            <div class="picker-list">
              <For
                each={
                  type() === "files"
                    ? files().filter((item) => ["ready", "partial"].includes(item.status ?? ""))
                    : shownCapabilities().filter((item) => (capabilityKind() === "all" || item.kind === capabilityKind()) && (!search() || (item.name + (item.description ?? "")).toLowerCase().includes(search().toLowerCase())))
                }
                fallback={
                  <Empty
                    title={type() === "files" ? "暂无可关联文件" : "暂无已启用技能"}
                    text={type() === "files" ? "请先上传并等待文件解析完成。" : "当前没有匹配的可用能力。"}
                  />
                }
              >
                {(item) => (
                  <div class="pick-row capability-row">
                    <Show when={!("kind" in item && item.kind === "plugin")} fallback={<Button onClick={() => manage("plugins")}>配置</Button>}>
                    <input
                      type="checkbox"
                      aria-label={"选择 " + item.name}
                      disabled={type() === "files" && "status" in item && item.status === "partial"}
                      checked={(type() === "files" ? selectedFiles() : selectedSkills()).includes(item.id)}
                      onChange={() => type() === "files" ? toggle(item.id, "files") : "kind" in item && toggleCapability(item)}
                    />
                    </Show>
                    <Icon name={type() === "files" ? "file" : "kind" in item && item.kind === "plugin" ? "plugin" : "skill"} />
                    <span>
                      {item.name}
                      <Show when={type() === "capabilities" && "description" in item}><small>{("description" in item ? item.description : "") || "可用于当前研判任务"}</small></Show>
                      <Show when={type() === "files" && "status" in item && item.status === "partial"}>
                        <br />
                        <small class="muted">部分解析 · 请拆分重传</small>
                      </Show>
                    </span>

                  </div>
                )}
              </For>
            </div>
            <div class="modal-actions">
              <Show when={type() === "files"} fallback={<><Button onClick={() => manage("skills")}>管理技能</Button><Button onClick={() => manage("plugins")}>管理插件</Button></>}>
                <Button onClick={() => manage("files")}>上传与管理文件</Button>
              </Show>
              <Button variant="primary" onClick={() => setPicker(undefined)}>
                完成选择
              </Button>
            </div>
          </Modal>
        )}
      </Show>
      <Show when={manager()}>
        <Modal wide title={manager() === "skills" ? "个人技能管理" : manager() === "plugins" ? "授权插件管理" : "文件管理"} onClose={() => setManager(undefined)}>
          <Show when={manager() === "skills"}><Skills /></Show>
          <Show when={manager() === "plugins"}><Plugins /></Show>
          <Show when={manager() === "files"}><Files onUse={(item) => {
            if (!selectedFiles().includes(item.id)) toggle(item.id, "files")
            setManager(undefined)
            void fileRefresh.request()
          }} /></Show>
        </Modal>
      </Show>
      <Show when={rename()}>
        <Modal title="重命名对话" onClose={() => setRename(undefined)}>
          <form onSubmit={saveTitle}>
            <Field label="对话名称">
              <input
                required
                maxlength={100}
                value={title()}
                onInput={(event) => setTitle(event.currentTarget.value)}
              />
            </Field>
            <div class="modal-actions">
              <Button type="submit" variant="primary">
                保存名称
              </Button>
            </div>
          </form>
        </Modal>
      </Show>
    </div>
  )
}
