# PR-5 TaskSpec 与固定路由接口说明

## 范围与开启方式

依据第二阶段 V1.1，仅实现 PR-5；基线 ecefc20a01949b0ebd7f5c966608cf6762d310c9。数据库保持 schema v6。既有七插件、官方方法正文与前端不变。默认不开启新路由。

Control 环境变量 `PX_TASKSPEC_V1_UIDS` 为逗号分隔的完整账号 ID 白名单；只匹配精确 ID，不接受用户名或 `*`。本轮没有修改线上环境变量、构建发布镜像或升级 A/B。部署时必须先完成第一阶段匹配镜像与在线验收，再按专门发布清单开启。

关闭白名单只使后续新请求使用原行为。已经受理的任务继续使用冻结快照；不是删除或重算历史任务。当前源码可以读取旧 Run；旧代码能否执行新快照不能仅凭 schema 未变化推断，回退前应排空或妥善核对新任务。

## 消息受理契约

沿用 `POST /api/console/v1/sessions/{sid}/messages`、登录 Cookie/CSRF 或账号令牌、`client_request_id` UUID，以及原 text/model_id/skill_ids/plugin_ids/file_ids/mode/agent_id 字段。

客户端不能提交 task_spec、query_mode、intent、methods、official_skill_ids、target_refs、target_mode、allowed_capabilities、allowed_tools、source_data_run_id 或 TaskCandidate。未知字段沿用既有 HTTP 400 整体拒绝行为；不改变既有接口错误码为 422。

```json
{"text":"看看资金往来","agent_id":"gambling-assistant","skill_ids":[],"plugin_ids":[],"file_ids":[],"mode":"standard","client_request_id":"00000000-0000-4000-8000-000000000001"}
```

HTTP 202 仍返回 accepted/run_id/message_id。同账号、同会话、同请求标识、同内容返回原受理结果；内容冲突 409。重放不重新解析场景、对象或最新授权，不产生二次执行。新请求仍重新检查当前权限；一个会话只允许一个活动 Run。

任务判断顺序为：数据任务 → query_mode 与冲突 → 场景 → 固定 intent → 对象支持 → 官方副本 → 固定 facts_plan。不是看到所选 Skill 就查询。

| 输入情形 | PR-5 行为 |
|---|---|
| 看看资金往来 | 场景确定且拥有可用官方副本时，仅批准 funds |
| 核对同行 | 仅批准 companions、人像共现插件 |
| 查询已有关系 | relations，需要 lookup 与 composite |
| 综合整理 | 对应场景官方总流程的固定方法集合 |
| 选资金 Skill，但说不要重新查 | explain_existing；零取数、零模型投递 |
| 不要重新查，但更新最新资料 | clarify；需要确认是否重新查询 |
| 资金碰撞是什么意思、你好 | 普通对话，无 TaskSpec；禁用所有工具 |
| 多方法表达但未明确综合整理 | 澄清，不静默扩大 |
| 无场景、未知方法、未知姓名、自定义日期范围 | 澄清，不替换成固定主对象 |
| 资金问题却选夜间专项 | 方法冲突，澄清 |
| 总流程 Skill 下仅问资金 | 允许收窄为 funds，不执行整个总流程 |

PR-5 使用固定中文表达匹配和保守目标语法，不是通用中文理解器。不确定表达可以被澄清；不会用模型置信度获得执行权限。用户资料、引用正文和模型输出不作为任务授权输入。现有场景续接/重置边界被复用；没有实现 PR-6 Session Task Context、双 Run 引用或历史 Claim 解释。

## 零取数分支

explain_existing 和 clarify 在现有 Run 中保存确定性答复，状态为 completed，phase 分别为 history_unavailable / clarification。不创建 run_deliveries，不调用 Agent/模型/资料插件，不生成新资料快照。这里 completed 只表示路由答复完成，不表示取得数据。

历史解释明确答复“本轮没有重新查询，完整历史结果解释将在下一阶段提供”，不声称已经读取或核验历史事实。不提供 PR-7 clarification_id、resolve/cancel 选项写接口；用户可提交新的明确请求。

`GET /sessions/{sid}/messages` 以服务端文本投影补充本地受理的用户问题和答复，不写入 Agent 历史、不修改旧消息。会话/Run evidence 保持空结果及明确原因，报告包含同一原因。对消息投影的源码测试不能代替前端实际联调。

## 新增只读接口

`GET /api/console/v1/sessions/{sid}/runs/{rid}/task`

仅本人账号、本人会话可访问。其他账号或错误会话返回 404；不提供写接口。示例：

```json
{
  "run_id":"run-id",
  "task_spec":{
    "schema_version":"task-spec-v1","router_version":"peixian-router-v1",
    "domain":"gambling","query_mode":"new_query","intent":"funds_analysis",
    "scenario_id":"DEMO-CASE-GAMBLING","target_refs":["林晓舟"],
    "target_mode":"scenario_subject","methods":["funds"],
    "official_skill_ids":["owned-skill-id"],"output_types":["summary","evidence"],
    "direct_parent_run_id":null,"source_data_run_id":null,"missing_fields":[],"context_generation":null
  },
  "response":null
}
```

TaskSpec 和 TaskCandidate 使用闭合 JSON Schema。TaskCandidate 仅保存在加密快照，不作为客户端输入或公开授权结果。ordinary chat 和升级前 Run 的 task_spec 返回 null。response 非空时仅含 code/message。直接父 Run 和原始资料 Run 字段本阶段均为 null，不伪造 PR-6 来源关系。上下文重置前 generation 可为 null；重置后为持久审计边界标识。

## 官方方法与目标支持

自动选择只查当前账号已有副本，核对官方内容散列、发布状态、启用、实际应用内容及依赖。副本显示名不作为身份。不能自动复制模板、安装、启用或替换用户内容。仅有公共模板时返回 official_method_not_owned。

| 错误码 | 含义 |
|---|---|
| official_method_not_owned | 没有可归属当前账号的官方副本 |
| official_method_identity_changed | 明确选择或已有受信 applied 身份对应的副本正文已变化 |
| official_method_disabled | 官方副本未启用 |
| official_method_pending | 所选官方内容/版本未实际生效 |
| official_method_dependency_unavailable | 依赖配置、插件授权、安装、连接或生效状态不满足 |
| task_context_changed / runtime_changed | 受理前后上下文或运行配置发生变化，请重新确认 |

上述方法错误返回 409，受理前拒绝，不发起模型。无法证明某编辑副本的历史官方身份时，不按名称猜测它是什么方法。

当前冻结资料实际以中文人员引用作为 member_ref/group_ref，而非方案中的示例 DEMO-SUBJECT ID。接口如实冻结字段值，不能将示例 ID 映射成未经核实的新对象。

- 所有方法支持场景主对象 scenario_subject。
- 资金方法额外支持 record_filter：仅一个已知且在当前账号、当前会话有效资料来源中出现的对象，按原始 member_ref 完全相等筛选。
- 已知对象来自本会话有效重置边界之后已完成 Run 的代码事实来源；其他会话或账号、自由模型文字不提供对象身份。PR-5 不支持代词消歧、多对象选择或任意姓名检索。
- 其他方法首版只支持主对象。资金双人关系查询、账户名称后缀推断、未支持日期条件均不执行。
- 原始完整响应在既有加密事实状态中核验和保存；传给模型的 items、事实编译输入、证据与图形使用同一筛选函数。原始冻结计划不改写。
- record_filter 不表示服务端按人检索全库。响应保留 source_returned_count，returned_count/total_count 为明确筛选后的数量；附固定快照范围说明。缺少记录不等于没有发生。

## 兼容与后续

新增可选快照字段 task_candidate、task_spec、task_context_snapshot、task_router_version、task_target、task_response；新计划包含 task_target。原插件调用名、Run 状态枚举、证据与分析结果结构不变，不新增数据表。

没有实施 PR-6/7/8/9、Result V2、结构化澄清提交、全新历史来源链和自由说明冲突检查。没有自动推送 GitHub或发布。PR-5 通过独立审阅后再进入 PR-6。
