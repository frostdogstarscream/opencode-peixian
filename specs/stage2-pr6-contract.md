# PR-6 多轮上下文与历史说明契约

基线：679e4e6f7cbe60642c529e0ed840b172e7bd8370。Router 继续 v2，新增 TaskSpec v3、session-context-v1、historical-claim-projection-v1；旧 v1/v2 结果保持只读兼容。未部署、未调用真实模型或资料。

## 启用与迁移

默认不升级数据库。候选部署需显式 PX_BACKEND_V6=1、PX_TASK_CONTEXT_V1=1；旧 v6 升级还需 PX_ALLOW_V7_MIGRATION=1、平台 frozen、无活动 Run/环境任务或未闭合责任，并事先使用 platform-backup.py 完整备份。迁移采用一个 SQLite 事务，保留旧迁移脚本与全部旧 Run 密文。新鲜安装可直接初始化 v7。新功能仍要求原 PX_TASKSPEC_V1_UIDS 和 PX_MULTI_AGENT_V1_UIDS 双账号白名单。

新表只保存账号/会话/助手/Profile Hash、generation/version、最后完成与最后有效数据指针，不保存第二套任务。重开验证结构和迁移指纹；未知或损坏结构拒绝启动。

回退：禁止降低 PRAGMA user_version。旧 max=6 镜像不得连接 v7；使用现有完整备份恢复工具恢复至空命名空间并使用匹配密钥和镜像。测试覆盖真实 SQLite 原库升级及升级前备份恢复到另一空目录，不覆盖升级后新数据。

## 接口

- GET /api/console/v1/sessions/{sid}/task-context：返回 schema、agent_id、agent_profile_sha256、generation、version、last_completed_run_id、last_data_run_id、pending_clarification_id、updated_at。新会话可用 agent_id 查询参数选择已开放助手；已有会话不允许切换。
- DELETE 同路径：需要 Idempotency-Key；原子增加 generation/version 并清空指针。执行中也可重置，不自动重发或取消模型；旧执行仍可查历史，但完成后不恢复旧上下文。重复幂等请求不重复重置。
- GET /sessions/{sid}/runs/{rid}/source：返回 run_kind、direct_parent_run_id、source_data_run_id、projection_version、projection_digest，不返回 Prompt、实现或凭据。
- POST messages：新增可选正整数 context_version；旧值返回 409 task_context_changed。客户端不能提交 TaskSpec、来源 Run、目标或能力白名单。同 client_request_id 同内容仍先返回原受理，不重新解析。

已有本地 Run 的上下文读取不依赖运行容器在线；新会话仍经账号环境校验归属。跨账号/会话来源返回 404。

## 来源与并发

A 数据查询、B 解释 A、C 继续解释：B 的 parent=A/source=A；C 的 parent=B/source=A。last_completed_run_id 仅在完成时推进；last_data_run_id 仅在有可信结构化事实时推进。受理与上下文 CAS 在同一事务中；完成时再核对冻结 generation/version，过期完成不覆盖新上下文。

历史投影只读取已完成的原数据 Run：同账号、会话、Agent、Profile Hash 和当前 generation；核对冻结资料快照与模块响应，投影事实、已核验摘要标识、缺口、规则版本与事件状态。模型文字、报告正文、用户文本不参与投影。投影及 digest 冻结到当前 Run。投影超出预算或来源无效时返回本地 source_evidence_unavailable，不调用模型或资料。

历史说明 allowed_capabilities=[]、allowed_tools=[]，保留模型叙述但禁用取数；若出现违规工具回执则标记失败，不生成可信结果。报告引用冻结历史投影，不能把说明 Run 的模型文字升级为事实。

当前 Profile 升级后，旧会话只能读取历史，新消息需新建会话，不能借重置切换 Agent。普通聊天保留数据来源指针；PR-7 的对象澄清本阶段尚未实施。
