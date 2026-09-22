# 盗窃助手 M1—M4 前后端候选联调说明

## 部署前置

schema v11，匹配Control/Gateway和前端。真实连接配置 PX_THEFT_REAL_CONFIG 默认关闭；账号必须在配置名单内、接入合同和验收范围已确认，插件2.0.0授权安装生效。warning与police连接分别配置；缺少其中一组不阻止另一组。不得尝试不同登录加密方式或随机人员。

任务预算通过 PX_THEFT_TASK_LIMITS 显式提供：max_user_requests（≤40）、max_planning_calls、max_rounds_per_task、max_data_calls、max_steps、max_locations，所有值为正整数。示例仅为隔离测试：40/8/8/10/10/3。规划需 PX_THEFT_PLANNER_UIDS 名单与已生效、内容未修改的两个官方2.0.0方法副本。未满足时查询拒绝，不自动安装，不调用演示替代。

## 统一消息入口

POST /api/console/v1/sessions/{sid}/messages

```json
{"text":"查询所选位置的警情资料，半径500米","agent_id":"theft-assistant","model_id":"authorized-model","client_request_id":"11111111-1111-4111-8111-111111111111","analysis_task_id":"existing-task-id","scope":{"radius_m":500},"source_refs":[{"run_id":"source-run-id","result_digest":"saved-result-digest","record_id":"selected-record-id","snapshot_id":"saved-response-snapshot"}]}
```

analysis_task_id可省略，服务端复用当前会话未重置任务；新会话创建新任务。source_refs完全来自用户明确选择的当前来源，不能默认首条。scope是人工补参，可省略；不得复制来源坐标来替代引用。输入单个人员使用person_identity，仅在加密执行条件内保存，不进入模型。时间start/end使用北京时间YYYY-MM-DD HH:mm:ss。原经纬度使用lon/lat，半径radius_m为米，page为用户明确翻页。

成功仍返回202和run_id/message_id，增加analysis_task_id/planning_call_id。同client_request_id同内容返回原结果；冲突409。规划失败、unknown不自动重发。后台后续Run使用稳定子标识，同一用户请求只计一次，内部规划调用另计。SSE只通知读取；页面继续GET会话Run列表恢复后续步骤，不重放写请求。

模型只能选择已生效官方Skill、已授权能力与用户提供槽位。条件齐全直接执行；缺少条件产生中文澄清Run，不要求填写内部接口名。表单与来源按钮也走此入口。解释不新增查询，未知或失败结果不退回较早成功结果。

## 任务读取

GET /sessions/{sid}/scenarios/{scenario_id} 返回 context_version、scope_version、steps、selected_refs、planning、budget。steps内有来源四元组、规范参数、实际插件/合同版本和父Run。方向不是模式，不需要重建会话。

budget分别为用户请求、规划调用/轮数、已受理数据步骤、实际投递尝试、确认响应。投递尝试不代表供应方一定收到；unknown不能写成成功或空结果。planning仅有脱敏状态/动作/错误码/Run引用，不返回模型原文和敏感槽位。

## 来源复核

POST /sessions/{sid}/runs/{rid}/reviews，继续要求Idempotency-Key。

```json
{"result_digest":"saved-result-digest","status":"needs_information","note":"需要补充此条来源时间说明","claim_ids":[],"record_refs":[{"record_id":"selected-record-id","snapshot_id":"saved-response-snapshot"}]}
```

状态consistent / needs_information / inconsistent。必须选择实际Claim或记录；更正增加supersedes，并保持原目标集合。GET同路径分页读取全部历史。跨账号404。用户复核不会修改原事实或提高Claim可信等级。

## 任务导出

GET /sessions/{sid}/scenarios/{scenario_id}/report?format=html 或 md。返回text/html或text/markdown及安全下载文件名。尚有执行/规划责任返回409；结束但失败的步骤可记录其失败，不补成功结论。报告从同一快照取得结果和复核，保留来源、版本、覆盖局限和数据环境。

## 必须保留的状态

real_provider_disabled、provider_connection_unconfigured、coordinate_contract_unconfirmed：合同/连接未开放。
source_version_changed、analysis_context_changed：刷新来源后重新准入，不能忽略。
planning_unconfirmed：已计入预算，未确认的请求不得自动重发。
planner_skill_unavailable：官方副本未启用、内容被修改或尚未生效。
task_budget_exhausted：停止并保留已有结果。
review_target_required / review_target_changed：需明确条目或更正目标不一致。

## 尚待实际联调

真实认证与范围、坐标合同、夜间/跨小区明细歧义、目标v11部署、模型实际规划选择、两个账号的非空跨步骤来源、页面操作及任务导出。每项分别记录通过/失败/未执行，不以空响应或静态编译替代真实验收。
