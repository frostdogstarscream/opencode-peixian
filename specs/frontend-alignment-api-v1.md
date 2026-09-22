# 前端交付清单接口接入说明

日期：2026-09-22。版本：frontend-alignment-api-v1。适用候选分支：`codex/frontend-contracts`。

## 1. 发布边界与技术前提

本次仅修改后端、测试和契约文档，不覆盖前端同事源码，不更换现有站点镜像，不迁移线上控制库。接口实现运行于原PR-9C候选源码之上；当前19460站点并不因此已获得这些接口。

执行步骤/正文/来源展示支持现有schema v6及之后版本，不新增表。实体图谱的数据来源要求schema v9可信结果V2已启用且Run已经保存可信结果；历史v1结果仅报告不可投影，绝不读当前最新夹具补充旧Run。正式发布前仍须完成PR-9C保留的升级及灰度门槛。

全部路径相对于同源`/api/console/v1`。浏览器使用HttpOnly会话Cookie；POST除Cookie外必须携带登录返回的`X-CSRF-Token`并满足Origin检查。Python使用可撤销Bearer令牌。普通用户仅访问本人资源，管理角色不自动取得会话图谱访问权。不存在或跨账号资源返回404，管理角色不具有普通用户接口权限时返回403。

本次文档附带的JSON样例由确定性合成测试生成，不是线上账号请求记录，不包含凭据。

## 2. 实际执行过程

### 2.1 消息归属

`GET /sessions/{sid}/messages`保持`items[].info`和`parts`结构。

新增可选字段：

| 位置 | 字段 | 类型/含义 |
|---|---|---|
| info | run_id | string，本条消息所属持久Run |
| info | turn_id | string，本轮用户消息ID |
| info | parentID | string/null，Agent原始父消息ID |
| tool Part | run_id、step_id | string，持久Run及步骤ID |
| tool Part | call_id | string/null，实际调用关联标识 |
| tool Part | execution | 下述公开步骤对象 |
| text Part | origin=verified_result | 该Part由后端可信结果整理生成，不是模型原文 |

关联来源为持久Run的用户消息ID、明确parentID、调度器实际观察到的本轮助手消息ID和最终助手ID；不靠当前查询时的相邻文本猜测。不在历史缺少证据时补造run_id/call_id。前端对无新字段的旧消息可继续使用原来的兼容归组。

同一调用的`step_id`固定，`sequence`随状态或公开元数据更新前进；前端按step_id原位更新。`after`是变更游标，不能作为步骤身份，也不能假定列表追加才有新状态。

### 2.2 步骤对象

`GET /sessions/{sid}/runs/{rid}/events?page=1&page_size=100&after=0`保持分页外壳。

| 字段 | 含义 |
|---|---|
| id / step_id | 同一个持久步骤ID |
| run_id、call_id、message_id、part_id | 执行与消息关联；历史缺失允许null/省略 |
| step_type | skill/plugin/analysis及已有平台步骤类别 |
| name | 公开业务步骤名 |
| capability_id/name/version | 仅实际观察到调用且能映射冻结能力时提供，历史缺少版本为null |
| status | 保留原协议；pending/running/completed/failed/cancelled，平台还可能返回unknown/rejected等，不强行改成完成 |
| started_at/completed_at | ISO8601或null，不推算缺失时间 |
| input_summary/output_summary | 白名单摘要，无可公开详情时明确为空或说明 |
| result | 仅允许展示的标量结果对象，不含原始工具响应 |
| result_truncated | 原输出存在未公开字段；代表公开裁剪，不等于取数完整或失败 |
| record_count/evidence_refs | 原字段保留；不能把未知的默认计数0解释为已查询0条 |
| details.inputs/outputs | 兼容现有步骤详情组件 |

用户选择Skill/插件只是偏好，不会生成“已经执行”步骤。当前Agent可能把已选技能正文直接注入提示词而不调用skill工具；本版不会把这种选择或注入伪造为一次skill工具调用。普通闲聊无Tool时没有能力调用记录。平台内部实际插件取数事件仍是独立步骤；不能与外层整理工具强行合并成同一次调用。

执行时冻结能力名称、版本、展示字段。敏感字段名、路径、地址、命令、已知凭据等不会进入公开摘要；不提供完整原始工具结果。管理员调用审计仍只查看脱敏元数据，不因此获得本接口的私人正文。

## 3. 正文、建议与可读来源

新生成的受信展示结果继续保留`analysis_result@1.0`和既有presentation字段，新增：

- `missing_details[]`: `{id, category, text, source_ids}`。
- `category`: `scope_limit`（固定范围局限）、`source_missing`（相应模块尚未取得）、`verification_pending`（核对未完成）。
- `recommendations[]`: `{id, type, text, gap_refs, source_ids, actionable:false}`。
- `type`: `request_information`或`manual_review`；首版仅给补资料、核对来源、确认支持范围的建议，没有自动执行业务操作。
- `next_steps`: 兼容字符串；无可验证建议保持空。
- presentation的`next_steps_status`: `available/no_verified_suggestion`。
- `public_markdown`: 代码生成的已核对结果、来源依据、局限和建议。

消息读取时把该Markdown作为一个稳定ID的独立text Part附到本轮最终助手消息，ID为`part_summary_{run_id}`。不重写原模型正文、不全局删除历史文本。前端现有Markdown渲染可直接展示；可用`origin`区分后端整理说明与原模型正文，避免把两者标为同一来源。

来源依据保留旧`type/label/content/source_ids`，新增`record_id/occurred_at/synthetic/verification_status`。`label`示例为“资金流水记录 · 2026-09-14 20:14”；ID不会充当标题。时间按北京时间展示；无时区或解析失败显示时间未提供。资金由整数分精确格式化为元，不合并双边流水。

交接清单建议把“演示”加回每条标题，这与产品此前去掉常驻演示提示的决定冲突。本版继续采用此前展示决定：标题不加常驻提示，后台`synthetic`保留为true，导出报告保留数据性质。没有把资料改成真实来源。

已持久化历史结果不原地回填；旧标签继续保留，不能重算或伪称新摘要已核对。新增图节点详情是授权跳转，来源record_id并不是可直接下载原始资料的URL。

## 4. 实体关系图谱P1接口

### 4.1 目录

`GET /sessions/{sid}/runs/{rid}/graphs?page=1&page_size=20`

响应`{items,total,page,page_size}`；每项`id/title/kind/status/data_revision/updated_at`。普通无资料Run返回空列表；旧有资料但无V2可信来源返回unavailable；未结束的V2 Run返回pending。前端只在ready/partial时展开图形。

### 4.2 快照

`GET /sessions/{sid}/runs/{rid}/graphs/{gid}?node_limit=80&edge_limit=160&cursor=...`

采用交接文档的`peixian.entity-graph@1.0`格式，包含：

- graph_id/session_id/run_id/status。
- nodes、edges、analysis始终为数组。
- 节点id/type/label/properties/evidence_refs。
- 边id/source/target/type/label/directed/properties/evidence_refs。
- meta.mode/data_revision/generated_at/total_nodes/total_edges/returned_nodes/returned_edges/max_depth/truncated/next_cursor/limits。

客户端不要解码或修改cursor。游标签名绑定账号、图谱、版本、查询模式、展开基点、深度、关系类型和分页上限；不兼容的游标返回422，新修订返回409。每一页都包含本页所有边的两端节点，允许客户端丢失缓存后独立显示；合并时按ID去重。

本版图节点使用“人员1、车辆1、来源记录1”等脱敏别名，别名在同一修订内稳定，不暴露真实身份字段。原始记录ID保留于受控evidence_refs。图形只来自已批准事实Claim及对应记录、匹配快照，不来自模型Markdown/Mermaid或截图。

已支持来源关系：同框same_frame、明确同行same_trip、明确同乘same_vehicle、车辆记录关联vehicle_record、资金流水归属ledger_record、夜间记录归属observation_record。没有结构化、可核对关系的来源不硬转成边，并保留partial。资金按独立流水节点展示，不构造资金汇聚/连续转账链。

不返回weight，不给置信度或风险分值。节点属性、边属性只允许标量白名单。页面依然需要前端同事将Mock切换为此接口，本次不改前端。

### 4.3 展开

`POST .../graphs/{gid}/expand`

```json
{"node_id":"n_example","depth":1,"relation_types":["same_frame"],"node_limit":80,"edge_limit":160,"cursor":null,"data_revision":"revision-example"}
```

返回GraphPage，meta.mode=delta。含基点和边端点。depth最多2。relation_types为空表示所有本图实际关系；过滤不触发重新取数。禁止多余URL、账户UID、源路径字段。

### 4.4 节点详情

`GET .../graphs/{gid}/nodes/{nid}?data_revision=...`

响应`{schema,version,graph_id,data_revision,node}`，node与图页同形，仅白名单脱敏属性。节点不存在或跨账号返回404。

### 4.5 路径

`POST .../graphs/{gid}/paths`

```json
{"source_id":"n_source","target_id":"n_target","max_hops":4,"data_revision":"revision-example"}
```

最多6跳；返回**一条最短来源路径**，不枚举所有简单路径。`{schema,version,graph_id,data_revision,found,paths,truncated}`。无路径时found=false且paths=[]。每条路径的edge_ids长度为node_ids长度减一，并按顺序对应。路径仅说明记录关系可连接，不表示因果、团伙或犯罪过程。

### 4.6 容量与状态

本版硬上限500节点、1000边；每页2至200节点、1至400边。最低2节点是为了保证至少容纳一条关系的两端，此点比前端原建议增加了明确下限。meta.limits公开上限。截断或来源不完整时truncated=true；无后续游标时给出truncation_reason。不会静默丢弃并假称完整。

图谱是持久可信结果的确定性只读投影，修订包含投影版本和内容摘要。不会创建额外业务任务、访问模型、重查资料或修改Run。GET恢复不依赖浏览器SSE。现有runs/messages变更通知可触发目录重查；本版不承诺单独graphs事件。

## 5. P2有界算法

`POST .../graphs/{gid}/analysis/query`

```json
{"algorithm":"communities","params":{"method":"connected_components"},"data_revision":"revision-example"}
```

或`centrality`搭配`{"method":"degree"}`；params可省略或为空。其他算法/函数名/代码均拒绝。communities只是连通分组；centrality仅返回每节点直接相邻节点数，没有排序、风险预测或人员重要性判断。全图最多500节点/1000边，固定BFS/集合运算，不提供任意复杂算法。算法阶段采用1秒协作式计算预算，超时返回503 GRAPH_QUERY_TIMEOUT；此值不承诺整个HTTP请求的墙钟延迟。返回algorithm、params、scope、generated_at、truncated及analysis[]。算法结果不能被前端提升为事实或犯罪判断。

## 6. 文件与流式约定

新增`GET /files/{fid}`返回既有File对象；无权或不存在404。内部复用本人Gateway列表读取，减少前端传输负担，但不承诺减少Gateway扫描开销。

上传继续`POST /files`，202返回稳定id。queued/parsing为中间态；ready且truncated=false才允许消息引用。partial、no_text、failed/error不能静默按ready发送。只读状态接口不自动重试上传或模型生成。

SSE仍是`event: change`失效通知，消息正文经GET快照获取，进行中可叠加原有临时正文。断线后以持久历史恢复，不能拼接跨断线缓存或自动重发写请求。**本版没有新增可恢复逐token/delta接口。** 两份交接文档将其作为“若要求严格逐字流”的条件性建议，本轮保留已验证快照机制。

## 7. 错误与审计

错误沿用`{message,code,request_id,field_errors}`。新增X-Request-ID响应头与业务错误关联。Graph主要错误：

| HTTP | code | 客户端处理 |
|---|---|---|
|401|既有认证错误|重新登录，不自动重发生成|
|403|既有权限/CSRF错误|检查身份、Origin、CSRF|
|404|graph_not_found/node_not_found或既有归属错误|按不存在处理，不枚举其他账号|
|409|GRAPH_REVISION_CONFLICT|清空旧图并重新获取目录/快照|
|409|GRAPH_NOT_READY|显示等待或不可用，不触发模型重跑|
|422|GRAPH_INVALID_QUERY|修正参数/游标|
|422|GRAPH_LIMIT_EXCEEDED|缩小页大小、深度、跳数|
|422|GRAPH_ALGORITHM_UNSUPPORTED|使用公开算法白名单|
|429/503|既有过载或服务不可用|遵循Retry-After，有界重试读取|

成功图查询审计包含当前用户及session/run/graph/request标识；普通用户已完成认证后被拒绝的图查询记录资源标识摘要与request_id，不写入猜测的原始路径。不记录正文、查询自由文本、工具原始响应或密钥。读图不写业务数据；允许写脱敏操作审计。

当前平台没有逐条历史证据撤销API，也未引入新的跨部门资料ACL。本版沿用本人Run历史读取规则：卸载插件不删除本人历史证据。不要把账号归属验证宣传为已完成逐条来源撤权；未来接入真实来源时需单独定义该规则。失效身份、跨账号、缺失来源、未批准Claim和快照混用已有拒绝/不投影约束。

## 8. 接入顺序与验收

1. 确认正式发布后的OpenAPI版本，不直接在现有旧站点假定接口存在。
2. 使用messages中的显式run_id/turn_id和step_id；旧数据走原兼容路径，绝不以“选择”当“调用”。
3. Markdown直接渲染text Part，可区分origin；保持可信结构化结果与自由文本不同信任等级。
4. 根据当前Run取图目录，空/不可用保持空态；禁止使用上一个Run或Mock替代。
5. 同一修订合并分页和展开；409清空；切换会话、退出、取消组件时停止请求。
6. 仅用户点击才查询路径/算法；所有POST携带CSRF，不自动重发生成消息。

请前端复核：同轮多助手消息、步骤展开稳定、文字选择、普通问候空侧栏、选中未调用能力、取消与unknown、来源12条列表、修订冲突、无路径、跨账号、文件部分解析及SSE恢复。后端自动测试不能代替这轮真实页面联调。
