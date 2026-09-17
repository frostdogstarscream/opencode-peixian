import { createEffect, createMemo, createSignal, For, onCleanup, Show } from "solid-js"
import { api, list, patch, post, remove, safeMessage } from "../api"
import { Button, Empty, ErrorLine, Field, Icon, Markdown, Modal, Spinner, Status } from "../components"
import { useConsole } from "../context"
import BusinessConfirmations from "../BusinessConfirmations"
import type { FileItem, Message, Model, Session, Skill } from "../types"
import { createRefreshScheduler, createResponseGuard } from "../refresh"
import { canSend, runtimeNotice } from "../runtime-view"
export default function Chat() {
  const app = useConsole()
  const [sessions, setSessions] = createSignal<Session[]>([])
  const [messages, setMessages] = createSignal<Message[]>([])
  const [expandedTools, setExpandedTools] = createSignal<Record<string, boolean>>({})
  const [models, setModels] = createSignal<Model[]>([])
  const [files, setFiles] = createSignal<FileItem[]>([])
  const [skills, setSkills] = createSignal<Skill[]>([])
  const [selected, setSelected] = createSignal<string>()
  const [model, setModel] = createSignal("")
  const [draft, setDraft] = createSignal("")
  const [selectedFiles, setSelectedFiles] = createSignal<string[]>([])
  const [selectedSkills, setSelectedSkills] = createSignal<string[]>([])
  const [busy, setBusy] = createSignal(false)
  const [sending, setSending] = createSignal(false)
  const [loading, setLoading] = createSignal(true)
  const [error, setError] = createSignal("")
  const [picker, setPicker] = createSignal<"files" | "skills">()
  const [search, setSearch] = createSignal("")
  const [showHistory, setShowHistory] = createSignal(false)
  const [rename, setRename] = createSignal<Session>()
  const [title, setTitle] = createSignal("")
  let scroll!: HTMLDivElement
  let textarea!: HTMLTextAreaElement
  const selection = createResponseGuard(selected)
  let disposed = false
  const active = createMemo(() => sessions().find((s) => s.id === selected()))
  const ready = createMemo(() => canSend(app.user().runtime))
  const available = createMemo(() => app.user().runtime?.runtime_mode === "on_demand" ? app.user().runtime?.ready === true : ["ready", "draining", "updating", "applying"].includes(app.user().runtime?.status ?? ""))
  const notice = createMemo(() => runtimeNotice(app.user().runtime))
  const interval = () => (document.hidden ? 15000 : 500)
  const messageRefresh = createRefreshScheduler(
    async (signal) => {
      const id = selected(),
        current = selection.capture()
      if (!available() || !id) return
      try {
        const data = await list<Message>("/sessions/" + id + "/messages", { signal })
        if (!disposed && current()) setMessages(data)
      } catch (error) {
        if (!disposed && current()) setError((error as Error).message)
      }
    },
    { interval },
  )
  const sessionRefresh = createRefreshScheduler(
    async (signal) => {
      if (!available()) {
        setBusy(false)
        return
      }
      const values = await list<Session>("/sessions", { signal })
      if (disposed) return
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
      const values = await list<FileItem>("/files", { signal })
      if (!disposed) setFiles(values)
    },
    { interval },
  )
  const skillRefresh = createRefreshScheduler(
    async (signal) => {
      const values = await list<Skill>("/skills", { signal })
      if (!disposed) setSkills(values)
    },
    { interval },
  )
  const refresh = async () => {
    await Promise.all([sessionRefresh.request(), messageRefresh.request()])
  }
  const calibrate = async () => {
    await Promise.all([refresh(), modelRefresh.request(), fileRefresh.request(), skillRefresh.request()])
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
    ;[messageRefresh, sessionRefresh, modelRefresh, fileRefresh, skillRefresh].forEach((scheduler) =>
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
    selection.invalidate()
    setSelected(id)
    setMessages([])
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
    selection.invalidate()
    setSelected(undefined)
    setMessages([])
    setDraft("")
    setSelectedFiles([])
    setSelectedSkills([])
    setError("")
    setShowHistory(false)
    setBusy(false)
    textarea?.focus()
  }
  async function send() {
    if (!draft().trim() || sending() || busy() || !ready() || !models().length) return
    setSending(true)
    setError("")
    try {
      let id = selected()
      if (!id) {
        const session = await post<Session>("/sessions", { title: draft().trim().slice(0, 35) })
        id = session.id
        selection.invalidate()
        setSelected(id)
      }
      await post("/sessions/" + id + "/messages", {
        text: draft().trim(),
        model_id: model() || undefined,
        skill_ids: selectedSkills(),
        file_ids: selectedFiles(),
      })
      setDraft("")
      setBusy(true)
      await refresh()
    } catch (error) {
      setError((error as Error).message)
    } finally {
      setSending(false)
    }
  }
  async function abort() {
    if (!selected()) return
    try {
      await post("/sessions/" + selected() + "/abort")
      setBusy(false)
      await refresh()
      app.notify("已停止本次生成。")
    } catch (error) {
      setError((error as Error).message)
    }
  }
  async function deleteSession(item: Session) {
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
  return (
    <div class="chat-layout">
      <aside class={"history-panel " + (showHistory() ? "visible" : "")}>
        <div class="history-head">
          <strong>对话记录</strong>
          <button class="icon-button" aria-label="新建对话" onClick={fresh}>
            <Icon name="plus" />
          </button>
        </div>
        <Button class="new-chat" icon="plus" onClick={fresh}>
          新建对话
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
              each={sessions().filter((item) => item.title?.includes(search()))}
              fallback={<p class="quiet">你的对话会保存在这里</p>}
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
            <h2>{active()?.title || "新的对话"}</h2>
          </div>
          <div class="model-choice">
            <span class="model-dot" />
            <Show
              when={models().length > 1}
              fallback={<span class="model-name">{models()[0]?.name ?? "暂无可用模型"}</span>}
            >
              <select
                aria-label="选择授权模型"
                value={model()}
                disabled={busy()}
                onChange={(event) => setModel(event.currentTarget.value)}
              >
                <For each={models()}>
                  {(item) => (
                    <option value={item.id}>
                      {item.name}
                      {item.is_default ? " · 默认" : ""}
                    </option>
                  )}
                </For>
              </select>
            </Show>
          </div>
        </div>
        <Show when={notice()}>
          <div class="runtime-banner">
            <Icon name="clock" size={17} />
            <span>
              {notice()}
            </span>
            <Status value={app.user().runtime?.status} />
          </div>
        </Show>
        <div class="messages-scroll" ref={scroll}>
          <Show
            when={messages().length}
            fallback={
              <div class="welcome">
                <div class="welcome-symbol">
                  <Icon name="skill" size={31} />
                </div>
                <div class="eyebrow">你的专属智能助手</div>
                <h1>今天，从什么问题开始？</h1>
                <p>
                  提出问题，关联文件，或选择一项个人技能。
                  <br />
                  每一步思考，都在你的独立空间中完成。
                </p>
                <div class="suggestion-grid">
                  <button
                    onClick={() => {
                      setDraft("请帮我梳理资料中的关键事实，并标明资料来源。")
                      textarea?.focus()
                    }}
                  >
                    <Icon name="file" />
                    <strong>梳理关键事实</strong>
                    <span>让复杂资料变得有条理</span>
                  </button>
                  <button
                    onClick={() => {
                      setPicker("skills")
                    }}
                  >
                    <Icon name="skill" />
                    <strong>使用我的技能</strong>
                    <span>按你的习惯完成工作</span>
                  </button>
                  <button onClick={() => setPicker("files")}>
                    <Icon name="plugin" />
                    <strong>结合已有资料</strong>
                    <span>选择文件作为对话依据</span>
                  </button>
                </div>
              </div>
            }
          >
            <div class="messages">
              <For each={messages()}>
                {(message) => (
                  <article class={"message " + (message.info.role === "user" ? "user" : "assistant")}>
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
              <Show when={busy()}>
                <div class="thinking">
                  <Spinner />
                  <span>正在整理思路与资料…</span>
                  <button onClick={abort}>停止</button>
                </div>
              </Show>
            </div>
          </Show>
        </div>
        <div class="composer-area">
          <BusinessConfirmations sessionID={selected()} available={available()} onAnswered={() => void refresh()} />
          <ErrorLine message={error()} />
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
                    {skills().find((x) => x.id === id)?.name ?? "已选技能"}
                    <Icon name="close" size={12} />
                  </button>
                )}
              </For>
            </div>
          </Show>
          <div class="composer">
            <textarea
              ref={textarea}
              aria-label="输入消息"
              maxlength={32000}
              placeholder="描述你的问题，或告诉我希望完成什么…"
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
                <button onClick={() => setPicker("files")}>
                  <Icon name="file" size={17} />
                  关联文件
                </button>
                <button onClick={() => setPicker("skills")}>
                  <Icon name="skill" size={17} />
                  使用技能
                </button>
              </div>
              <Show
                when={busy()}
                fallback={
                  <Button
                    variant="primary"
                    icon="send"
                    busy={sending()}
                    disabled={!draft().trim() || !ready() || !models().length}
                    onClick={send}
                  >
                    发送
                  </Button>
                }
              >
                <Button icon="stop" onClick={abort}>
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
      <Show when={picker()}>
        {(type) => (
          <Modal
            title={type() === "files" ? "关联文件" : "使用我的技能"}
            text={type() === "files" ? "仅可选择已完成解析的个人文件。" : "选择的技能将用于本次提问。"}
            onClose={() => setPicker(undefined)}
          >
            <div class="picker-list">
              <For
                each={
                  type() === "files"
                    ? files().filter((item) => ["ready", "partial"].includes(item.status ?? ""))
                    : skills().filter((item) => item.enabled)
                }
                fallback={
                  <Empty
                    title={type() === "files" ? "暂无可关联文件" : "暂无已启用技能"}
                    text="请先到对应页面添加后再使用。"
                  />
                }
              >
                {(item) => (
                  <label class="pick-row">
                    <input
                      type="checkbox"
                      disabled={type() === "files" && "status" in item && item.status === "partial"}
                      checked={(type() === "files" ? selectedFiles() : selectedSkills()).includes(item.id)}
                      onChange={() => toggle(item.id, type())}
                    />
                    <Icon name={type() === "files" ? "file" : "skill"} />
                    <span>
                      {item.name}
                      <Show when={type() === "files" && "status" in item && item.status === "partial"}>
                        <br />
                        <small class="muted">部分解析 · 请拆分重传</small>
                      </Show>
                    </span>
                  </label>
                )}
              </For>
            </div>
            <div class="modal-actions">
              <Button variant="primary" onClick={() => setPicker(undefined)}>
                完成选择
              </Button>
            </div>
          </Modal>
        )}
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
