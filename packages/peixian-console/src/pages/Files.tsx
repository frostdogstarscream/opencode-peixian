import { createEffect, createMemo, createSignal, For, Show } from "solid-js"
import { api, download, list, remove, safeMessage } from "../api"
import { Button, Empty, ErrorLine, formatDate, formatSize, Icon, Modal, PageHead, Spinner, Status } from "../components"
import { useConsole } from "../context"
import type { FileItem } from "../types"
type PreviewChunk = {
  text: string
  source?: {
    page?: number
    sheet?: string
    row_start?: number
    row_end?: number
    paragraph?: number
    table?: number
    line_start?: number
    line_end?: number
    type?: string
  }
}
type PreviewData = {
  text?: string
  content?: string
  status?: string
  error?: string
  chunks?: PreviewChunk[]
  truncated?: boolean
}
function parseError(value?: string) {
  return (
    (
      {
        parse_error: "文件损坏或格式不符，请检查原文件",
        parse_timeout: "解析超时，请拆分文档",
        resource_limit: "内容过大或过于复杂，请拆分文档",
        encrypted_document: "文件已加密，请去除密码后重新上传",
        text_encoding: "无法识别文字编码，请另存为 UTF-8",
        input_limit: "文件过大，请拆分后重新上传",
      } as Record<string, string>
    )[value ?? ""] ?? safeMessage(value)
  )
}
function sourceLabel(chunk: PreviewChunk, index: number) {
  const source = chunk.source ?? {}
  const values: string[] = []
  if (source.page !== undefined) values.push(`第 ${source.page} 页`)
  if (source.sheet) values.push(`工作表：${source.sheet}`)
  if (source.paragraph !== undefined) values.push(`第 ${source.paragraph} 段`)
  if (source.table !== undefined) values.push(`表格 ${source.table}`)
  const start = source.row_start ?? source.line_start
  const end = source.row_end ?? source.line_end
  if (start !== undefined) values.push(`第 ${start}${end !== undefined && end !== start ? "–" + end : ""} 行`)
  return values.length ? values.join(" · ") : `内容片段 ${index + 1}`
}
export default function Files() {
  const app = useConsole()
  const [items, setItems] = createSignal<FileItem[]>([])
  const [results, setResults] = createSignal<FileItem[]>([])
  const [tab, setTab] = createSignal("files")
  const [search, setSearch] = createSignal("")
  const [loading, setLoading] = createSignal(true)
  const [uploading, setUploading] = createSignal(false)
  const [error, setError] = createSignal("")
  const [preview, setPreview] = createSignal<FileItem>()
  const [text, setText] = createSignal("")
  const [chunks, setChunks] = createSignal<PreviewChunk[]>([])
  const [truncated, setTruncated] = createSignal(false)
  const [previewBusy, setPreviewBusy] = createSignal(false)
  const [drag, setDrag] = createSignal(false)
  let input!: HTMLInputElement
  async function refresh() {
    if (!["ready", "running", "healthy"].includes(app.user().runtime?.status ?? "")) {
      setLoading(false)
      setError("个人工作空间尚不可用，恢复后可查看文件。")
      return
    }
    try {
      const [files, outputs] = await Promise.all([list<FileItem>("/files"), list<FileItem>("/results")])
      setItems(files)
      setResults(outputs)
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
  const visible = createMemo(() =>
    (tab() === "files" ? items() : results()).filter((item) =>
      item.name?.toLowerCase().includes(search().toLowerCase()),
    ),
  )
  async function upload(files: FileList | File[] | null) {
    if (!files?.length) return
    setUploading(true)
    setError("")
    let completed = 0
    try {
      for (const file of Array.from(files)) {
        const body = new FormData()
        body.append("file", file)
        await api("/files", { method: "POST", body })
        completed++
      }
      app.notify(`已上传 ${completed} 个文件，正在准备解析结果。`)
      await refresh()
    } catch (error) {
      setError((error as Error).message)
      await refresh()
    } finally {
      setUploading(false)
      input.value = ""
    }
  }
  async function open(item: FileItem) {
    setPreview(item)
    setText("")
    setChunks([])
    setTruncated(false)
    setPreviewBusy(true)
    try {
      const response = await api<string | PreviewData>("/files/" + item.id + "/preview")
      const value: PreviewData = typeof response === "string" ? { text: response } : response
      if (preview()?.id !== item.id) return
      setText(value.text || value.content || "此文件暂无可预览的文字，请查看解析状态或下载原文件。")
      setChunks(value.chunks ?? [])
      setTruncated(!!value.truncated)
      setPreview({ ...item, status: value.status ?? item.status, error: value.error ?? item.error })
    } catch (error) {
      if (preview()?.id === item.id) setText(safeMessage((error as Error).message))
    } finally {
      if (preview()?.id === item.id) setPreviewBusy(false)
    }
  }
  async function erase(item: FileItem) {
    if (!window.confirm("确定删除这个文件吗？已有对话中的引用可能无法再次使用。")) return
    try {
      await remove("/files/" + item.id)
      app.notify("文件已删除。")
      await refresh()
    } catch (error) {
      app.notify((error as Error).message, "error")
    }
  }
  return (
    <div class="content-page">
      <PageHead eyebrow="资料中心" title="我的文件" text="上传资料、查看解析进度，让每次分析有据可依。">
        <Button variant="primary" icon="upload" busy={uploading()} onClick={() => input.click()}>
          上传文件
        </Button>
      </PageHead>
      <input
        ref={input}
        class="visually-hidden"
        type="file"
        multiple
        accept=".xlsx,.pdf,.docx,.txt,.md,.csv"
        aria-label="选择上传文件"
        onChange={(event) => void upload(event.currentTarget.files)}
      />
      <div
        class={"drop-zone " + (drag() ? "dragging" : "")}
        onDragOver={(event) => {
          event.preventDefault()
          setDrag(true)
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(event) => {
          event.preventDefault()
          setDrag(false)
          if (!uploading()) void upload(event.dataTransfer?.files ?? null)
        }}
      >
        <span class="drop-icon">
          <Icon name="upload" size={24} />
        </span>
        <div>
          <strong>{uploading() ? "正在上传，请稍候…" : "拖拽文件到这里，或点击上传"}</strong>
          <p>支持 Excel、PDF、Word 和文本资料 · 扫描版文档暂不识别图片文字</p>
        </div>
        <Button onClick={() => input.click()} disabled={uploading()}>
          选择文件
        </Button>
      </div>
      <ErrorLine message={error()} />
      <div class="section-toolbar">
        <div class="tabs">
          <button class={tab() === "files" ? "active" : ""} onClick={() => setTab("files")}>
            资料文件 <span>{items().length}</span>
          </button>
          <button class={tab() === "results" ? "active" : ""} onClick={() => setTab("results")}>
            分析成果 <span>{results().length}</span>
          </button>
        </div>
        <label class="search-box">
          <Icon name="search" size={16} />
          <input
            aria-label="搜索文件"
            placeholder="搜索文件名称"
            value={search()}
            onInput={(event) => setSearch(event.currentTarget.value)}
          />
        </label>
      </div>
      <Show
        when={!loading()}
        fallback={
          <div class="loading">
            <Spinner />
            正在读取文件列表
          </div>
        }
      >
        <Show
          when={visible().length}
          fallback={
            <Empty
              icon="file"
              title={tab() === "files" ? "还没有上传资料" : "还没有生成成果"}
              text={
                tab() === "files" ? "上传文件后，会自动提取可用于分析的内容。" : "对话中生成的结果文件会出现在这里。"
              }
            />
          }
        >
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>文件名称</th>
                  <th>大小</th>
                  <th>解析状态</th>
                  <th>上传时间</th>
                  <th class="align-right">操作</th>
                </tr>
              </thead>
              <tbody>
                <For each={visible()}>
                  {(item) => (
                    <tr>
                      <td>
                        <div class="file-cell">
                          <span class="file-type">
                            {item.name?.split(".").pop()?.slice(0, 4).toUpperCase() ?? "FILE"}
                          </span>
                          <div>
                            <strong>{item.name}</strong>
                            <Show when={item.error}>
                              <small class="danger-text">{parseError(item.error)}</small>
                            </Show>
                          </div>
                        </div>
                      </td>
                      <td class="nowrap">{formatSize(item.size)}</td>
                      <td>
                        <Status value={item.status ?? "ready"} />
                      </td>
                      <td class="nowrap muted">{formatDate(item.created_at)}</td>
                      <td>
                        <div class="table-actions">
                          <Show when={tab() === "files"}>
                            <Button variant="ghost" onClick={() => void open(item)}>
                              预览
                            </Button>
                          </Show>
                          <a
                            class="button ghost"
                            href={download((tab() === "files" ? "/files/" : "/results/") + item.id + "/download")}
                            download=""
                            aria-label={"下载 " + item.name}
                          >
                            <Icon name="download" size={16} />
                            <span>下载</span>
                          </a>
                          <Show when={tab() === "files"}>
                            <button
                              class="icon-button"
                              aria-label={"删除 " + item.name}
                              onClick={() => void erase(item)}
                            >
                              <Icon name="trash" size={17} />
                            </button>
                          </Show>
                        </div>
                      </td>
                    </tr>
                  )}
                </For>
              </tbody>
            </table>
          </div>
        </Show>
      </Show>
      <div class="info-strip">
        <Icon name="lock" size={16} />
        <span>文件仅保存在你的个人工作空间。解析失败时可下载原文件检查格式。</span>
      </div>
      <Show when={preview()}>
        {(item) => (
          <Modal title={item().name} text="解析内容预览 · 请结合原文件核验" wide onClose={() => setPreview(undefined)}>
            <div class="preview-meta">
              <Status value={item().status} />
              <span>{formatSize(item().size)}</span>
              <a href={download("/files/" + item().id + "/download")} download="">
                下载原文件
              </a>
            </div>
            <Show
              when={!previewBusy()}
              fallback={
                <div class="loading">
                  <Spinner />
                  正在读取内容
                </div>
              }
            >
              <Show when={item().error}>
                <ErrorLine message={parseError(item().error)} />
              </Show>
              <Show when={truncated()}>
                <div class="notice">仅预览部分内容，请下载原文件。</div>
              </Show>
              <Show when={chunks().length} fallback={<pre class="file-preview">{text()}</pre>}>
                <div class="file-preview parsed-preview">
                  <For each={chunks()}>
                    {(chunk, index) => (
                      <section class="source-block">
                        <div class="source-label">
                          <Icon name="file" size={13} />
                          {sourceLabel(chunk, index())}
                        </div>
                        <pre>{chunk.text}</pre>
                      </section>
                    )}
                  </For>
                </div>
              </Show>
            </Show>
          </Modal>
        )}
      </Show>
    </div>
  )
}
