# PR-7.1 双 Agent 联合审查与修复记录

## 基线和范围

基线 `cb080805cb26d5ebbaa95a7283605737e634fee4`，分支 `codex/stage2-context-integration-review-v1`。先只读审查，再运行反例，最后修复；没有新增业务功能、查询模块或 PR-8。保留旧迁移脚本和前三阶段关账制品。

## 发现与修复

|编号|问题|修复及对应验证|
|---|---|---|
|IR-001|执行前目标链核对不完整|Control 和 Gateway 同时核对任务、独立目标、场景对象及车辆筛选字段；篡改三个位置均拒绝，独立快照目标也不能替换。|
|IR-002|迁移只验证直接前驱|检查全部已记录迁移的 ID、前后版本和源码摘要；保留当前完整结构指纹检查；历史迁移文件不变。|
|IR-003|裸指代可能进入普通模型聊天|“他”“这个人”“这个账户”等缺少方法时本地澄清，不生成模型投递；不自动猜测查询方法。|
|IR-004|旧阶段工作流误触发新 PR|按 PR 来源分支限定阶段工作流；历史验收在固定关账提交运行。|
|IR-005|缺少有历史数据的联合恢复用例|v6 Run→v7 Context→v8 升级后比对完整 Run、账号身份和 Context；恢复 v6/v7 到空目录再比对。|
|IR-006|旧库 source 接口返回内部故障|schema<6 直接返回404；不查询尚不存在的 Run 表。|

修复前 15 个反例：14 failed / 1 passed。失败是预期缺陷复现。修复后第一组 21 项通过；新增联合测试初次因测试列名和合成开通任务未闭合失败，修正夹具后通过。没有修改升级保护来迁就测试。

联合覆盖能力/规则停用后的新查询阻断与历史只读解释、澄清确认后撤销插件授权、车辆范围证据、跨账号/会话/Profile/代次隔离、幂等重放、零模型本地澄清。补充两项反例确认未适配话单此前返回 intent_required，修复为 capability_not_ready；Registry 为 contract_only/disabled 时零查询。未增加话单 Method，已发布插件但 Profile 未声明方法时仍请求必要方法信息，插件存在不等于方法已发布。

## 兼容与操作

数据库最高版本仍为8，部署保持显式启用；没有修改 v4—v8 迁移脚本。旧库 source 返回404；已启用上下文与澄清的接口、枚举和请求格式不变。裸指代本地提示需要的方法，确认对象本身不启动查询，需明确继续。

此候选版本没有部署到19460，没有升级现有账号环境、修改插件授权或前端资源，没有调用真实资料或付费模型。恢复验证使用合成控制库与匹配测试密钥，不等同于完整生产卷恢复或线上验收。

回退需匹配原 schema，不允许旧镜像直接连接较新库。完整站点发布、前端二次接入、真实模型和规模测试需单独验收。

## 验收和可追溯材料

全量结果、实现提交和实际 GitHub CI 回执见 `stage2-pr7-integration-release.json`；逐条发现及测试名称见 `stage2-pr7-integration-findings.json`。SHA256SUMS 覆盖本阶段文档及清单。候选阶段不声明 CI 或全量测试已通过；完成后严格检查器拒绝未关闭发现、源码漂移与无效回执。


## 正式关账结果

- 实现提交：`2d94392c01dda951fd5cd993095eeb53a4e32d9a`。
- 实际 GitHub CI：[35606895495](https://github.com/frostdogstarscream/opencode-peixian/actions/runs/35606895495)，success。
- 确切实现提交的 Control/Gateway 全量 **903 passed**；两项既有 Starlette/httpx 弃用警告。
- CI 部署/发布/容量池检查 **59 passed，10 subtests passed**；Bun 七插件行为 **14 passed**。
- 固定历史提交：PR-5 63、PR-5.5 62、PR-5.6 17、PR-6 19、PR-7 19 项均通过，历史关账检查通过。
- 本地先执行的全量901项及最后路由补丁的88项定向结果保留；最终通过声明以903项的确切提交CI为依据。
- 当前导出 OpenAPI 与 PR-7 JSON 完全相同，无前端接口重接要求。
- 六项发现全部关闭，无未关闭 P0/P1；源代码和证据提交分离，严格检查器禁止关账后核心源码漂移。

### 统一场景对应测试

|场景|验证入口与边界|
|---|---|
|涉赌连续历史解释|`test_abc_history_source_is_a_and_no_tool_dispatch`；来源保持原数据Run，不使用模型说明替代事实。|
|盗窃车辆澄清后查询|`test_vehicle_confirm_then_query_exact_selected_vehicle`、`test_selected_vehicle_real_gateway_plugin_and_http`；实际Gateway、Bun和合成HTTP链路，仅选定车辆进入证据。|
|建设中话单|`test_unadapted_calls_is_explicitly_unavailable`；返回capability_not_ready，零插件，无新增Method。|
|Agent与账号隔离|`test_source_fail_closed`、`test_cross_account_and_session_tickets_hidden`；Profile/代次/来源/账号不一致即拒绝。|
|Context重置|`test_projection_only_current_trusted_fields_and_reset`、`test_terminal_or_replaced_ticket_not_resolvable`；旧票据过期，旧来源不再自动继承。|
|能力状态变化|`test_resumed_query_rechecks_capability`、`test_revoked_resolved_vehicle_not_queried`、`test_disabled_registry_preserves_history_but_blocks_new`。|
|升级与恢复|`test_existing_run_context_upgrade_restore`；保留真实加密Run和Context，合成库恢复到空目标，非生产全量恢复。|

以上包含受控HTTP与真实插件代码执行；没有生产Agent容器发布、真实模型问答、UI接入或并发验收，不能替代对应上线门槛。PR-8未开始。
