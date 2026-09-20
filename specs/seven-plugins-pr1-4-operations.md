# 七插件执行闭环：PR-1 至 PR-4 操作与接口说明

## 范围
依据《沛县公安涉赌Agent架构修改建议 V1.1》，仅实施第一阶段。保留 schema v6、三角色、Durable Run 和现有前端。自然语言 TaskSpec、跨 Run 说明模式和正式业务权限不在本次完成声明内。

## 唯一执行链
受理 Run → 服务端冻结固定方法计划 → Agent 托管工具 → Gateway 校验真实助手消息的 parentID → Control 按账号/Run/revision 准入 → 真实独立插件 → Relay 固定模块策略 → HTTP 合成服务 → 加密 Run 状态 → 确定性事实 → 精确摘要核对 → 已存证据/卡片/事件图/报告。
`platform-facts/coordinator.mjs` 为早期候选和契约样例；生产协调状态使用 `control/facts_runtime.py`，不并行运行第二套 Run。纯 JS engine 由 Gateway 受控子进程调用。

## 契约
公共消息、Run、evidence、报告接口和 schema v6 保持兼容。`plugin_ids` 继续表示偏好，不作为严格白名单。服务端在加密请求快照新增 facts_plan/execution_plan/allowed_capabilities/allowed_tools/facts_state；客户端不能赋值。
内部 POST `/internal/facts/execute` 仅接受专属 facts 凭据和 session_id/message_id/tool/args，校验 Agent 助手消息后取 parentID 绑定已有 Run。该凭据不能访问其他 Gateway 接口。Agent 不获得七插件的 Relay 连接绑定。
内部 POST `/internal/runtime/facts` 仅接收账号运行凭据；操作为 begin/authorize/reserve/complete/read/table/check/finish。请求体受限，不提供 URL、文件路径或命令参数。
已完成模块在同一 Run 复用。pending 在 Control 重启恢复或终止核对后成为 unknown，不自动重发。已明确取得但随后撤权的响应仅加密保留为 rejected，不进入可用事实。取消不代表远端操作撤销。
事前检查当前账号、Run、revision、授权、已安装且已发布版本、applied 版本和固定方法；出口再次检查方法、路径及完整 JSON 外壳。运行后的工具一致性检查仅为审计兜底。

## Skill
四个专项官方 V3：夜间活动整理、同行与共现核对、资金往来整理、已有关系核对。另有两个场景总流程。稳定方法 ID、版本、依赖、内容 SHA256 和 draft/published/disabled 状态由匹配发布清单维护；只有 published 官方内容可作为官方方法执行。个人停用另由 enabled 控制，不等同于公共审批系统。
模板复制自动带入插件依赖；服务端根据内容哈希识别官方方法，不根据可编辑显示名授予权限。个人修改副本不自动覆盖，不会因包含“方法标识”就获得官方身份。
当前记录服务仍是固定合成范围。单项方法由明确所选专项 Skill 限定；完整场景计划允许固定方法的有限组合。自动自然语言路由准确率属于后续 PR-5，不能宣称本次已完成。

## 发布及迁移
发布前记录当前镜像 ID、前端静态资源 SHA256、源码 SHA、插件 ZIP SHA、Skill SHA、资料快照，并备份控制库、制品、Worker 状态、账号卷、配置和匹配密钥。私密备份不得放入 Git。
使用匹配 Control/Gateway 与 Worker 文件；Agent 二进制不变，托管插件加载器随账号配置发布。
在 Control 容器内运行 `python -m control.seven_migration publish --packages <只读发布包目录>`，该操作只新增不可变插件、七条独立受限连接和六个官方模板，不改变用户配置。
逐账号运行 `python -m control.seven_migration migrate --uid <账号ID> --receipt <私密回执路径>`。要求无活跃 Run 和环境任务、当前配置一致；在同一事务移除旧安装授权、加入七项安装授权、更新未编辑官方副本与依赖并排队一个配置版本。保留个人副本和历史记录。
先 A 生效与验收，再 B。确认两账号 applied 不含旧插件后运行 `python -m control.seven_migration archive`，旧发布记录保留但不可安装，未被其他插件绑定的旧连接停用。

## 回退
`rollback --uid <账号ID> --receipt <私密回执路径>` 仅恢复回执覆盖的配置域，不恢复整个数据库、不删除新 Run/证据/文件。若用户已编辑相关配置，拒绝自动覆盖，需人工合并。需先恢复匹配旧插件发布状态与旧连接，再排队该账号上一整套配置；不能混合启用新旧链。
发布回退还需恢复匹配的 Control/Gateway 镜像及 Worker 文件。不要用仅替换 Control 的方式回退工具协议。数据库保持 v6，历史新链结果可由本次兼容代码读取。

## 历史及验收
持久 Run 证据按本人资源归属读取，不依赖当前安装旧插件，不重新查询。无持久 Run 的早期聊天不凭空补造执行记录；应保留原始消息与版本，资料图缺少受信字段时明确不展示。
测试区分真实 HTTP 插件契约、合成 Control/Gateway 协议（Agent 消息身份测试替身）、真实账号模型调用。只通过前两项不能声称模型验收通过。模型每轮上限40次，本轮首批至多8次，失败和未知计数，不自动重发。
最终部署状态和实际验收结果以同目录独立验收回执为准。
