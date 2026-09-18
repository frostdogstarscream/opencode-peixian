# 后端接口设计与差异说明

日期：2026-09-18。基线：`da76198e689adf1b027f3c523b62395ee2a6d471`；工作区：`/root/PeiXianDB/frontend-alignment`。本轮不修改前端源码、不覆盖原交接清单。源码、独立测试部署、现有测试站点分别验收。

## 1. 清单对应

| 编号 | 现状与本轮实现 | 与前端原清单的差异 |
|---|---|---|
| BE-P0-01 | 扩展消息接口，持久 Run、固定用户消息 ID、加密请求快照、独立投递器、Agent 受理回执 | 返回 202；client_request_id 为 UUID；未知投递不重发；plugin_ids 是偏好 |
| BE-P0-02 | 新增 Run 列表、详情、增量步骤、定向取消、固定证据 | 七状态；cancelling/reconciling 不能显示已取消或失败；步骤不是推理链 |
| BE-P0-03 | 根据可信事实生成 analysis_result Part，保存到 Run | schema=peixian.analysis-result、version=1.0；模型同名结构不可信；旧会话不补造 Run |
| BE-P0-04 | 新增 capabilities，提交与目录共用授权、生效、依赖校验 | 模板需复制；无部门 Skill 发布状态机；插件偏好不等于白名单 |
| BE-P0-05 | 模型字段、单默认模型、保存前和保存后连接测试 | supports_tools 为管理员声明；GET models 成功不能证明模型推理或工具调用 |
| BE-P0-06 | 用户资料、summary、部门树与组织 CRUD | 三角色、四测试账号；管理员不修改部门或普通用户部门归属 |
| BE-P0-07 | 独立 Invocation 元数据审计 | 管理员只能读取普通用户的脱敏元数据，不获取问题或工具正文 |
| BE-P0-08 | 保留 change SSE，增加 run.updated/runs | 通知不含完整结果；通过 GET 恢复，不重放消息 POST |
| BE-P1-01 | 模型辅助草稿、编辑、结构验证、显式试运行、保存 | 保存个人技能且默认停用；生成时禁用工具；会话来源只提供方法元数据 |
| BE-P1-02 | 显式重跑、Markdown 报告 | 新 UUID 和新 Run，保留 parent_run_id；报告保留数据性质与失败状态 |
| BE-P1-03 | 审计详情与 UTF-8 BOM CSV | 最多10000条，公式防护；与列表相同过滤及角色边界 |

## 2. 存储与执行设计

schema v6 采用附加表，不改变原账号 ID、密码、归属和 Runtime 模式。新增 departments、user_profiles、model_profiles、skill_profiles、business_runs、run_deliveries、run_events、invocations、skill_drafts、draft_trials。迁移编号为 control.backend-contract.v6.1；校验迁移文件摘要、实际结构指纹和历史迁移身份。

升级旧库需要 PX_BACKEND_V6=1、PX_ALLOW_V6_MIGRATION=1、维护冻结及已清理的执行责任。镜像 schema.max 必须支持6。数据库版本与部署配置版本、Worker协议版本是独立边界，不能只改版本数字。Worker协议仍为2；Agent/Gateway新增 durable_run_v1 能力。

受理短事务创建 Run、Invocation、用户消息 ID、密文快照和投递记录。投递前持久标记 sending；结果不明确只查询稳定执行标识，不盲目重新调用。Agent 将接受记录写入独立持久 SQLite 后才启动生成。Agent 重启后未闭合旧记录返回 unknown，Control 保持 reconciling。此设计优先避免重复外部调用，不承诺未知任务自动恢复成功。

完成依据是对应用户消息之后的实际 Agent 消息及执行受理状态，不依赖浏览器在线。取消意图持久保存；已发送 abort 不等于外部系统操作撤销。一次会话只允许一个未结束 Run；没有业务队列。

步骤按稳定 ID 保存，状态变化取得新 sequence；增量接口是可合并的步骤视图，不是每次状态变化的完整不可变日志。冻结请求包含模型、插件版本与工具映射、Skill 引用及 applied 配置身份；当前权限收紧仍限制后续读取和执行。

## 3. 可信展示

会话 evidence/presentation 保持兼容。新增按 Run 固定的证据与服务端 analysis_result。只有完成且通过现有事实校验的插件结果能够提供事实卡片；模型自由文本、模型编造编号或 analysis_result 都不作为来源。对象画像与建议没有可靠来源时为空。

Invocation.record_count 当前表示可信证据卡片条数，不是原始资料总条数。计数为0不能推导“没有资料”。source_metadata 保存合成性质、场景/资料两套版本；Markdown 导出保留必要性质说明。

## 4. 已知限制

草稿敏感信息检测为保守规则，不能保证识别所有自然语言姓名或事实；用户必须复核后明确保存。会话生成仅发送方法元数据，不发送原始会话正文。尚无草稿自动审核发布、部门 Skill 发布、Run 人工核对控制台及持久记录自动归档清理。

运行环境恢复仍遵循原有安全屏障。独立部署直接使用 Compose 替换 Control 时跳过了动态管理网络恢复，进入保护状态；使用正式平台 up 命令及账号生命周期恢复后通过。Agent 构建通道兼容问题已通过固定读取原数据库解决。任意故障边界和空目标完整恢复未完成新一轮穷举验收，详见开发回执。
