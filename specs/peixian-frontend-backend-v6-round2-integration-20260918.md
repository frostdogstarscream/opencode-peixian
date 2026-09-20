# 沛县公安 Agent 平台前后端第二轮接口接入清单

日期：2026-09-18\
后端契约：`peixian-backend-v6-handoff-20260918(1)`\
前端源码：`/root/PeiXianDB/frontend-alignment/packages/peixian-console`\
部署：`/srv/peixian-alignment-20260917`\
站点：`https://36.134.45.38:19460`

## 1. 本轮结论

本轮已完成后端 v6 主要公开能力的前端接入并更新到服务器，覆盖用户端持久 Run、可信结构化结果、固定证据、能力目录、Skill 草稿，以及管理端模型测试、用户资料、部门管理和 Invocation 调用审计。

前后端仍保持分离：前端使用同源 `/api/console/v1`，认证依赖 HttpOnly Cookie、CSRF 与既有 SSE；没有把 Runtime 地址、账号 UID、服务器路径或私密凭据写入前端。此次未修改任何后端源码、数据库结构或接口契约。

## 2. 接入状态总表

| 所属界面 | 接口/能力 | 接入状态 | 联调结果 | 说明 |
|---|---|---:|---:|---|
| 登录与会话 | `POST /auth/login`、`GET /me` | 已有并继续使用 | 成功 | 管理员和普通用户真实登录成功；未回显凭据、Cookie 或 CSRF。 |
| 用户问答 | `GET /models` | 已接入 | 成功 | alignment-a 实际返回 1 个授权模型。 |
| 用户问答 | `GET /capabilities` | 已接入 | 成功 | 实际返回 12 项，包含 `official_skill`、`personal_skill`、`plugin`；7 项可用、5 项不可用。前端统一映射为 Skill/插件，并显示不可用原因、禁止选择不可用项。 |
| 用户问答 | `POST /sessions/{sid}/messages` v6 请求体 | 已接入 | 构建成功，未新触发模型 | 已发送 `mode=standard`、一次用户动作固定 UUID `client_request_id`、`skill_ids`、`plugin_ids`、`file_ids`；接收 `run_id` 和固定用户 `message_id`。为避免消耗真实模型额度，本轮没有额外提交新问题。 |
| 用户问答 | `GET /sessions/{sid}/runs` | 已接入 | 成功 | 多个真实会话均返回 Run；最终抽检会话返回 1 条，前序历史会话最多返回 9 条。刷新、重新登录和切换会话可恢复最近 Run。 |
| 用户问答 | `GET /sessions/{sid}/runs/{rid}` | 已接入 | 成功 | 七状态已映射；`cancelling`、`reconciling` 不再显示为已停止或失败。 |
| 用户问答 | `GET /sessions/{sid}/runs/{rid}/events` | 已接入 | 成功 | 真实返回步骤；按 `step.id` 合并，以最大 `sequence` 作为下一次 `after` 游标，不重复追加同一步骤。 |
| 用户问答 | `GET /sessions/{sid}/runs/{rid}/evidence` | 已接入 | 成功 | 真实返回固定 Run 证据；页面显示 pending/empty/partial/complete/unavailable 状态，不用模型文字冒充证据。 |
| 用户问答 | 消息 Part `analysis_result` | 已接入 | 成功 | 真实历史中检测到 2 个 `analysis_result` Part；只接受 `schema=peixian.analysis-result`、`version=1.0`，不解析模型 Markdown/JSON 文字。 |
| 用户问答 | `POST /sessions/{sid}/runs/{rid}/abort` | 已接入 | 未对运行中任务做破坏性实测 | 优先定向停止当前 Run；继续查询，只有 `cancelled` 才显示已确认停止。 |
| 用户问答 | `POST /sessions/{sid}/runs/{rid}/rerun` | 已接入 | 未触发真实重跑 | 使用新的 `client_request_id`，保留新 Run 与 `parent_run_id`；为避免额外模型调用未执行真实重跑。 |
| 用户问答 | `GET /sessions/{sid}/runs/{rid}/report` | 已接入 | 成功 | 终态 Run 实测返回 200、`text/markdown` 且内容非空；前端按文件下载，不按 JSON 解析。 |
| 用户问答 | SSE `run.updated` / `resources:runs` | 已接入 | 代码路径通过 | 前端事件资源表已加入 `runs`，收到通知后补查 GET；断线仍按既有退避重连和定时 GET 恢复，不重放消息 POST。未额外创建活跃 Run 捕获新通知。 |
| 用户问答 | 插件偏好 | 已接入 | 契约对齐 | `plugin_ids` 可选择并随消息提交；页面不再提示“后端不支持”。文案明确其为偏好，不作为严格插件白名单。 |
| Skill 创建 | `POST /skill-drafts/from-requirement` | 已接入 | 未触发真实模型生成 | 使用 UUID `client_request_id`、当前模型和需求文本；受理后轮询草稿状态。 |
| Skill 创建 | `POST /skill-drafts/from-session` | 已接入 | 未触发真实模型生成 | 使用本人当前会话，只生成方法草稿；前端不声称逐字提炼原文。 |
| Skill 创建 | `GET/PATCH /skill-drafts/{did}` | 已接入 | 类型检查/构建成功 | 支持 preparing/generating/ready/needs_review/failed/saved；编辑名称、描述、内容、依赖、输入 Schema 和默认规则。 |
| Skill 创建 | `POST /skill-drafts/{did}/test` | 已接入 | 未消耗模型实测 | 区分“结构检查”和“模型试运行”；模型试运行要求用户提供合成输入和新 UUID。 |
| Skill 创建 | `POST /skill-drafts/{did}/save` | 已接入 | 未创建持久草稿实测 | 仅 ready 可保存；提示“个人 Skill、默认停用、启用并等待配置生效”，不声称发布公共 Skill。 |
| 模型管理 | `GET/POST/PATCH /admin/models` | 已有并补齐字段 | 读取成功 | 已接入 provider、context_length、access_mode、supports_tools、默认与启停字段。 |
| 模型管理 | `POST /admin/models/test` | 已接入 | 未探测真实上游 | 新增保存前连接测试，提交当前表单完整配置但不落库；未主动探测生产上游。 |
| 模型管理 | `POST /admin/models/{mid}/test` | 已有 | 接口可用，未重复探测 | 保留保存后测试，并展示 message 与耗时。 |
| 用户与部门 | `GET /admin/users/summary` | 已接入 | 成功 | 返回 users/enabled/disabled/departments，替换前端自行估算。 |
| 用户与部门 | `GET /admin/users` profile 字段 | 已接入 | 成功 | 展示姓名、警号、职务、部门和最近登录；不把 `system_role` 当作提权输入。 |
| 用户与部门 | `POST/PATCH /admin/users` profile 字段 | 已接入 | 未修改真实账号资料 | 姓名、警号、职务已随保存提交；department_id 仅超管提交。 |
| 用户与部门 | `GET /admin/departments/tree` | 已接入 | 成功 | 当前真实树为空；前端递归展开 children，支持父部门选择。 |
| 用户与部门 | 部门 `POST/PATCH/DELETE` | 已接入 | 成功 | 临时部门创建 201、更新 200、删除 200；测试对象已删除。管理员只读，超管显示写操作。 |
| 调用审计 | `GET /admin/invocations` | 已接入 | 成功 | 最终抽检返回 14 条脱敏 Invocation；替换原 `/admin/audit` 伪映射。 |
| 调用审计 | `GET /admin/invocations/{iid}` | 已接入 | 成功 | 详情 200，steps 为数组；显示所选插件、实际插件、证据数和脱敏步骤。 |
| 调用审计 | `GET /admin/invocations/export` | 已接入 | 成功 | 实测 200、`text/csv`、UTF-8 BOM；前端按下载文件处理。 |
| 安全边界 | 跨账号 Run 访问 | 后端约束，前端不绕过 | 成功 | alignment-b 读取 alignment-a Run 列表返回 404。 |

## 3. 页面行为变化

### 用户问答页

- 提交动作生成并保留一个 `client_request_id`，接收 202 后进入 Run 状态显示。
- 页面显示“已受理、执行中、停止确认中、状态待核对、完成、失败、已取消”七种状态。
- Run 步骤默认是业务步骤摘要，不展示或推断模型隐藏思维。
- 终态提供“重新执行”和“导出报告”；非终态提供“停止执行”。
- 能力选择使用后端统一目录；不可用项禁选并展示原因。
- 消息内的可信结构化 Part 就地渲染，旧会话没有 Run 或没有可信 Part 时仍可查看原始文本与工具摘要。

### Skill 草稿页

- “从需求创建”和“从当前对话生成”均改用 v6 草稿接口。
- 生成阶段自动轮询；`needs_review` 只能继续编辑和结构检查，不能直接保存。
- “结构检查”不调用模型；“模型试运行”明确使用合成输入并创建独立 Run。

### 管理端

- 模型表单支持任意 provider、数值上下文长度、API/本地接入和工具能力声明。
- 用户与部门页面读取真实汇总和部门树，资料字段可保存。
- 调用审计使用独立 Invocation 接口，不再混用管理操作审计。

## 4. 尚未完成或仅部分验收

| 项目 | 当前状态 | 原因/建议 |
|---|---|---|
| 新消息、取消、重跑的真实模型全链路 | 已接入，未新增调用实测 | 避免未经确认消耗真实模型与插件调用额度。建议下一轮选择一条合成问题，分别验收 completed、cancelling、reconciling。 |
| Skill 草稿完整生成→试运行→保存 | 已接入，未新增持久草稿实测 | 生成与模型试运行会调用模型，保存会形成个人技能。建议由业务方提供一条无敏感信息的合成需求后验收。 |
| 保存前模型连接测试 | 已接入，未真实探测 | 会访问生产上游模型地址。建议管理员在维护窗口使用一条已确认配置测试。 |
| 用户资料写入 | 已接入，未改真实账号 | 避免改变当前联调账号姓名、警号和部门。建议新建专用临时普通账号验收后删除或禁用。 |
| Invocation 高级筛选 | 部分接入 | 当前支持页面文本筛选和导出时 query；start/end、uid、department_id、model_id、skill_id、status 尚未全部做成真实筛选控件。后端接口已足够，无需补接口。 |
| Run 历史选择器 | 部分接入 | 当前自动恢复最近/活动 Run；历史 Run 仍通过会话历史和审计查看，尚未提供独立 Run 列表抽屉。后端接口已足够。 |
| 报告错误状态提示 | 已接入基本下载 | 终态下载成功；若用户在非终态手工访问链接，后端 409。页面只在终态展示下载入口。 |
| 390/1366/1920 浏览器全量视觉验收 | 未执行 | 本轮以接口接入、类型检查、构建和 HTTP 联调为主；需后续浏览器专项验收。 |

## 5. 后端是否仍需补充接口

本轮没有发现阻塞第二轮接入的新接口缺口。现有 v6 契约足以支持当前页面。建议后端后续优化但不阻塞：

1. 如需跨会话恢复未完成 Skill 草稿，可增加本人草稿分页列表接口；当前只能凭已知 draft id 查询。
2. 如需在普通用户页面集中查看全部 Run，可增加本人跨会话 Run 分页聚合接口；当前可逐会话查询。
3. 如需避免前端轮询草稿，SSE 可增加明确的 `skill_draft.updated` 资源通知；当前轮询可正常工作。

以上均为体验增强，不是本轮前端接入失败项。

## 6. 验证记录

- TypeScript：`tsc --noEmit` 通过。
- Vite 生产构建：通过。
- 只读真实接口：管理员与普通用户登录、模型、用户、汇总、部门树、Invocation、能力目录、会话、消息、Run、步骤、固定证据全部成功。
- 安全可回滚写测试：临时部门创建/更新/删除成功并已清理。
- 下载：Invocation CSV 与终态 Run Markdown 报告成功。
- 隔离：跨账号 Run 请求返回 404。
- 服务器发布：正式控制台镜像为 `agent-platform-control:frontend-v6-round2-20260918`，镜像摘要 `sha256:557c567ed79a228a2f5e959cdd68fa4f02773b6acad21e3972561cbbf443e9f4`，控制台容器健康。
- 发布恢复：控制容器重建后旧 worker 注册态失效，首次恢复作业返回 `worker_boot_unregistered`；已重启正式 worker，并按官方 `pause → resume` 管理流程完成两账号安全恢复。最终 `alignment-a`、`alignment-b` 均为 `ready`、`recovery_required=false`，各自 agent/gateway/model-relay 容器健康。
- 最终在线复核：用户会话 200；能力目录 12 项（7 可用、5 不可用）；Run 列表、详情、事件、证据均为 200；管理端模型、用户、部门、Invocation 与作业接口均为 200。
- 未执行：全量浏览器验收、真实新模型生成、真实插件副作用、负载与故障注入。

## 7. 涉及前端文件

- `src/pages/Chat.tsx`
- `src/pages/FinalAdmin.tsx`
- `src/TrustedAnalysis.tsx`
- `src/types.ts`
- `src/events.ts`
- `src/styles.css`
