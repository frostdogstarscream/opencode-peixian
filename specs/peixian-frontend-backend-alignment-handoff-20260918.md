# 沛警智枢前端接入现状与后端补充接口交接清单

版本：V1.0\
日期：2026-09-18\
用途：后端开发、后端回执、第二轮前后端对齐与联调验收\

> 本文只记录接口契约、接入状态和验收要求，不包含密码、Cookie、CSRF、API Key、私钥或公安原始数据。后端完成开发后，请按第 10 节模板形成新的 Markdown 回执。

## 1. 基线与范围

| 项目 | 当前基线 |
| --- | --- |
| 实际源码工作区 | `/root/PeiXianDB/frontend-alignment` |
| 实际源码分支 | `frontend-alignment` |
| 本次复核 HEAD | `1bfd91f5b54d9a2f88877b5a9d35accae1b3dcc6` |
| 运行数据与部署目录 | `/srv/peixian-alignment-20260917` |
| 公网入口 | `https://36.134.45.38:19460` |
| API 前缀 | `/api/console/v1` |
| GitHub UI 需求基线 | `peixian-ui-final`，文档基线提交 `4c43143b1` |
| GitHub 需求文档 | `specs/peixian-backend-alignment-handoff.md` |
| 服务器既有接口文档 | PR7C，固定源码 `ea36aa8ec39bc319b66596f7774537891d8f0d97` |
| 结构化消息版本 | `peixian.analysis-result@1.0` |

说明：

- `/root/PeiXianDB/opencode` 不是本次统一入口控制台部署使用的源码工作区，不作为修改或验收基线。
- 复核时服务器工作区存在多组未提交修改和新增文件，包含其他并行工作。后端开发不得用覆盖工作区、`git reset --hard` 或清理未跟踪文件的方式处理。
- 本轮开始时前端修改仅在源码层；最终复核时检测到其他并行任务已经重建 `dist` 并重新创建控制台容器。本任务自身未执行 Docker 构建、重启或发布。

## 2. 架构结论：保持代码分离、部署同源

当前系统已经是前后端代码分离：

- 前端：`packages/peixian-console`，SolidJS + Vite。
- 控制后端：`services/peixian-control`。
- Runtime/Agent：独立容器，通过 Control 访问。
- HTTPS 入口：Nginx 将全部请求同源代理到 Console/Control 服务。

建议继续采用“代码分离、部署同源”，不新增浏览器跨域架构。原因：

1. 登录依赖 HttpOnly、Secure、SameSite Cookie。
2. 非 GET 请求依赖 `X-CSRF-Token`。
3. SSE、下载、文件预览均适合沿用同源会话。
4. 当前 `CONSOLE_ORIGINS` 是安全边界之一；只修改前端 API 地址不能自动获得跨域 Cookie 能力。
5. 强行拆成不同域名会同时影响 Cookie、Origin 校验、CSRF、SSE、下载及代理超时，改动和回归范围明显扩大，但没有产品收益。

结论：不做新的跨域分离改造。前后端继续独立开发、独立构建，通过同一 HTTPS 入口发布。

## 3. 当前访问与预览结论

### 3.1 当前线上入口

- 地址：`https://36.134.45.38:19460`
- TLS 证书 SAN 已包含 `36.134.45.38`、`127.0.0.1`、`localhost`。
- 证书为当前部署自签证书，首次访问需由测试环境显式信任。
- 已验证账号及角色：

| 账号 | 角色 | 2026-09-18 登录验证 |
| --- | --- | --- |
| `admin` | `super_admin` | HTTP 200 |
| `alignment-manager` | `admin` | HTTP 200 |
| `alignment-a` | `user` | HTTP 200 |
| `alignment-b` | `user` | HTTP 200 |

密码不写入本文。唯一凭据源为服务器：

- `/srv/peixian-alignment-20260917/private.json` 的 `accounts.<账号>.password`
- 管理员启动密码文件：`/srv/peixian-alignment-20260917/runtime/secrets/console-admin.password`

禁止把上述文件加入 Git、接口文档、测试截图或后端回执。

### 3.2 现在能看到什么

最终复核时，当前公网入口与服务器源码目录中的 `dist` 均加载：

```text
/assets/index-DHxt41A8.js
/assets/index-BSwnBSbi.css
```

线上 bundle 已检出新界面标记“用户与部门、调用审计、研判依据”，说明本轮前端已经由其他并行任务发布到当前控制台容器。因此现在可直接登录公网地址查看和测试新 UI，但后端缺失接口仍会限制对应功能闭环。

| 测试方式 | 现在是否可做 | 能否看到本轮新 UI | 是否使用真实后端 |
| --- | --- | --- | --- |
| 直接打开公网入口 | 可以，推荐 | 是 | 是 |
| 前端类型检查、单测、生产构建 | 可以 | 不涉及页面交互 | 否 |
| Vite/浏览器合成数据验收 | 可以 | 是 | 否，使用合成 API |
| 普通 HTTP Vite + SSH 转发 | 仅适合有限调试 | 是 | 不保证；受 Secure Cookie 与 Origin 限制 |
| HTTPS 同源临时预览网关 | 可以另行搭建 | 是 | 是 |
| 后续重建控制台镜像并发布 | 当前无需为“查看页面”重复执行 | 是 | 是，正式更新方式 |

本任务按要求没有重启 Docker。由于并行任务已经完成发布，正式登录、CSRF、SSE、文件下载和真实后端联调现在可以直接在公网 HTTPS 入口进行；尚未实现的后端接口仍按第 5 节推进。

### 3.3 已完成的源码级验证

- `git diff --check`：通过。
- 前端 TypeScript 类型检查：通过。
- 前端测试：57 项通过。
- 临时目录生产构建：通过，未覆盖正式 `dist`。
- 合成浏览器验收：8 个场景通过。
- 1366、1920、390 三种宽度检查：无页面级横向溢出。

这些结果证明前端源码可构建且主要交互可运行，不代表所有真实后端路径已经线上联调成功。

## 4. 页面级接入现状

状态定义：

- **已接入**：前端已调用当前正式接口。
- **适配接入**：后端没有 GitHub 目标接口，前端通过现有接口组合实现。
- **前端就绪**：页面和渲染已完成，但正式数据仍需后端补充。
- **未接入**：目标接口不存在或契约不足，前端不能完成真实闭环。
- **待发布验证**：源码与合成测试通过，尚未在新镜像上做真实登录联调。

| 所属界面 | 功能 | 当前使用接口 | 状态 | 接入结果/限制 |
| --- | --- | --- | --- | --- |
| 登录 | 品牌信息 | `GET /platform` | 已接入 | 成功；公网返回 200 |
| 登录 | 账号登录 | `POST /auth/login` | 已接入 | 四个部署账号均验证成功 |
| 全局 | 当前用户、CSRF、权限 | `GET /me` | 已接入 | 成功；组织与警务身份字段不足 |
| 全局 | 退出 | `POST /auth/logout` | 已接入 | 成功 |
| 个人设置 | 修改密码 | `POST /me/password` | 已接入 | 保留服务器新增能力 |
| 全局 | SSE 变化通知 | `GET /events` | 已接入 | 成功；仍需补充 Run 资源语义 |
| 智能研判 | 可用模型 | `GET /models` | 已接入 | 成功 |
| 智能研判 | 历史会话、新建、重命名、删除 | `/sessions*` | 已接入 | 成功 |
| 智能研判 | 消息读取 | `GET /sessions/{sid}/messages` | 已接入 | Markdown、工具信息、结构化 Part 渲染已准备 |
| 智能研判 | 消息提交 | `POST /sessions/{sid}/messages` | 部分接入 | 当前仅接受 `text/model_id/skill_ids/file_ids`；缺插件、模式、客户端幂等和持久 Run |
| 智能研判 | 中止 | `POST /sessions/{sid}/abort` | 已接入 | 成功；待同步持久 Run/审计状态 |
| 智能研判 | 文件上传、列表、预览、下载、删除 | `/files*` | 已接入 | 保留服务器文件闭环 |
| 智能研判 | 结果文件 | `/results*` | 已接入 | 保留服务器新增能力 |
| 能力选择 | Skill | `GET /skills` | 已接入 | 当前个人 Skill 为主；官方/部门范围字段不足 |
| 能力选择 | 插件 | `GET /plugins` | 已接入 | 可展示已授权插件；消息提交尚不能传 `plugin_ids` |
| 能力选择 | 统一能力目录 | 组合 `GET /skills` + `GET /plugins` | 适配接入 | UI 可用；缺统一可用性、依赖与范围判定 |
| Skill 创建 | 从需求/会话生成草稿 | `/skill-drafts/*` | 未接入 | 后端不存在，页面只能等待正式接口 |
| Skill 创建 | 草稿测试并保存 | `/skill-drafts/{id}/test|save` | 未接入 | 后端不存在 |
| 结构化研判 | `analysis_result` 渲染 | 消息 Part | 前端就绪 | 需后端稳定生产 `peixian.analysis-result@1.0` |
| 研判依据 | 会话证据扩展 | `GET /sessions/{sid}/evidence` | 已接入扩展 | 当前是会话级投影，非目标 Run 级契约 |
| 研判依据 | Run 状态/步骤/证据恢复 | `/sessions/{sid}/runs/{run_id}*` | 未接入 | 后端不存在持久 Run 查询资源 |
| 研判报告 | 修改条件重跑、导出 | `.../rerun`、`.../report` | 未接入 | 后端不存在 |
| 确认闭环 | 问题与权限确认 | `/questions*`、`/permissions*` | 已接入 | 保留服务器新增功能 |
| 模型管理 | 列表、新增、编辑、启停、默认、已保存测试 | `/admin/models*` | 已接入 | 当前字段少于目标 UI；保存前测试缺失 |
| 用户与部门 | 用户列表、新增、启停、授权、重置密码 | `/admin/users*` | 已接入 | 保留现有三角色权限；组织字段不足 |
| 用户与部门 | 用户汇总、部门树与 CRUD | `/admin/users/summary`、`/admin/departments*` | 未接入 | 后端不存在 |
| 调用审计 | 管理操作审计 | `GET /admin/audit` | 适配接入 | 只能展示管理操作，不等于业务调用审计 |
| 调用审计 | 业务调用列表、详情、导出 | `/admin/invocations*` | 未接入 | 后端不存在 |
| 隐藏能力配置 | 能力管理 UI | 现有插件/模板/连接接口 | 前端就绪 | 不进入主导航；等待产品确认入口 |
| 服务器扩展管理 | 连接、插件发布、模板、环境任务、恢复、维护、诊断 | 服务器既有 `/admin/*` | 已保留 | 不因 UI 主线迁移删除；保持原权限边界 |

## 5. 后端开发清单

### 5.1 P0：第二轮正式联调前必须完成

#### BE-P0-01 消息提交扩展与真实 Run

目标：扩展 `POST /sessions/{sid}/messages`。

当前实现通过字段白名单只保留：

```json
{"text":"...","model_id":"...","skill_ids":[],"file_ids":[]}
```

目标请求：

```json
{
  "text": "分析最近30天夜间活动",
  "model_id": "mdl_01",
  "skill_ids": ["skill_01"],
  "plugin_ids": ["plugin_01"],
  "file_ids": ["file_01"],
  "mode": "standard",
  "client_request_id": "UUID"
}
```

目标响应为 HTTP 202：

```json
{"accepted":true,"run_id":"run_01","message_id":"msg_user_01"}
```

必须满足：

1. 校验模型、Skill、插件、文件均已启用且授权给当前用户。
2. 执行前校验 Skill/插件依赖和 Runtime 应用状态；不可用返回 409 和稳定 `code`。
3. 对 `user_id + session_id + client_request_id` 幂等；同键同内容返回首次结果，同键不同内容返回 409。
4. `run_id` 必须对应数据库中的持久 Run，不能使用与执行状态无关的随机回执。
5. 创建 Run、Invocation、用户消息后再异步执行；中止时同步更新未结束记录。
6. 服务端继续执行数量、文本长度、UTF-8 字节与文件预算限制，并返回 `field_errors`。

验收：重复提交不产生第二个 Run；刷新页面后仍可查询 Run；无权插件在模型执行前被拒绝。

#### BE-P0-02 持久 Run 查询与实际步骤

新增：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/sessions/{sid}/runs/{run_id}` | 状态恢复、关联模型与消息 |
| GET | `/sessions/{sid}/runs/{run_id}/events` | 实际执行步骤回放 |
| GET | `/sessions/{sid}/runs/{run_id}/evidence` | Run 级脱敏证据链 |

Run 最少字段：

```json
{
  "id": "run_01",
  "session_id": "ses_01",
  "status": "queued|running|completed|failed|cancelled",
  "model_id": "mdl_01",
  "message_id": "msg_assistant_01",
  "created_at": "ISO-8601",
  "started_at": "ISO-8601|null",
  "completed_at": "ISO-8601|null",
  "error": null
}
```

事件字段至少包括：`id/sequence/step_type/name/status/started_at/completed_at/elapsed_ms/input_summary/output_summary/record_count/capability_id/evidence_refs/error_message`。

约束：

- `step_type` 使用 `requirement|skill|plugin|analysis|result`。
- 步骤必须由 Runtime 实际状态回写，禁止在请求开始时一次性伪造全部成功步骤。
- 只返回执行摘要，不返回模型隐藏思维链。
- `/sessions/{sid}/evidence` 可暂时保留兼容，但新 UI 的可恢复依据应以 Run 级接口为准。
- 所有查询同时校验用户、会话、Run 的归属关系。

验收：执行中刷新浏览器，页面可恢复同一 Run；中止后 Run 和未完成步骤为 `cancelled`；跨账号 ID 返回 404。

#### BE-P0-03 结构化研判 Part

`GET /sessions/{sid}/messages` 的助手消息需在结构化场景返回：

```json
{
  "id": "part_01",
  "type": "analysis_result",
  "data": {
    "schema": "peixian.analysis-result",
    "version": "1.0",
    "run_id": "run_01",
    "generated_at": "ISO-8601",
    "intro": "...",
    "process": [],
    "subjects": [],
    "conclusions": [],
    "evidence": [],
    "next_steps": "...",
    "clues": []
  }
}
```

约束：`process/subjects/conclusions/evidence/clues` 即使为空也返回数组；不得把 JSON 塞入 Markdown 代码块；证据最多由前端展示前 4 项；敏感信息由后端脱敏。

验收：普通问答只返回 `text`；结构化消息刷新后仍能渲染；未知版本前端安全降级。

#### BE-P0-04 统一能力目录

新增或正式确认 `GET /capabilities`。建议对象：

```json
{
  "id": "plugin_01",
  "kind": "official_skill|personal_skill|plugin",
  "name": "轨迹查询",
  "description": "...",
  "version": "1.0.0",
  "category": "轨迹",
  "recommended": false,
  "enabled": true,
  "owned": false,
  "scope": "personal|department|official",
  "available": true,
  "unavailable_reason": null,
  "dependency_ids": []
}
```

后端负责聚合并过滤个人 Skill、官方/部门 Skill、插件授权、连接依赖与 Runtime 可用性。真实为空就返回空数组，不注入演示项。

如后端决定长期不提供统一接口，必须在回执中确认以下稳定契约：前端继续组合 `/skills` 与 `/plugins`；两端分别补齐上述 `kind/scope/available/unavailable_reason/dependency_ids` 语义，且筛选结果与消息提交校验一致。

#### BE-P0-05 模型管理补齐

现有接口保留，补充：

- `POST /admin/models/test`：保存前测试，不落库。
- 列表/详情字段：`provider/context_length/access_mode/supports_tools/test_status/updated_at/api_key_configured`。
- 新增/编辑接受同名配置字段；`api_key` 为只写，响应永不回传明文。
- 保存前测试与已保存测试统一返回：`ok/message/elapsed_ms`。
- 同时只能有一个“已启用且默认”的模型。

前端在后端完成前不会伪造保存前测试，也不会提交当前后端不支持的展示字段。

#### BE-P0-06 用户组织字段、汇总与部门

扩展登录、`GET /me` 与管理用户对象：

```json
{
  "id": "usr_01",
  "username": "320722099",
  "display_name": "张警官",
  "police_no": "320722099",
  "system_role": "user",
  "position": "民警",
  "department_id": "dept_01",
  "department": {"id":"dept_01","name":"刑警大队","code":"32032201"},
  "active": true,
  "last_login_at": "ISO-8601|null"
}
```

`system_role` 与 `position` 必须分开，不能用警务职务推断系统权限。新增：

| 方法 | 路径 |
| --- | --- |
| GET | `/admin/users/summary` |
| GET | `/admin/departments/tree` |
| POST | `/admin/departments` |
| PATCH | `/admin/departments/{id}` |
| DELETE | `/admin/departments/{id}` |

删除非空部门返回 409；账号停用、重置密码继续立即撤销已有认证。保留现有 `super_admin/admin/user` 权限边界，不能为了页面字段而放宽管理权限。

#### BE-P0-07 业务调用审计

新增 `GET /admin/invocations`，区别于现有管理操作审计 `/admin/audit`。

查询参数：`page/page_size/query/start/end/uid/department_id/model_id/skill_id/status`。

列表首屏必需字段：

`id/run_id/session_id/created_at/username/display_name/department_name/model_id/model_name/status/duration_ms/record_count/query_summary`

`query_summary` 必须短且脱敏。不得记录密码、Cookie、CSRF、API Key、完整身份证/手机号、未经脱敏的原文、上游完整原始响应或模型思维链。

验收：一次真实消息调用可以通过 `run_id` 在 Run、Invocation、结构化消息与证据间追踪；普通 admin 只能看到获准审计范围。

#### BE-P0-08 SSE 资源语义

现有 `GET /events` 保持。至少增加或稳定支持：

```text
event: change
data: {"type":"run.updated","resources":["runs","messages","sessions"],"session_id":"ses_01","run_id":"run_01","updated_at":"ISO-8601"}
```

心跳不能使用 `change`。SSE 只做“需要刷新”的通知，真实状态仍由持久 GET 接口恢复；断线重连不得自动重放消息写请求。

### 5.2 P1：P0 稳定后完成

#### BE-P1-01 Skill 草稿闭环

新增：

- `POST /skill-drafts/from-requirement`
- `POST /skill-drafts/from-session`
- `GET /skill-drafts/{id}`
- `PATCH /skill-drafts/{id}`
- `POST /skill-drafts/{id}/test`
- `POST /skill-drafts/{id}/save`

草稿字段至少包括：`id/session_id/source_type/status/name/description/content/dependency_ids/input_schema/default_rules/error/created_at/updated_at`。

从会话生成时必须校验会话与消息归属；只能沉淀方法、参数、依赖和规则，不能把人员、身份证、轨迹等具体敏感事实写进 `SKILL.md`。保存后的用户内容固定为 `scope=personal`。

#### BE-P1-02 重跑与报告导出

新增：

- `POST /sessions/{sid}/runs/{run_id}/rerun`
- `GET /sessions/{sid}/runs/{run_id}/report`

重跑返回新的持久 `run_id`，保留父子关联；原 Run 不被覆盖。报告需明确 `Content-Type`、文件名、字符集、脱敏与审计规则。建议首版支持 PDF 或 DOCX 中的一种，不用前端猜测扩展名。

#### BE-P1-03 调用审计详情与导出

新增：

- `GET /admin/invocations/{id}`，包含与 Run event 相同结构的 `steps`。
- `GET /admin/invocations/export`，筛选条件与列表完全一致，建议 UTF-8 BOM CSV。

## 6. 后端无需重复开发、不得回退的现有能力

下列能力当前已有接口并被前端保留。后端新开发应兼容，不要用新页面需求替换或删除：

- 平台品牌、登录、Cookie、CSRF、退出、首次改密。
- 三角色权限、capability 菜单与逐接口鉴权。
- Runtime 状态、按需启停、容量与维护态语义。
- 模型、会话、消息、abort。
- 文件上传、解析、预览、正文、下载、删除与结果文件。
- 个人 Skill CRUD/test/rollback、模板复制。
- 插件安装配置/test/rollback。
- questions/permissions 确认闭环。
- 个人 Token。
- 管理端模型、用户、插件发布、模板、连接、任务、恢复、维护、诊断和管理审计。
- 会话归属、资源 ID 归属、下载权限、密码重置后撤销认证等安全边界。

## 7. 全局接口约束

1. 所有业务路径相对于 `/api/console/v1`。
2. Cookie 请求使用 `credentials: same-origin`；非 GET/HEAD 携带 `X-CSRF-Token`。
3. 普通用户访问 `/admin/*` 必须由后端返回 403，不能只隐藏前端入口。
4. 列表新增接口统一返回 `items/total/page/page_size`；`page` 从 1 开始，`page_size` 最大 100。
5. 新时间字段使用 ISO 8601；同一字段不得混用秒、毫秒和字符串。
6. 通用错误结构：`message/code/request_id/field_errors`。
7. 401 会使前端停止 SSE 并返回登录；403 表示已登录但无权限；409 表示状态、依赖或幂等冲突；429/503 允许有界退避。
8. 所有公安数据通过服务端适配层访问、授权、脱敏和审计，前端不得直连数据源。
9. 日志和响应不得包含堆栈、SQL、内网凭据、密码、Cookie、CSRF、API Key、完整敏感身份数据或模型隐藏思维过程。

## 8. 后端交付验收矩阵

| 编号 | 验收场景 | 预期结果 |
| --- | --- | --- |
| A-01 | 四角色/账号登录与菜单 | 角色和 capability 一致，越权接口 403 |
| A-02 | 消息含 Skill、插件、文件 | 授权与依赖通过后创建一个持久 Run |
| A-03 | 同 `client_request_id` 重试 | 不产生重复消息、Run、Invocation |
| A-04 | 执行中刷新页面 | 恢复同一 Run、步骤、消息和证据 |
| A-05 | 中止执行 | Run、未完成步骤、Invocation 变为 cancelled |
| A-06 | 跨账号访问会话/Run/证据 | 返回 404，不泄露资源存在性 |
| A-07 | 结构化研判结果 | `analysis_result@1.0` 正常渲染，普通回答仍为 Markdown |
| A-08 | 能力依赖不可用 | 选择时标记 unavailable，提交时 409，不进入模型执行 |
| A-09 | 保存前模型测试 | 不落库、不回传密钥，返回真实耗时和结果 |
| A-10 | 部门删除冲突 | 非空部门返回 409 和稳定错误码 |
| A-11 | 调用审计追踪 | session/run/invocation/trace 可关联且内容已脱敏 |
| A-12 | SSE 断线重连 | 仅补查 GET，不重复写消息 |
| A-13 | 账号停用/重置密码 | 旧 Cookie、SSE、Token 按现有安全规则失效 |
| A-14 | 真实空能力目录 | 返回空数组，不自动注入演示数据 |

## 9. 第二轮前端接入顺序

后端回执后，前端按以下顺序联调：

1. 对比后端 OpenAPI 与本文，先锁定字段和错误码。
2. 接入消息扩展、持久 Run、SSE 和 `analysis_result`，打通智能研判主链路。
3. 接入统一能力目录或确认后的双目录稳定契约。
4. 接入模型保存前测试、组织字段、部门和业务调用审计。
5. 接入 Skill 草稿、重跑、报告、审计详情与导出。
6. 在 HTTPS 同源环境完成四账号真实联调。
7. 运行类型检查、单测、生产构建、桌面/移动浏览器验收和跨账号权限测试。
8. 形成第二轮“已接入/未接入/失败原因/后端版本/证据”清单后再决定发布。

## 10. 后端完成后的 Markdown 回执模板

后端请新建独立 Markdown，不要覆盖本文，至少包含：

```markdown
# 沛警智枢后端接口补充开发回执

## 1. 交付基线
- 源码目录：
- 分支：
- 提交：
- OpenAPI 文件及 SHA256：
- 数据库迁移编号：
- 部署环境/镜像标签：

## 2. 接口完成表
| 本文编号 | 方法与路径 | 状态（完成/部分/未做） | 实际请求/响应差异 | 权限 | 错误码 | 自动化测试 |

## 3. 数据库与迁移
- 新表/字段/索引：
- 向前与回滚策略：
- 历史数据兼容：

## 4. 安全说明
- 资源归属：
- 脱敏：
- 审计：
- 幂等：
- 限流：

## 5. 测试证据
- 单测/集成测试命令与结果：
- 四角色测试：
- 跨账号拒绝测试：
- 刷新恢复与中止测试：

## 6. 未完成项和协商项
- 未完成原因：
- 临时兼容方式：
- 建议前端调整：

## 7. 联调信息
- 可联调 URL：
- 可用账号名称（不写密码）：
- 凭据安全获取位置：
- 已知限制：
```

后端回执中禁止粘贴任何明文密码、密钥、Cookie、CSRF、公安原始数据或模型内部思维过程。

## 11. 本轮结论

1. 当前前后端已经代码分离，无需改成浏览器跨域部署；继续同源发布影响最小、安全边界最清晰。
2. GitHub 主线 UI 已迁入服务器源码，服务器新增页面和管理能力得到保留；前端源码验证通过，且最终复核时已由其他并行任务发布到公网控制台。
3. 当前可直接登录公网控制台查看本轮新 UI 并连接真实后端；本任务自身没有重启 Docker。后端尚未实现的功能会在界面中表现为缺数据、不可操作或接口失败，需按本文清单补齐。
4. 主要阻断项不是页面，而是消息插件选择、持久 Run、结构化结果生产、统一能力可用性、组织部门、业务调用审计和保存前模型测试。
5. 后端按本文完成并提交 Markdown 回执后，再进入第二轮接口对齐、真实联调与发布评估。
