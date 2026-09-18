import { createEffect, createMemo, createSignal, For, onCleanup, onMount, Show } from "solid-js"
import { api, ApiError, list, patch, post, remove, safeMessage } from "../api"
import { Button, Empty, ErrorLine, Field, Icon, Markdown, Modal, Spinner, Status } from "../components"
import { useConsole } from "../context"
import BusinessConfirmations from "../BusinessConfirmations"
import { AnalysisResultView, ClueDrawer, CluePanel } from "../TrustedAnalysis"
import type { TrustedEvidence } from "../TrustedAnalysis"
import { displayName } from "../analysis-display"
import { capabilityCatalog } from "../capability-catalog"
import { canObserve, canSend } from "../runtime-view"
import type { AnalysisClue, CapabilityItem, Evidence, FileItem, Message, Model, Plugin, RunEvent, Session, Skill, SkillDraft } from "../types"
export default function Chat() {
  const app = useConsole()
  const [sessions, setSessions] = createSignal<Session[]>([])
  const [messages, setMessages] = createSignal<Message[]>([])
  const [expandedTools, setExpandedTools] = createSignal<Record<string, boolean>>({})
  const [models, setModels] = createSignal<Model[]>([])
  const [files, setFiles] = createSignal<FileItem[]>([])
  const [skills, setSkills] = createSignal<Skill[]>([])
  const [plugins, setPlugins] = createSignal<Plugin[]>([])
  const [capabilities, setCapabilities] = createSignal<CapabilityItem[]>([])
  const [selected, setSelected] = createSignal<string>()
  const [model, setModel] = createSignal("")
  const [draft, setDraft] = createSignal("")
  const [selectedFiles, setSelectedFiles] = createSignal<string[]>([])
  const [selectedSkills, setSelectedSkills] = createSignal<string[]>([])
  const [selectedPlugins, setSelectedPlugins] = createSignal<string[]>([])
  const [busy, setBusy] = createSignal(false)
  const [sending, setSending] = createSignal(false)
  const [uncertain, setUncertain] = createSignal(false)
  const [loading, setLoading] = createSignal(true)
  const [error, setError] = createSignal("")
  const [picker, setPicker] = createSignal<"files" | "capabilities">()
  const [search, setSearch] = createSignal("")
  const [capabilityKind, setCapabilityKind] = createSignal<"all" | "skill" | "plugin">("all")
  const [creator, setCreator] = createSignal<"choose" | "source" | "edit">()
  const [creatorSource, setCreatorSource] = createSignal<"requirement" | "conversation">("requirement")
  const [skillDraft, setSkillDraft] = createSignal<SkillDraft>()
  const [skillEditor, setSkillEditor] = createSignal<Skill>()
  const [latestRun, setLatestRun] = createSignal<string>()
  const [runEvents, setRunEvents] = createSignal<RunEvent[]>([])
  const [evidence, setEvidence] = createSignal<Evidence>()
  const [trusted, setTrusted] = createSignal<TrustedEvidence>()
  const [selectedClue, setSelectedClue] = createSignal<AnalysisClue>()
  const [showHistory, setShowHistory] = createSignal(false)
  const [rename, setRename] = createSignal<Session>()
  const [title, setTitle] = createSignal("")
  let scroll!: HTMLDivElement
  let textarea!: HTMLTextAreaElement
  let selectionRevision = 0
  let messageFlight: { id: string; revision: number; trailing: boolean; promise: Promise<void> } | undefined
  const shownSessions = createMemo(() => sessions())
  const active = createMemo(() => shownSessions().find((s) => s.id === selected()))
  const shownModels = createMemo(() => models())
  const shownCapabilities = createMemo(() => capabilities().filter((item) => item.enabled).map(item=>({...item,name:displayName(item.name),description:displayName(item.name)!==item.name?"整理相关资料并核对来源。":item.description})))
  const slashQuery = createMemo(() => draft().match(/^\s*\/([^\s]*)$/)?.[1]?.toLowerCase())
  const slashCapabilities = createMemo(() => {
    const query = slashQuery()
    if (query === undefined) return []
    return shownCapabilities().filter((item) => !query || `${item.name}${item.description ?? ""}`.toLowerCase().includes(query)).slice(0, 7)
  })
  const latestAnalysis = createMemo(() => trusted()?.presentation)
  const shownMessages = createMemo(() => {
    const values=messages(), turn=values.findIndex(x=>x.info.id===trusted()?.turn_id);
    return latestAnalysis()&&turn>=0?values.filter((x,i)=>i<=turn||x.info.role!=="assistant"):values
  })
  createEffect(() => {
    const clue = selectedClue()
    if (clue && !latestAnalysis()?.clues.some((item) => item.id === clue.id)) setSelectedClue(undefined)
  })
  const ready = createMemo(() => canSend(app.user().runtime))
  const available = createMemo(() => canObserve(app.user().runtime))
  function fetchMessages(id: string): Promise<void> {
    const revision = selectionRevision
    const owner = app.user().id
    if (messageFlight?.id === id && messageFlight.revision === revision) {
      messageFlight.trailing = true
      return messageFlight.promise
    }
    const flight = { id, revision, trailing: false, promise: Promise.resolve() }
    messageFlight = flight
    const current = () => selected() === id && selectionRevision === revision && app.user().id === owner
    flight.promise = (async () => {
      do {
        flight.trailing = false
        const data = await list<Message>("/sessions/" + id + "/messages")
        if (!current()) return
        setMessages(data)
        if(trusted()?.turn_id!==data.filter(x=>x.info.role==="user").at(-1)?.info.id)setTrusted(undefined)
        try {
          const view=await api<TrustedEvidence>("/sessions/"+id+"/evidence")
          if(current())setTrusted(view)
        } catch {
          if(current()){setTrusted(undefined);setError("研判结果暂时无法读取，请刷新重试。")}
        }
      } while (flight.trailing && current())
    })().finally(() => {
      if (messageFlight === flight) messageFlight = undefined
    })
    return flight.promise
  }
  async function refresh() {
    if (!available()) {
      setBusy(false)
      return
    }
    try {
      const values = await list<Session>("/sessions")
      setSessions(values)
      if (selected()) {
        setBusy(["busy", "retry"].includes(values.find((item) => item.id === selected())?.status ?? "idle"))
        await fetchMessages(selected()!)
      }
      setError("")
    } catch (error) {
      setError((error as Error).message)
    }
  }
  async function resources() {
    if (!available()) {
      setLoading(false)
      return
    }
    const result = await Promise.allSettled([
      list<Model>("/models"),
      list<FileItem>("/files"),
      list<Skill>("/skills"),
      list<Session>("/sessions"),
      list<Plugin>("/plugins"),
    ])
    if (result[0].status === "fulfilled") {
      setModels(result[0].value as Model[])
      const data = result[0].value as Model[]
      if (!data.some((item) => item.id === model())) setModel(data.find((x) => x.is_default)?.id ?? data[0]?.id ?? "")
    }
    if (result[1].status === "fulfilled") setFiles(result[1].value as FileItem[])
    if (result[2].status === "fulfilled") setSkills(result[2].value as Skill[])
    if (result[3].status === "fulfilled") setSessions(result[3].value as Session[])
    if (result[4].status === "fulfilled") setPlugins(result[4].value as Plugin[])
    setCapabilities(
      capabilityCatalog(
        result[2].status === "fulfilled" ? (result[2].value as Skill[]) : skills(),
        result[4].status === "fulfilled" ? (result[4].value as Plugin[]) : plugins(),
      ).map((item) => ({
        ...item,
        category: item.kind === "skill" ? "个人 Skill" : "插件工具",
        recommended: false,
        enabled: true,
        owned: item.kind === "skill",
        scope: item.kind === "skill" ? "personal" : "authorized",
      })),
    )
    setLoading(false)
  }
  onMount(() => {
    void resources()
  })
  createEffect(() => {
    app.changed()
    void refresh()
    void resources()
  })
  const poll = setInterval(() => {
    if (busy()) void refresh()
  }, 1800)
  onCleanup(() => { selectionRevision++; clearInterval(poll) })
  createEffect(()=>{if(!available()){selectionRevision++;setTrusted(undefined);setSelectedClue(undefined)}})
  createEffect(() => {
    messages()
    busy()
    queueMicrotask(() => {
      if (scroll) scroll.scrollTop = scroll.scrollHeight
    })
  })
  async function choose(id: string) {
    selectionRevision++
    setSelected(id)
    setMessages([])
    setTrusted(undefined)
    setSelectedClue(undefined)
    setError("")
    setShowHistory(false)
    setBusy(["busy", "retry"].includes(sessions().find((item) => item.id === id)?.status ?? "idle"))
    try {
      await fetchMessages(id)
    } catch (error) {
      setError((error as Error).message)
    }
  }
  function fresh() {
    selectionRevision++
    setSelected(undefined)
    setMessages([])
    setTrusted(undefined)
    setSelectedClue(undefined)
    if (!uncertain()) setDraft("")
    setSelectedFiles([])
    setSelectedSkills([])
    setSelectedPlugins([])
    setError("")
    setShowHistory(false)
    setBusy(false)
    textarea?.focus()
  }
  async function send() {
    if (!draft().trim() || sending() || uncertain() || busy() || !ready() || !shownModels().length) return
    const text = draft()
    const payload = {
      text: text.trim(),
      model_id: model() || undefined,
      skill_ids: [...selectedSkills()],
      file_ids: [...selectedFiles()],
    }
    const uid = app.user().id
    setSending(true)
    setError("")
    let submitting = false
    let accepted = false
    try {
      let id = selected()
      if (!id) {
        const session = await post<Session>("/sessions", { title: text.trim().slice(0, 35) })
        if (app.user().id !== uid) return
        id = session.id
        selectionRevision++
        setSelected(id)
      }
      if (!ready()) return
      submitting = true
      const result = await post<{ accepted: boolean; run_id: string }>("/sessions/" + id + "/messages", payload)
      if (app.user().id !== uid) return
      if (result.accepted !== true) throw new ApiError("提交结果待确认，请核对历史记录。", 0, "unknown_submission")
      accepted = true
      setLatestRun(result.run_id)
      setRunEvents([])
      if (draft() === text) setDraft("")
      setBusy(true)
      await refresh()
    } catch (error) {
      if (app.user().id !== uid) return
      if (accepted) setError("消息已受理，历史记录暂未刷新；请等待恢复，不要重复发送。")
      else if (submitting && error instanceof ApiError && (error.status === 0 || error.status >= 500)) {
        setUncertain(true)
        setError("提交结果待确认，草稿已保留。请先检查历史和当前任务状态，避免重复调用。")
      } else setError((error as Error).message)
    } finally {
      if (app.user().id === uid) setSending(false)
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
  function toggleCapability(item: CapabilityItem) {
    if (item.kind === "skill") {
      toggle(item.id, "skills")
      return
    }
    app.notify("当前后端不支持随消息选择插件；已授权插件由助手按需调用。", "error")
  }
  function chooseSlashCapability(item: CapabilityItem) {
    toggleCapability(item)
    setDraft("")
    queueMicrotask(() => textarea?.focus())
  }
  async function generateSkill(source: "requirement" | "conversation") {
    if (source === "conversation" && !selected()) {
      app.notify("请先选择一条已有对话。", "error")
      return
    }
    setCreatorSource(source)
    app.notify("当前后端尚未提供 Skill 草稿生成接口。", "error")
  }
  async function updateDraft() {
    return skillDraft()
  }
  async function testDraft() {
    await updateDraft()
    app.notify("当前后端尚未提供 Skill 草稿测试接口。", "error")
  }
  async function saveDraft() {
    await updateDraft()
    app.notify("当前后端尚未提供 Skill 草稿保存接口。", "error")
  }
  async function savePersonalSkill() {
    const value = skillEditor()
    if (!value) return
    try {
      await patch("/skills/" + value.id, {
        name: value.name,
        description: value.description ?? "",
        content: value.content ?? "",
        enabled: value.enabled ?? true,
      })
      setSkillEditor(undefined)
      await resources()
      app.notify("个人 Skill 已更新。")
    } catch (cause) {
      app.notify((cause as Error).message, "error")
    }
  }
  async function testPersonalSkill() {
    const value = skillEditor()
    if (!value) return
    try {
      const result = await post<{ ok: boolean; message: string }>("/skills/" + value.id + "/test")
      app.notify(result.message, result.ok ? "success" : "error")
    } catch (cause) {
      app.notify((cause as Error).message, "error")
    }
  }
  async function deletePersonalSkill() {
    const value = skillEditor()
    if (!value || !window.confirm(`确定删除个人 Skill“${value.name}”吗？`)) return
    try {
      await remove("/skills/" + value.id)
      setSelectedSkills(selectedSkills().filter((id) => id !== value.id))
      setSkillEditor(undefined)
      await resources()
      app.notify("个人 Skill 已删除。")
    } catch (cause) {
      app.notify((cause as Error).message, "error")
    }
  }
  async function showEvidence() {
    if (!selected() || !latestRun()) return
    try {
      setEvidence(await api<Evidence>("/sessions/" + selected() + "/evidence"))
    } catch (cause) {
      app.notify((cause as Error).message, "error")
    }
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
                    <span>{displayName(item.title) || "未命名对话"}</span>
                  </button>
                  <Show when={!item.id.startsWith("mock-")}><div class="history-actions">
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
                  </div></Show>
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
            <h2>{displayName(active()?.title) || "新建研判"}</h2>
          </div>
          <div class="conversation-head-actions">
            <div class="model-choice">
              <span class="model-dot" />
              <select
                aria-label="选择授权模型"
                value={model() || shownModels()[0]?.id}
                disabled={busy()}
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
            <Button class="distill-skill" icon="skill" onClick={() => setCreator("choose")}>沉淀为 Skill</Button>
          </div>
        </div>
        <Show when={!ready()}>
          <div class="runtime-banner">
            <Icon name="clock" size={17} />
            <span>
              个人工作空间
              {["updating", "applying"].includes(app.user().runtime?.status ?? "")
                ? "正在更新配置，当前对话可继续查看或停止，完成后即可发送新消息。"
                : ["paused", "stopped"].includes(app.user().runtime?.status ?? "")
                  ? "已暂停，请联系管理员恢复。"
                  : ["failed", "error"].includes(app.user().runtime?.status ?? "")
                    ? "暂时不可用，请联系管理员检查并重试。"
                    : "正在准备，准备完成后即可发送消息。"}
            </span>
            <Status value={app.user().runtime?.status} />
          </div>
        </Show>
        <div class="messages-scroll" ref={scroll}>
          <Show
            when={messages().length}
            fallback={<div class="conversation-blank" aria-label="空白研判对话区" />}
          >
            <div class="messages">
              <For each={shownMessages()}>
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
                        {(part) => {
                          const structured = undefined
                          return (
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
                          )
                        }}
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
              <Show when={latestAnalysis()}>{result=><article class="message assistant"><div class="message-avatar"><Icon name="skill" size={17}/></div><div class="message-content"><div class="message-author">智能助手</div><AnalysisResultView result={result()} onSelect={setSelectedClue}/></div></article>}</Show>
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
          <Show when={uncertain()}>
            <div class="runtime-banner" role="status">
              <span>结果待确认。刷新不会自动重发本次问题。</span>
              <Button onClick={() => void refresh()}>刷新历史</Button>
              <Button onClick={() => {
                if (window.confirm("请确认已核对原会话历史及任务状态。重新发送可能产生重复调用，是否解除发送保护？")) {
                  setUncertain(false)
                  setError("")
                }
              }}>已核对，解除保护</Button>
            </div>
          </Show>
          <Show when={selectedFiles().length || selectedSkills().length || selectedPlugins().length}>
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
              <For each={selectedPlugins()}>
                {(id) => (
                  <button onClick={() => setSelectedPlugins((current) => current.filter((value) => value !== id))}>
                    <Icon name="plugin" size={13} />
                    {shownCapabilities().find((x) => x.id === id)?.name ?? "已选插件"}
                    <Icon name="close" size={12} />
                  </button>
                )}
              </For>
            </div>
          </Show>
          <Show when={slashQuery() !== undefined}>
            <div class="slash-command-menu">
              <div class="slash-command-head"><strong>/ 选择技能或插件</strong><span>输入名称可筛选</span></div>
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
              placeholder="输入研判内容，使用 / 唤醒技能或插件…"
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
                when={busy()}
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
      <Show when={latestAnalysis()?.clues.length} fallback={<aside class="related-capabilities">
        <div class="related-capabilities-head"><div><strong>相关插件技能</strong><small>当前账号全部可用能力</small></div><span>{shownCapabilities().length}</span></div>
        <div class="related-capabilities-list">
          <For each={shownCapabilities()}>
            {(item, index) => <button class={(item.kind === "skill" ? selectedSkills() : selectedPlugins()).includes(item.id) ? "selected" : ""} onClick={() => toggleCapability(item)}><span class={"capability-icon tone-" + (index() % 5)}><Icon name={item.kind === "skill" ? "skill" : "plugin"} size={18} /></span><span><strong>{item.name}<em>v{item.version}</em></strong><small>{item.description}</small><i>{item.kind === "skill" ? (item.owned ? "个人 Skill" : "官方 Skill") : "插件工具"}</i></span><b>{(item.kind === "skill" ? selectedSkills() : selectedPlugins()).includes(item.id) ? "已选" : "使用"}</b></button>}
          </For>
        </div>
      </aside>}>
        <CluePanel clues={latestAnalysis()?.clues ?? []} onSelect={setSelectedClue} />
      </Show>
      <Show when={selectedClue()}>{(clue) => <ClueDrawer clue={clue()} onClose={() => setSelectedClue(undefined)} />}</Show>
      <Show when={picker()}>
        {(type) => (
          <Modal
            title={type() === "files" ? "关联文件" : "能力选择"}
            text={type() === "files" ? "仅可选择已完成解析的个人文件。" : "选择适合当前任务的能力；个人 Skill 可在此编辑和使用。"}
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
                    <input
                      type="checkbox"
                      disabled={type() === "files" && "status" in item && item.status === "partial"}
                      checked={(type() === "files" ? selectedFiles() : "kind" in item && item.kind === "plugin" ? selectedPlugins() : selectedSkills()).includes(item.id)}
                      onChange={() => type() === "files" ? toggle(item.id, "files") : "kind" in item && toggleCapability(item)}
                    />
                    <Icon name={type() === "files" ? "file" : "skill"} />
                    <span>
                      {item.name}
                      <Show when={type() === "capabilities" && "description" in item}><small>{("description" in item ? item.description : "") || "可用于当前研判任务"}</small></Show>
                      <Show when={type() === "files" && "status" in item && item.status === "partial"}>
                        <br />
                        <small class="muted">部分解析 · 请拆分重传</small>
                      </Show>
                    </span>
                    <Show when={type() === "capabilities" && "owned" in item && item.owned}>
                      <Button
                        variant="ghost"
                        onClick={() => {
                          const skill = skills().find((value) => value.id === item.id)
                          if (skill) setSkillEditor({ ...skill })
                        }}
                      >
                        编辑
                      </Button>
                    </Show>
                  </div>
                )}
              </For>
            </div>
            <div class="modal-actions">
              <Show when={type() === "capabilities"}><Button icon="plus" onClick={() => { setPicker(undefined); setCreator("choose") }}>创建 Skill</Button></Show>
              <Button variant="primary" onClick={() => setPicker(undefined)}>
                完成选择
              </Button>
            </div>
          </Modal>
        )}
      </Show>
      <Show when={creator() === "choose"}><Modal title="选择创建方式" onClose={() => setCreator(undefined)}><div class="creator-choice"><button onClick={() => { setCreatorSource("requirement"); setCreator("source") }}><Icon name="file" /><strong>从需求创建</strong><span>通过自然语言描述，由系统生成 Skill 草稿</span></button><button onClick={() => void generateSkill("conversation")}><Icon name="chat" /><strong>从当前对话生成</strong><span>提炼当前研判对话中的有效流程</span></button></div></Modal></Show>
      <Show when={creator() === "source"}><Modal title="从需求创建 Skill" text="描述需要固化的研判目标、数据范围和输出要求。" wide onClose={() => setCreator(undefined)}><Field label="研判需求" required><textarea rows={8} value={draft()} onInput={(event) => setDraft(event.currentTarget.value)} placeholder="例如：分析目标人员最近30天夜间活动和共同出现人员" /></Field><div class="modal-actions"><Button onClick={() => setCreator("choose")}>上一步</Button><Button variant="primary" onClick={() => void generateSkill("requirement")}>AI 提炼生成</Button></div></Modal></Show>
      <Show when={creator() === "edit" && skillDraft()}>{(value) => <Modal title="编辑 Skill" text={`来源：${creatorSource() === "conversation" ? "当前对话" : "需求描述"}`} wide onClose={() => setCreator(undefined)}><div class="form-grid"><Field label="Skill 名称" required><input value={value().name} onInput={(event) => setSkillDraft({ ...value(), name: event.currentTarget.value })} /></Field><Field label="使用场景"><input value={value().description} onInput={(event) => setSkillDraft({ ...value(), description: event.currentTarget.value })} /></Field></div><Field label="Skill 内容（SKILL.md）" required><textarea class="skill-editor" value={value().content} onInput={(event) => setSkillDraft({ ...value(), content: event.currentTarget.value })} /></Field><div class="modal-actions"><Button onClick={() => void testDraft()}>测试运行</Button><Button variant="primary" onClick={() => void saveDraft()}>保存到个人 Skill</Button></div></Modal>}</Show>
      <Show when={skillEditor()}>{(value) => <Modal title="编辑个人 Skill" text="个人 Skill 仅当前账号可见，可在能力选择弹窗中继续使用。" wide onClose={() => setSkillEditor(undefined)}><div class="form-grid"><Field label="Skill 名称" required><input value={value().name} onInput={(event) => setSkillEditor({ ...value(), name: event.currentTarget.value })} /></Field><Field label="使用场景"><input value={value().description ?? ""} onInput={(event) => setSkillEditor({ ...value(), description: event.currentTarget.value })} /></Field></div><Field label="Skill 内容（SKILL.md）" required><textarea class="skill-editor" value={value().content ?? ""} onInput={(event) => setSkillEditor({ ...value(), content: event.currentTarget.value })} /></Field><div class="modal-actions split"><Button variant="danger" onClick={() => void deletePersonalSkill()}>删除</Button><span /><Button onClick={() => void testPersonalSkill()}>测试运行</Button><Button variant="primary" onClick={() => void savePersonalSkill()}>保存</Button></div></Modal>}</Show>
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
