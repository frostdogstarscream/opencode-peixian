# PR-7 对象澄清接口契约

基线 cb8e9cdcd9af997fe0c75d1283f178cf3c410b3e。仅后端与受控执行链；不部署，不增加前端或业务方法。

## 启用与版本

沿用双账号白名单。默认不开启；独立候选设置 PX_BACKEND_V6=1、PX_TASK_CONTEXT_V1=1、PX_TASK_CLARIFICATION_V1=1。已有 v7 升级还需 PX_ALLOW_V8_MIGRATION=1、frozen、无执行责任，并事先完整备份。v8 新增 task_clarifications，保留 v7 Context 及旧 Run。旧镜像不得连接 v8；回退恢复升级前成套备份到空目标，不能降版本号或覆盖新增数据。

TaskSpec 继续 v3，Router 继续 v2；新增 entity-projection-v1、peixian.task-clarification/1.0 与 method-target-v2。旧 v1 筛选计划保持兼容。

## 候选与查询

候选仅来自当前账号、会话、Agent/Profile、Context generation 的可信来源 Run 的结构化字段和固定场景主对象，不从模型说明取对象。按类型及原始标识去重，来源逐项保留，最多20候选，超限给出缺口。

涉赌允许人员/账户候选；盗窃允许人员/车辆。对象存在不代表方法支持：现有资金精确筛选只支持 member_ref 人员，不将账户后缀转成人员。多个人组合仍不支持。车辆仅对盗窃 vehicles 方法开放 group_ref 精确筛选，明确 method-target-v2；Gateway 原始返回和事实计算同时核对。未知名称和范围不退回默认对象。

单一合法对象 resolved；多个合法候选 ambiguous；没有可见对象 missing；方法不支持 unsupported。后三类本地完成，零模型、零插件。资金、车辆选择只筛当前固定快照，不表示全库查询。

## 接口

所有路径均在 /api/console/v1 下，普通用户只可访问本人会话；Cookie 写入沿用 Origin/CSRF，Python 令牌同样校验归属。跨账号/会话返回404。

GET /sessions/{sid}/clarifications/{cid} 返回 schema、version、clarification_id、agent_id、field=target_refs、中文 question、options[{id,label}]、context_generation、context_version、status、updated_at。客户端不获得可提交的权威实体结构。

POST 同路径 /resolve，闭合请求体：
```json
{"option_id":"option-1","context_generation":1,"context_version":5,"client_request_id":"unique-client-id"}
```
成功返回 resolved=true、最新代次/版本、resume_required=true。此动作只更新上下文，不访问模型或插件；随后发送标准 messages 文本“继续”，服务端重做能力、技能和对象契约检查再创建查询 Run。

POST /cancel 只接受 context_generation/context_version/client_request_id，返回 cancelled=true、最新版本、resume_required=false。以上请求标识仅用于确认操作，不是消息执行或任意工具的自动重试保证。

错误：旧代次/重置后409 clarification_expired；旧版本或新任务覆盖409 task_context_changed；不同标识重复处理409 clarification_already_resolved；同键不同内容409 client_request_conflict；未知选项或额外权威字段422。相同请求同内容重放首次结果，无重复状态更新。

普通聊天保留待确认事项，但推进版本，旧页面需重新 GET；待确认时“继续”只提醒确认。新数据任务使旧事项 expired。Reset 同时过期待确认项，清空已确认对象，Agent 不变。Profile 变化不静默复用旧确认。

## 执行与兼容

确认选项和继续意图加密保存。新 Run 冻结实际目标、筛选契约、源记录和平台版本。确认后能力关闭，后续查询拒绝；历史读取仍不重新取数。模型文本不构造候选，客户端不能提交 target_refs/source_data_run_id 等权威字段。

历史 Run、证据与报告不重算。未升级 v8 的 v6/v7 行为保持原样，功能门槛和 schema/镜像标签分别检查。PR-8 自动续查、前端组件和 Claim V1 均未实施。

## 标准消息续接示例

确认响应中的 context_version 用于下一条消息。后续消息仍需保持当前 agent_id；盗窃会话不能省略后误用兼容默认的涉赌助手。

```json
{
  "text":"继续",
  "agent_id":"theft-assistant",
  "model_id":"当前账号已授权模型ID",
  "skill_ids":[],
  "plugin_ids":[],
  "file_ids":[],
  "mode":"standard",
  "context_version":6,
  "client_request_id":"11111111-1111-4111-8111-111111111111"
}
```

数值6仅为格式示例，必须使用当前接口返回值。后端使用已确认原问题和原方法选择重新检查，不接受客户端提交实体或来源。明确“继续解释”仍是历史解释，不因存在已确认对象而隐式取数。
