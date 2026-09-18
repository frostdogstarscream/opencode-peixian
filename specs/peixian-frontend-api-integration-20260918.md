# 前端联调接口文档：后端 v6

## 1. 使用范围与版本

本文件为本轮新增后端能力的接入入口，与同目录 `peixian-backend-v6.openapi.json` 配套。字段附录 `peixian-frontend-api-field-reference-20260918.md` 与 OpenAPI 覆盖每个公开接口的请求、响应、类型、权限、分页和错误结构；不要继续从旧 Mock 推断字段。基线 da76198e689adf1b027f3c523b62395ee2a6d471；三角色 super_admin/admin/user，四个测试账号是账号数量，不是四角色。

独立验收地址在服务器回环：`https://127.0.0.1:19470`，不能在客户端把127.0.0.1直接解释为服务器。现有测试站点 `https://36.134.45.38:19460` 已发布本轮 v6 后端；四账号和原前端资源保留。新增界面能力仍需前端按本文二次接入。

前缀 `/api/console/v1`。所有资源以当前认证账号归属为准；不传 uid、Runtime 地址或文件系统路径来选择账号。涉及新字段的时间是带时区 ISO8601（UTC Z）；已有数值时间字段维持原类型。

## 2. 认证、CSRF 与两种请求标识

POST /auth/login，JSON `{"username":"alignment-a","password":"从安全渠道获取"}`。成功响应包含 user、csrf_token；浏览器以 credentials:include 保存 HttpOnly px_session。Cookie 写操作发送同源 Origin、X-CSRF-Token。首次 must_change_password=true 先调用 POST /me/password，字段 current_password/password；密码修改后按返回状态重新登录。

GET /me 返回身份、权限和本人环境；system_role 是 user.role 的只读别名，不能用于提升权限。退出 POST /auth/logout，清理 SSE、缓存、草稿输入的内存状态。Python 使用个人设置创建的 Bearer Token；不要同时发送 Cookie 和 Bearer。401 回登录，403 显示权限或首次改密提示，不无限重试。

管理配置写入以及个人 Skill 配置、草稿编辑/保存使用 `Idempotency-Key`，8至100位字母数字下划线连字符。具体是否必填见 OpenAPI header。相同键、相同内容重放首次结果；内容冲突409。网络错误后先确认状态，不能换键盲写。

消息、重跑、草稿生成及模型试运行使用请求体 `client_request_id` UUID。一个明确用户动作生成一次，保留到结果确认。同一消息键、同一内容返回原受理；不同内容409。重跑是新动作必须新键。旧客户端不提供时服务端生成，不能保护客户端重新 POST 的重复执行。草稿生成不需要 Idempotency-Key；编辑/保存需要；不要将两类语义混用。

通用错误示例：
```json
{"message":"首版仅支持standard模式","code":"unsupported_mode","request_id":"排查编号","field_errors":{"mode":"standard"}}
```
保留服务端实际 detail/message 兼容字段；显示业务文本，不展示堆栈。429/503 按 Retry-After 退避读取；504或提交断线为结果未知，先查询 Run，不自动重发。新增分页 `{items:[],total:0,page:1,page_size:20}`；page从1开始，page_size最多100。旧列表仍可能直接数组。

## 3. 一次完整对话

1. GET /me 确认环境；必要时按原接口启动环境，等待 ready。
2. GET /models、GET /capabilities 选择实际 available 的资源。
3. POST /sessions 创建会话；上传文件沿用 POST /files multipart。
4. POST /sessions/{sid}/messages：
```json
{"text":"整理所选场景资料","model_id":"模型ID","skill_ids":[],"plugin_ids":[],"file_ids":[],"mode":"standard","client_request_id":"22222222-2222-4222-8222-222222222222"}
```
只支持standard；每类资源最多5个不同ID。保留原字符、UTF8字节和文件引用预算，字段错误不调用模型。
```json
{"accepted":true,"run_id":"执行ID","message_id":"msg_固定用户消息ID"}
```
HTTP202仅表示持久受理，不表示模型完成。保存 run_id；同一会话已有未结束执行返回409 session_busy，保留输入，不静默排队。

5. GET /sessions/{sid}/runs/{rid} 查询执行；GET /sessions/{sid}/runs 恢复最近执行（分页）。Run.id 是执行ID，user_message_id 是受理时固定用户消息，message_id 在详情中是可能为空的最终助手消息ID，不能混淆这两个位置的 message_id。
6. GET /events?session_id={sid} 建立原有 SSE，收到 event:change 的 data.type=run.updated、resources含runs时，补查 Run、步骤、消息和必要证据。事件只做失效通知，不作为事实存储。
7. GET /sessions/{sid}/messages 获取原始安全消息及服务端补充 Part。GET /sessions/{sid}/runs/{rid}/evidence 获取该次固定证据。旧会话仍可 GET /sessions/{sid}/evidence；旧历史没有 Run 是正常状态。

| status | 页面建议 | 是否终态 |
|---|---|---|
| queued | 已受理，等待投递 | 否 |
| running | 执行中；phase可表示等待权限/问题回复 | 否 |
| cancelling | 正在请求停止 | 否 |
| reconciling | 执行状态待核对，请勿重复提交 | 否 |
| completed | 执行结束；仍需检查证据是否有效 | 是 |
| failed | 执行失败，保留已取得内容 | 是 |
| cancelled | 已确认执行终止 | 是 |

GET /runs/{rid}/events 支持 page/page_size/after（均在sessions/{sid}下）。初次after=0；按step.id合并或替换，用最大sequence做下次游标。状态更新沿用id但sequence增长；不能只追加否则会重复步骤。分页时先固定查询after取完本页，再推进游标。name/input_summary/output_summary是白名单业务文本，无隐藏思维。时间未知为null，不用页面当前时间代替。

SSE断线后GET恢复并退避重连；不重放消息POST。切换会话清理旧Run/卡片请求，用会话和请求代次防止迟到响应覆盖新会话。通知可能合并，不承诺逐条事件投递。

## 4. 结构化结果与证据

消息Part `type=analysis_result`、`data.schema=peixian.analysis-result`、`data.version=1.0`。process/subjects/conclusions/evidence/clues总为数组；conclusions为字符串数组，conclusion_sources保存对应来源。来源和快照在source_metadata，presentation_version为展示版本。没有可靠人物画像时subjects为空，不补Mock示例；next_steps为空字符串时隐藏。

只消费服务端消息接口返回的Part，不从模型text里的JSON、Markdown代码块或同名字段再解析事实。未知schema/version保留普通消息并提示更新客户端，不按1.0强行解释。

Run evidence 在未生成证据时返回pending及空数组；授权撤销可为unavailable。模型回答完成但没有可信工具结果时不显示“取数成功”。普通用户只能读取本人资源，跨账号Run、证据、步骤、报告、草稿404。

## 5. 中止、重跑和报告

POST /sessions/{sid}/runs/{rid}/abort 返回202 Run；可能cancelling/reconciling。原会话abort继续可用。继续查询，只有cancelled才显示已停止；不能声称已撤销外部系统写操作。

POST /sessions/{sid}/runs/{rid}/rerun，请求至少新client_request_id，可覆盖text/model_id/skill_ids/plugin_ids/file_ids/mode。只允许白名单字段；返回202新Run，parent_run_id指向原Run，原Run不覆盖。原执行必须终态，重新验证当前授权和文件有效性。不得添加固定工具不支持的人员、时间、分页参数。

GET /sessions/{sid}/runs/{rid}/report：未终态409 run_not_finished；终态返回text/markdown;charset=utf-8，Content-Disposition为安全.md文件名。失败/取消也可导出状态与已有资料，不编造成功结果。报告含来源、版本和必要数据性质说明。浏览器下载Blob后释放objectURL，不能按JSON解析。

## 6. 能力目录与插件偏好

GET /capabilities（page/page_size）返回id/kind/name/description/version/category/recommended/enabled/owned/scope/available/unavailable_reason/dependency_ids。

kind=personal_skill/plugin/official_skill。模板copy_required，先用现有模板复制接口形成个人技能，等待启用和配置生效。不存在部门Skill发布能力，不显示虚构部门集合。

plugin_ids只表示本次选择偏好。模型仍可调用账号其他获授权、启用且applied的插件；不能用它实现本次严格工具禁用。Invocation.plugin_ids记录选择；actual_plugin_ids记录实际识别到的调用；两者不相等不一定异常。Skill dependency_ids声明依赖，不授予权限。目录available和提交使用同一判定，但两请求之间仍可能授权变更，提交错误需刷新目录。

## 7. 模型、用户与部门

GET/POST /admin/models、PATCH /admin/models/{mid} 沿用原字段，增加provider字符串、context_length可空整数256..2000000、access_mode=api/local、supports_tools布尔。输出test_status/updated_at；api_key只写，不回显。最多一个启用默认模型，设置新默认在事务内清除旧默认。

POST /admin/models/test 使用完整模型创建请求，保存前测试，不落模型记录。POST /admin/models/{mid}/test 测试保存配置。响应 `{ok:true,message:"连接及模型ID已确认",elapsed_ms:123}`。失败可ok=false；只验证GET models列出的模型，不证明生成质量和工具调用，supports_tools来源是管理员声明。

GET /admin/users 兼容原结构，profile补充display_name/police_no/position/department_id/department/last_login_at。POST/PATCH同名字段可写但department_id仅超管；system_role和last_login_at只读。GET /admin/users/summary返回users/enabled/disabled/departments，范围为当前角色可管理账号。

GET /admin/departments/tree 两管理角色可读；POST /admin/departments、PATCH/DELETE /admin/departments/{did}仅超管。字段name/code/parent_id/sort_order；parent_id为空为根；树节点children数组。禁止环，存在子部门或账号关联删除409。升级账号部门为空，不自动猜测。

## 8. 调用审计

GET /admin/invocations、GET /admin/invocations/{iid}、GET /admin/invocations/export，两类管理员仅查看普通用户脱敏元数据。

过滤：page/page_size、query（用户名或脱敏摘要，最多100字符）、start（含）、end（不含）、uid、department_id、model_id、skill_id、status。时间必须带时区。导出复用过滤，忽略分页、最多10000条，超限413。

Invocation含id/run_id/session_id/username/display_name/department_name/model_id/model_name/status/query_summary/created_at/duration_ms/record_count/skill_ids/plugin_ids/actual_plugin_ids，详情加steps。record_count是已核对证据卡片数，非原始记录总数。query_summary来自请求类型，不截取用户问题。

导出为text/csv;charset=utf-8、UTF8 BOM、attachment。公式前缀已处理。管理员不能通过session_id进入用户会话；该ID仅关联排查。操作审计/admin/audit与业务Invocation分开。

## 9. Skill草稿流程

POST /skill-drafts/from-requirement：requirement(1..4000字符)、model_id、client_request_id。
POST /skill-drafts/from-session：session_id、model_id、client_request_id，只能本人会话。
均202返回Draft；GET /skill-drafts/{did}轮询。status为preparing/generating/ready/needs_review/failed/saved。生成不调用工具，草稿不是已验证方法。

Draft字段：id/session_id/source_type/status/run_id/saved_skill_id/scope=personal/error/created_at/updated_at/name/description/content/dependency_ids/input_schema/default_rules。PATCH同路径接受后七项编辑字段，Idempotency-Key必填；生成中或已保存409。name1..60、description最多500、content1..32000，依赖最多20个且已授权，input_schema合法JSON Schema最多8000编码字符、default_rules最多20条每条500字符。

POST /skill-drafts/{did}/test：
- `{mode:"validation"}`：返回ok/field_errors/model_executed=false，不调用模型。
- `{mode:"model",text:"合成测试输入",model_id:"ID",client_request_id:"新UUID"}`：检查依赖实际可用后创建独立会话和Run，返回accepted/session_id/run_id/message_id，model_executed=null表示刚受理未知。GET对应Run确认结果；不预先安装草稿。失败不自动重试。

POST /skill-drafts/{did}/save 请求{}并带Idempotency-Key，必须ready。响应skill_id/scope=personal/enabled=false/job/already_saved。再次保存返回原ID。前端提示“已保存为个人技能，启用后等待生效”，不提示已发布公共技能。启用沿用PATCH /skills/{id}；等待配置applied后才可选择。

草稿生成会最小化会话来源信息并作敏感标识检查；规则无法识别所有个人信息，用户仍须审阅。needs_review不得直接保存。from-session生成的是方法概括，不是原始对话逐字提炼。

## 10. 联调账号与用例

现有站点：admin（super_admin）、alignment-manager（admin）、alignment-a/alignment-b（user）。独立验收站点对应admin/test-manager/test-a/test-b。密码不在Git、文档、示例或OpenAPI中；由部署负责人从服务器私密凭据文件按账号提供，或通过超管重置流程发放临时密码，不在群聊公开。

前端逐项验收：登录改密→同源Cookie/CSRF；角色菜单；能力不可用提示；202后刷新恢复同Run；相同键不重复；busy保留草稿；SSE断线GET补齐；切会话不残留；等待问题/权限回复；取消待确认；跨账号404；可信Part空状态；草稿检查与试运行区别；个人保存待生效；CSV和Markdown下载；390/1366/1920布局。以上页面联调由前端二次接入执行，本轮后端测试不能代替。

## 11. 升级与安全边界

Control、Gateway、Agent必须是匹配版本，新Agent支持durable_run_v1。旧Agent提交返回409，不假装受理。schema v6旧镜像禁止直连；全量备份包括控制库、用户卷、发布目录和匹配密钥。先停旧写入组件，冻结并确认任务清空后迁移；回退到兼容版本或恢复到空目标，禁止降版本号覆盖新数据。

发布操作必须使用 `platform-manage.py up --config <配置>`，该命令负责恢复 Control 动态管理网络。直接 docker compose 替换 Control 会跳过网络恢复，可能触发安全保护；不得通过改数据库或忽略启动身份来绕过。

Agent 发布镜像必须设置 `OPENCODE_DISABLE_CHANNEL_DB=1`，继续使用原 opencode.db，避免自定义构建通道选择新库导致旧会话暂时不可见。镜像升级应形成新的配置发布版本，重试原版本或单纯resume不会替换不可变发布目录中的旧镜像。
