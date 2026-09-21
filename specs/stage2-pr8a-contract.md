# PR-8A 可信结果接口与升级说明

基线：77d3f05647abee50fc1185a2441c1ae4f686a7d1。范围仅合成资料、双 Agent 后端可信结果；不接入真实数据，不修改现有站点。

## 启用与兼容

schema v9 新增 run_results，仅保存结果密文、摘要及稳定时间，一 Run 一结果。不改写历史迁移脚本、Run 或 v1 结果。
新安装顺序启用 PX_BACKEND_V6、PX_TASK_CONTEXT_V1、PX_TASK_CLARIFICATION_V1、PX_TRUSTED_RESULT_V2。账号级 PX_TRUSTED_RESULT_V2_UIDS 限定新受理 Run；旧 Run 不自动补造。退出灰度不删除历史结果。
旧库升级需完整备份、停写、闭合全部 Run/环境任务及恢复责任、维护状态 frozen，设置 PX_ALLOW_V9_MIGRATION=1。DDL 与迁移回执在一个事务内；结构/脚本指纹异常拒绝启动。旧镜像不得读取 v9。恢复只能到空目标，保持匹配密钥；本阶段合成 SQLite 恢复不是完整线上卷恢复。

## 接口

保留 /api/console/v1，同源 Cookie/CSRF、Python Token 与现有鉴权一致。下述 GET 不产生模型/插件请求；跨账号或会话均404。

- GET /sessions/{sid}/runs/{rid}/result：终态 Result V2；活动状态 pending + data_usage；旧 Run legacy + result:null。
- GET /sessions/{sid}/runs/{rid}/claims：run_id/result_version/status/items；items 只包含 fact/computed/gap。
- GET /sessions/{sid}/runs/{rid}/data-usage：run_id/result_version/data_usage；旧 Run 为 null，不将其推断为没有查询。

HTTP409 result_not_finalized 表示应保留终态核对提示，不自动重发模型；result_integrity_failed/result_digest_conflict 表示不显示可信结果并交运维核对。
完整字段与响应示例以同提交 stage2-pr8a-openapi.json 为准。现有 evidence、presentation、analysis_result@1.0 不改动；前端 V2 接入属于 PR-8B。

## 可信边界

fact 必须属于已核验事实集合且来源、对象、两套快照与冻结资料相符。computed 由代码再次核算记录数/日期/夜间口径，并核对冻结 Rule 与编译回执。gap 来源于代码可识别缺口。模型正文不生成核心 Claim。
原始 records 是来源区，并不代表每条均已批准为核心结论。Claim 保存 source_run_id，历史解释保留原数据 Run 的来源。
保留整数分；同框/同行/同乘/未知分别表达；没有同行记录不等于独行。只处理冻结范围，没有新的资料读取。

## data_usage 判定

依持久 plugin 预留/完成记录与返回内容校验，不依 query_mode。queried=true 表示至少一个模块有效返回，不代表所有资料成功；有预留但不能确认返回则 null，无有效调用则 false。attempted/may_have_sent 表示存在预留，不声称外部服务必然已执行。
状态优先次序：历史零调用投影；权限拒绝；取消；有有效返回但模块/事实表不全为 partial；契约拒绝；未知；在途；全部确认。同 Run 缓存复用另标 reused_current_run 并保留 new_call_count/reuse_count，它不抹去本 Run 之前实际执行的调用。
终态 Result 永久冻结该轮最终状态；活动状态可变化，只由 API 动态投影，不写入最终结果表。前端不能将终态 data_usage 用作实时 Runtime 健康判断。

## 模型说明核对范围

verified 仅表示完整固定 Claim 句式或白名单说明通过规则；未覆盖自由文字为 unverified；数字/来源/关系等未绑定或无依据定性为 conflicted；未生成 not_generated。并不承诺任意语义自动核验。冲突/未核验说明与代码事实必须分区，不能生成事实卡片。不为语言或核对失败自动重发模型。

## 稳定性

generated_at 固定取 Run 终态时间；Claim ID 与结果摘要使用排序 JSON，无当前时钟。终态与 run_results 同事务保存。重复相同投影不改写；不同投影拒绝覆盖。历史解释核对原冻结投影摘要及原 Run 所有权、Agent 和上下文代次，不使用现时夹具或最新规则补算。
