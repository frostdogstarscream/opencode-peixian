# 第五轮：提问范围、资料状态与车辆图谱联调接口

日期：2026-09-22。源码：a7f639ce2e3e9e219a517a3b1f1efffa20d10a8f。数据库仍为 schema v9。

## 1. 兼容边界

沿用 /api/console/v1、三角色、Cookie/CSRF 与账号归属鉴权。现有 Run.status、请求标识及幂等规则不变。消息生成没有新增自动重试能力。旧客户端可以忽略新增 outcome。

本轮不改变 CSS、资料服务接口、插件授权、Agent/Gateway/Relay 镜像、Skill 模板及用户数据。没有扩展真实对象或时间筛选能力。

## 2. Run.outcome

以下接口的 Run 响应增加可选 outcome：

- GET /sessions/{sid}/runs：列表中的各 Run。
- GET /sessions/{sid}/runs/{run_id}：单个执行。
- POST /sessions/{sid}/runs/{run_id}/abort：兼容中止响应。

以同目录 openapi.json 为精确机器契约。字段如下：

| 字段 | 类型 | 含义 |
|---|---|---|
| version | string | 当前 run-outcome-v1 |
| status | string | 面向用户的资料结果状态，见下表 |
| label | string | 中文标题 |
| message | string | 中文说明 |
| next_steps | string[] | 下一步建议，只显示文字，不自动发送请求 |
| execution_status | string | 原 Run.status 原样保留 |
| data_status | string | 已持久化/受控取数状态，不从模型文字推断 |
| queried | boolean/null | 是否有确认的取数；未知保留 null |

| outcome.status | 展示含义 |
|---|---|
| processing | 尚在处理 |
| unconfirmed | 执行或取数结果待确认，不重复发起 |
| cancelled | 已确认停止，不能据此推断外部操作撤销 |
| failed | 执行失败，不等于没有资料 |
| needs_input | 仅完成澄清，尚未查询 |
| historical | 使用原执行资料，没有重新取数 |
| partial | 部分资料缺失、不可采用或记录未逐条核对 |
| data_ready | 资料已取得；不等于模型自由说明全部核验通过 |
| no_query | 执行结束但没有确认的新资料 |

示例（无支持的对象/范围）：

```json
{
  "status": "completed",
  "outcome": {
    "version": "run-outcome-v1",
    "status": "needs_input",
    "label": "需要补充信息 · 尚未查询",
    "message": "本次仅完成问题范围确认，没有发起资料查询。",
    "next_steps": ["请按本条回复补充对象或范围；若沿用已有对象，可说‘整理当前对象的车辆记录’。"],
    "execution_status": "completed",
    "data_status": "not_started",
    "queried": false
  }
}
```

此示例对应本轮范围澄清响应。前端以 label/message/next_steps 显示，不能将 completed 直接翻译为“资料查询成功”。现有结果区域原样保留，本轮在输入区上方添加复用原样式的“本轮资料结果”。

## 3. 复杂提问与场景

服务端只规范化有限、明确的当前用户表达：礼貌前缀、当前场景表述、已知输出方式、完整的“附件仅为页面测试，不能作为资料来源”等附加说明。原问题保持在冻结快照中，不因规范化改变重放内容校验。

新增冻结元数据 request_language_version=request-language-v1。场景续接沿用现有 TaskSpec/上下文；同会话追问“继续解释刚才的收支方向，不重新查询资料”使用原 Run 的可信结果，new_call_count=0。

任意人物、身份证、额外时间范围、不明方法或冲突信息不被当成无害修饰语删除。无法确认的对象仍澄清，不静默改成演示对象。附件正文、模型回答及工具内容不能决定本轮路由。

## 4. 车辆事实至图谱

新 Run 冻结 record_check_version=vehicle-record-check-v1。平台代码在事实表持久化边界检查：冻结场景与数据快照、受控插件回执、实际车辆来源、对象与观察窗口、固定字段生成的事实句、统计数量及规则版本。摘要模型没有选择某条记录，也不再成为已核对车辆事实进入图谱的唯一阻塞点。

校验记录保存在现有加密 facts_state.record_checked 中，步骤出现 facts.vehicle-check（核对车辆记录与来源）。可信结果生成前重新计算并比对证明。伪造句子、来源、时间、快照或回执不获得信任。

既有 /result、/evidence、/graphs 和 /report 路径不变。图谱与正文说明独立核验；不将无依据的地点距离、同乘、犯罪判断加入图谱。旧 Run 无本轮版本标识时保持旧行为，不回填、不重新取数。

## 5. 接入与测试步骤

1. 提交后保存 run_id；使用原 Run 读取状态，不自动重发写请求。
2. 分别显示原执行状态与 outcome。模型文字不决定 data_ready。
3. outcome=historical 时显示来源执行及时间范围，不显示“本轮已重新查询”。
4. needs_input 时保留场景与输入，让用户补充或明确沿用当前对象。
5. 图谱按现有账号/会话/Run 接口加载；切换会话清理旧状态。
6. 当前页面刷新回到首页，重新打开历史会话后恢复相同结果；本轮未新增自动恢复选中会话。
7. 跨账号访问 Run、任务、结果、图谱、报告返回 404。

原接口的认证与 CSRF 规则未调整。新增字段与当前部署 OpenAPI SHA256 记录在 verification.json 与 SHA256SUMS。
