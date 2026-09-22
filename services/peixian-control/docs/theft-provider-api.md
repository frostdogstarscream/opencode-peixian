# 盗窃资料接口前端联调说明

前缀 `/api/console/v1`；同源 Cookie + X-CSRF-Token，或本人 Bearer Token。角色边界不变。所有 session/run 资源按当前用户确定归属，跨账号404。六类资料只对具备当前授权且已生效的测试用户开放；真实服务未接入。

## 1. 能力与范围

`GET /theft-provider/capabilities` 返回 items(kind,name,plugin_id,available)、data_environment=synthetic、contract_version。

`POST /sessions/{sid}/provider-query/preview` 请求 `{"kind":"incidents","query":{"start":"2026-09-20 00:00:00","end":"2026-09-20 23:59:59","center":"DEMO-LOCATION-A","radius_m":500,"page":1,"page_size":20}}`。

返回 `plan/confirmation/summary`。plan为不可编辑服务端计划，绑定用户、会话、配置版本、场景清除边界，600秒有效。预览不调用模型/上游。修改任何输入必须重新预览。

kind 支持 incidents、captures、tracks、warnings、warning_detail、warning_logs。tracks/detail/logs 必须明确 subject，两项允许值为 DEMO-PERSON-001/002。incidents 需 address 或 center；captures 必须 center+radius_m 且不能按人员筛选。三个分页接口页码1起，每页最多100；轨迹和固定详情不能翻页。warning_detail/logs 不接收自定义日期，logs 固定来源近7天。日期按北京时间，warnings 仅完整日；时间范围最多31天。

## 2. 持久执行

`POST /sessions/{sid}/messages` 使用已有字段并添加 `agent_id=theft-assistant`、新的 client_request_id、`provider_query={plan,confirmation}`；text 只说明意图，不改变冻结的查询。每轮一种资料/一页。HTTP202只表示受理，通过已有 Run/事件/Result接口读取状态。不得自动重发未知请求。原会话绑定别的助手时新建会话。

签名被改写返回409 provider_confirmation_invalid；超时、配置或清除边界变化返回409 provider_confirmation_expired；未启用403 provider_not_enabled；未生效409 provider_not_applied。字段不合法422，提示需修正条件。本轮不实现供应方登录。

Result V2 保留原结构。task.schema_version=task-spec-v4，methods为一个查询kind。versions含provider_contract/provider_snapshot/plugin_versions/query；records.fields仅返回允许字段，record_id为本轮响应行引用，不冒充供应方永久行号。answer仍为controlled-zh-v1，中文来自回执字段。状态将执行完成与资料覆盖分开。无工具调用不得生成取数成功。

历史解释冻结本人来源，不重新调用。扩大对象、日期或资料类型时应再走预览确认。清除场景后不继承清除前资料。平台不会把自然语言中的未支持对象替换成固定演示对象。

## 3. 人工复核

`GET /sessions/{sid}/runs/{rid}/reviews?page=1&page_size=20` 返回 items/total/page/page_size/unreviewed/result_digest。要求schema v10；读取可返回尚无复核记录，追加仅允许终态Result V2。列表追加排序，不可编辑/删除。

`POST` 同路径，必须 Idempotency-Key，body含 result_digest、status、note，可选claim_ids(本轮Claim最多100)、supersedes(本轮本人未被更正意见ID)。status：consistent来源核对一致、needs_information需要补充、inconsistent发现不一致。note为1–2000字。返回201 Review；同幂等键同内容返回原结果，冲突409；结果摘要不一致409。

追加更正不覆盖旧记录，报告附独立复核段。复核既不改变可信Claim，也不提升模型自由文本为事实。结果、图谱和权限不因复核意见改变。

## 4. 联调检查

确认页面字段与预览一致；提交期间禁止改写；会话切换清理旧来源；受理丢响应只查原Run；结果部分/未知不能显示全部成功；预警和抓拍字段不改名为嫌疑/到访；跨账号、取消、撤权、旧客户端均回归。截图和真实模型结果由验收回执分别记录，接口单测不代表整体验收。
