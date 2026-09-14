import { createEffect, createSignal, For, Show } from "solid-js"
import { api, list, patch, post, remove } from "../api"
import {
  Button,
  Empty,
  ErrorLine,
  Field,
  Icon,
  JobNote,
  Markdown,
  Modal,
  PageHead,
  Spinner,
  Toggle,
} from "../components"
import { useConsole } from "../context"
import type { Skill } from "../types"
export default function Skills() {
  const app = useConsole()
  const locked = () => ["updating", "applying"].includes(app.user().runtime?.status ?? "")
  const [skills, setSkills] = createSignal<Skill[]>([])
  const [templates, setTemplates] = createSignal<Skill[]>([])
  const [tab, setTab] = createSignal("mine")
  const [loading, setLoading] = createSignal(true)
  const [error, setError] = createSignal("")
  const [editor, setEditor] = createSignal<Partial<Skill>>()
  const [name, setName] = createSignal("")
  const [description, setDescription] = createSignal("")
  const [content, setContent] = createSignal("")
  const [enabled, setEnabled] = createSignal(true)
  const [saving, setSaving] = createSignal(false)
  const [preview, setPreview] = createSignal(false)
  const [test, setTest] = createSignal<unknown>()
  const [working, setWorking] = createSignal("")
  let importInput!: HTMLInputElement
  async function refresh() {
    try {
      const result = await Promise.all([list<Skill>("/skills"), list<Skill>("/templates")])
      setSkills(result[0])
      setTemplates(result[1])
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
  function edit(item: Partial<Skill> = {}) {
    setEditor(item)
    setName(item.name ?? "")
    setDescription(item.description ?? "")
    setContent(item.content ?? "")
    setEnabled(item.enabled ?? true)
    setPreview(false)
    setError("")
  }
  async function save(event: SubmitEvent) {
    event.preventDefault()
    if (locked()) {
      setError("配置正在更新，完成后可提交修改。")
      return
    }
    if (!content().trim() || content().length > 32000) {
      setError("技能内容应为 1 至 32000 个字符。")
      setPreview(false)
      return
    }
    setSaving(true)
    try {
      const body = { name: name().trim(), description: description().trim(), content: content(), enabled: enabled() }
      if (editor()?.id) await patch("/skills/" + editor()!.id, body)
      else await post("/skills", body)
      setEditor(undefined)
      app.notify("技能已保存，正在更新你的工作空间。")
      await refresh()
    } catch (error) {
      setError((error as Error).message)
    } finally {
      setSaving(false)
    }
  }
  async function action(item: Skill, operation: "toggle" | "test" | "rollback" | "delete" | "copy") {
    if (locked()) {
      app.notify("配置正在更新，完成后可提交修改。", "error")
      return
    }
    if (operation === "delete" && !window.confirm("确定删除这个个人技能吗？")) return
    setWorking(item.id)
    try {
      if (operation === "toggle") await patch("/skills/" + item.id, { enabled: !item.enabled })
      if (operation === "test") setTest(await post("/skills/" + item.id + "/test"))
      if (operation === "rollback") await post("/skills/" + item.id + "/rollback")
      if (operation === "delete") await remove("/skills/" + item.id)
      if (operation === "copy") {
        await post("/templates/" + item.id + "/copy")
        setTab("mine")
        app.notify("模板已复制到我的技能，可以继续编辑。")
      }
      await refresh()
    } catch (error) {
      app.notify((error as Error).message, "error")
    } finally {
      setWorking("")
    }
  }
  async function importFile(file?: File) {
    if (!file) return
    if (file.size > 512 * 1024) {
      app.notify("技能文本请控制在 512 KB 以内。", "error")
      return
    }
    edit({ name: file.name.replace(/\.(md|txt)$/i, ""), content: await file.text(), enabled: true })
    importInput.value = ""
  }
  return (
    <div class="content-page">
      <PageHead
        eyebrow="可复用的分析方法"
        title="分析技能"
        text="把常用的分析步骤和输出要求，整理成随时可用的个人技能。"
      >
        <Button icon="upload" onClick={() => importInput.click()}>
          导入文本
        </Button>
        <Button variant="primary" icon="plus" onClick={() => edit()}>
          创建技能
        </Button>
      </PageHead>
      <input
        ref={importInput}
        class="visually-hidden"
        type="file"
        accept=".md,.txt"
        aria-label="导入技能文本"
        onChange={(event) => void importFile(event.currentTarget.files?.[0])}
      />
      <ErrorLine message={error()} />
      <Show when={locked()}>
        <div class="notice">配置正在更新，当前可以查看或编辑草稿，完成后再提交修改。</div>
      </Show>
      <div class="section-toolbar">
        <div class="tabs">
          <button class={tab() === "mine" ? "active" : ""} onClick={() => setTab("mine")}>
            我的技能 <span>{skills().length}</span>
          </button>
          <button class={tab() === "templates" ? "active" : ""} onClick={() => setTab("templates")}>
            推荐模板 <span>{templates().length}</span>
          </button>
        </div>
        <span class="muted small">个人技能仅在你的空间中生效</span>
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
            each={tab() === "mine" ? skills() : templates()}
            fallback={
              <Empty
                icon="skill"
                title={tab() === "mine" ? "把你的分析方法保存下来" : "暂无推荐模板"}
                text={tab() === "mine" ? "创建个人技能，或从推荐模板开始。" : "管理员发布的技能模板会出现在这里。"}
              >
                <Show when={tab() === "mine"}>
                  <Button icon="plus" onClick={() => edit()}>
                    创建第一个技能
                  </Button>
                </Show>
              </Empty>
            }
          >
            {(item) => (
              <article class="resource-card">
                <div class="resource-head">
                  <span class="resource-icon">
                    <Icon name="skill" />
                  </span>
                  <Show when={tab() === "mine"}>
                    <Toggle
                      checked={item.enabled}
                      disabled={locked() || working() === item.id}
                      label={item.enabled ? "已启用" : "已停用"}
                      onChange={() => void action(item, "toggle")}
                    />
                  </Show>
                  <Show when={tab() === "templates"}>
                    <span class="pill">推荐模板</span>
                  </Show>
                </div>
                <h3>{item.name}</h3>
                <p>{item.description || "按设定的步骤和要求辅助完成分析。"}</p>
                <div class="resource-meta">{item.version ? "版本 " + item.version : "文本技能"}</div>
                <div class="resource-actions">
                  <Show
                    when={tab() === "mine"}
                    fallback={
                      <Button
                        onClick={() => void action(item, "copy")}
                        disabled={locked()}
                        busy={working() === item.id}
                      >
                        添加到我的技能
                      </Button>
                    }
                  >
                    <Button icon="edit" onClick={() => edit(item)}>
                      编辑
                    </Button>
                    <Button
                      variant="ghost"
                      disabled={locked()}
                      busy={working() === item.id}
                      onClick={() => void action(item, "test")}
                    >
                      测试
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
                    <button
                      class="icon-button"
                      aria-label={"删除 " + item.name}
                      disabled={locked() || working() === item.id}
                      onClick={() => void action(item, "delete")}
                    >
                      <Icon name="trash" size={16} />
                    </button>
                  </Show>
                </div>
              </article>
            )}
          </For>
        </div>
      </Show>
      <div class="info-strip">
        <Icon name="skill" size={16} />
        <span>技能用于描述分析步骤，不会改变你的数据权限，也不包含可执行插件代码。</span>
      </div>
      <Show when={editor()}>
        <Modal
          title={editor()?.id ? "编辑个人技能" : "创建个人技能"}
          text="写清适用场景、分析步骤和期望的输出格式。"
          wide
          onClose={() => {
            if (!saving()) setEditor(undefined)
          }}
        >
          <form onSubmit={save}>
            <ErrorLine message={error()} />
            <Show when={locked()}>
              <div class="notice">配置正在更新，当前可以查看或编辑草稿，完成后再提交修改。</div>
            </Show>
            <div class="form-grid">
              <Field label="技能名称" required>
                <input
                  required
                  maxlength={60}
                  value={name()}
                  onInput={(event) => setName(event.currentTarget.value)}
                  placeholder="例如：资料要点梳理"
                />
              </Field>
              <Field label="简短说明">
                <input
                  maxlength={240}
                  value={description()}
                  onInput={(event) => setDescription(event.currentTarget.value)}
                  placeholder="说明何时使用这项技能"
                />
              </Field>
            </div>
            <div class="editor-bar">
              <strong>技能内容</strong>
              <div class="tabs compact">
                <button type="button" class={!preview() ? "active" : ""} onClick={() => setPreview(false)}>
                  编辑
                </button>
                <button type="button" class={preview() ? "active" : ""} onClick={() => setPreview(true)}>
                  预览
                </button>
              </div>
            </div>
            <Show
              when={preview()}
              fallback={
                <textarea
                  class="skill-editor"
                  aria-label="技能内容"
                  required
                  maxlength={32000}
                  value={content()}
                  onInput={(event) => setContent(event.currentTarget.value)}
                  placeholder={
                    "## 适用场景\n说明何时使用这项技能。\n\n## 分析步骤\n1. 阅读用户选择的资料。\n2. 区分已知事实与待核实事项。\n\n## 输出要求\n列出关键结论，并注明资料来源。"
                  }
                />
              }
            >
              <div class="skill-preview">
                <Markdown text={content()} />
              </div>
            </Show>
            <div class="modal-actions between">
              <Toggle checked={enabled()} onChange={setEnabled} label="保存后启用" />
              <div>
                <Button type="button" onClick={() => setEditor(undefined)} disabled={saving()}>
                  取消
                </Button>
                <Button type="submit" variant="primary" busy={saving()} disabled={locked()}>
                  保存技能
                </Button>
              </div>
            </div>
          </form>
        </Modal>
      </Show>
      <Show when={test() !== undefined}>
        <Modal title="技能生效检查" text="确认技能能否使用，不进行分析生成。" onClose={() => setTest(undefined)}>
          <JobNote value={test()} />
          <div class="modal-actions">
            <Button onClick={() => setTest(undefined)}>关闭</Button>
          </div>
        </Modal>
      </Show>
    </div>
  )
}
