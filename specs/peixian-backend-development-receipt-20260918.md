# 后端开发回执与测试部署记录

## 1. 交付状态

- **后端接口已实现**：BE-P0-01～08、BE-P1-01～03 对应源码与契约已进入服务器本地提交。
- **测试部署已更新并验证**：现有 `https://36.134.45.38:19460` 已迁移至 schema v6，Control 与两个普通账号的 Agent/Gateway/Relay 已匹配发布。
- **等待前端二次接入**：本轮未修改前端源码，没有把接口测试记作新页面交互验收。

基线：da76198e689adf1b027f3c523b62395ee2a6d471。
源码提交：b31c18b55a37a7c61fd598719c59f5b0d25371a4。
镜像数据库兼容修复：dd8287e3730ee7fea8300af168dff1bd1b87803b。
分支：frontend-alignment。仅本地提交，未推送 GitHub。原有其他工作区修改未纳入本轮提交。

## 2. 接口与存储

新增持久 Run、Agent去重受理记录、有界后台投递/核对、固定证据、可信analysis_result、capabilities、调用审计、模型辅助草稿、重跑与Markdown报告；补充用户资料、部门树及管理、模型元数据和保存前测试。

schema v6 的版本化迁移保持账号身份、密码哈希、资源归属和 Runtime 模式。支持从4/5迁移，校验真实结构与摘要；旧库升级需要冻结和显式迁移开关。请求原文与结果快照加密保存；审计只显示脱敏元数据。当前没有为历史会话补造 Run。

## 3. 测试证据

| 层次 | 实际结果 | 边界 |
|---|---|---|
| Control + Gateway 全量 pytest | 515 passed / 4 skipped | 跳过项要求显式 Bun；不是浏览器联调 |
| Bun 插件补验 | 7 passed，其中包括上述4个跳过项 | 初次挂载二进制权限不满足普通用户执行；改用755测试副本后通过 |
| Agent receipt/activity | 5 passed，20 assertions | 同键去重、冲突及活动终结相关单测 |
| Agent typecheck/build | 通过，二进制版本1.18.30 | 不重新构建前端 |
| 部署相关定向测试 | 30 passed，34 subtests | 配置、备份与兼容检查源码回归 |
| 独立真实容器HTTP | 通过 | Control→Gateway→Agent→Relay→可控模型服务；无付费模型 |
| 持久Run、重复提交、冲突、重跑 | 通过 | 终态GET、固定ID、无浏览器订阅仍完成；重复不创建新Run |
| 草稿 | 通过 | 可控模型生成、结构检查、编辑、保存个人停用技能；不等同真实模型质量 |
| 审计与隔离 | 通过 | 管理员列表/详情/BOM CSV，普通用户禁止管理访问，跨账号Run/步骤/证据/报告404 |
| SSE | 通过 | 实际run.updated通知并GET补查终态；新一轮浏览器断线体验未执行 |
| 迁移 | 通过 | 合成4/5库迁移、重复启动、结构损坏拒绝；现有测试库5→6成功 |
| 现有站点只读冒烟 | 通过 | 4账号保留，A/B ready，各12个能力，A24/B11会话可读；A升级前23，新增会话不覆盖历史 |
| 前端保持 | 通过 | 16个静态文件升级前后SHA256逐项一致 |
| 新一轮真实付费模型/真实工具行为 | 未执行 | 本轮0次；原账本14/40，剩余26，不自动消耗 |
| 390/1366/1920新页面联调 | 未执行 | 前端同事二次接入后验收 |
| 所有故障边界、空命名空间完整恢复 | 未全面执行 | 不能把单测或备份校验当成完整恢复演练 |
| 大规模并发、持续负载 | 未执行 | 不在本轮声明范围 |

确定性测试覆盖SQLite同键并发、冲突、同会话busy、未知投递不重发、取消意图、步骤游标变化、可信事实投影、防伪、组织环与权限。没有声称所有网络故障和外部模型副作用能够自动恢复。

## 4. 升级记录与问题处理

先暂停两个普通账号环境，确认环境任务完成，维护冻结；停止Worker、Control及HTTPS后完成7个持久卷、2个账号环境、发布目录与匹配密钥完整备份。

备份：`/srv/peixian-backend-v6-full-backup-20260918-01`，目录仅服务器私密保存，不打入交付包。
manifest SHA256：81a35abe0c55c1c962ebf0ae687251d6a3574cbeac017419dcb0e6da9c1077ba。
首次仅停Control而未停HTTPS时，备份工具拒绝并未完成备份；上述01目录是完成且校验成功的备份，不能使用之前空目录代替。

离线迁移显示schema6、账号4，随后使用 `platform-manage.py up` 恢复Control管理网络。解除维护，启动Worker，使用新的镜像发布版本更新账号环境。普通apply重试不会增加desired，也不会覆盖不可变旧发布目录；镜像升级作为真实发布变化，由受信维护路径入队新版本，保留执行器阶段和排空检查。

本轮发现并处理：
1. 独立环境直接Compose替换Control跳过管理网络恢复，Worker拒绝继续；使用正式up、确认停止和恢复流程解决，没有绕过启动身份校验。
2. 新Agent自定义构建通道选择opencode-backend-v6.db，历史列表暂时为空；原opencode.db完整保留。最终镜像固定OPENCODE_DISABLE_CHANNEL_DB=1后恢复原历史；临时新库文件也保留，未覆盖或删除用户数据。
3. 镜像应用期间出现runtime_gate_outcome_unknown，执行器通过既有核对责任恢复；没有将丢响应直接标记成功，最终检查实际镜像与ready状态。

## 5. 最终镜像与来源

| 组件 | 镜像ID |
|---|---|
| Control | sha256:a49e4bc2f6ba47f6c54d11e891cf1086840643efef11aca21efe7e3d90cf2ff0 |
| Gateway / Relay | sha256:b4f287a7c7706f5c7d246169af81ac3c46fc23dd204a77daa0d398d81d577e7c |
| Agent | sha256:bc328ad2659b8967a2a6f16e654aa214e0538f8a2018b3e1f3869a6350639737 |

运行Control的41个Python源码文件与工作区逐项SHA256一致。两账号Gateway只读回执查询均确认durable_run_v1，未提交标识返回null，不触发模型。Agent二进制SHA和源码身份记录在 `deploy/peixian/evidence/backend-v6/release-manifest.json`。

## 6. 交付文件与复现

- specs/peixian-backend-contract-design-20260918.md
- specs/peixian-frontend-api-integration-20260918.md（前端主入口）
- specs/peixian-frontend-api-field-reference-20260918.md（逐接口和组件字段附录）
- specs/peixian-backend-v6.openapi.json
- specs/examples/backend-v6-client.py（环境变量提供地址/令牌/模型，无自动写重试）
- deploy/peixian/acceptance/backend-v6-http.py（仅独立合成环境）
- deploy/peixian/evidence/backend-v6/*.json

源码回归在 services/peixian-control 目录执行 `python -m pytest -q tests gateway/tests`；Bun补验显式设置可被运行用户执行的BUN_EXECUTABLE。HTTP脚本需要BACKEND_V6_FIXTURE_ROOT、BACKEND_V6_BASE_URL及部署方私密准备的合成账号/模型/证书文件；不要向现有用户空间批量执行。

## 7. 回退和后续验收

保留完整备份、原镜像及发布目录。v6库禁止用旧v5镜像直连；选择兼容v6整套镜像，或先保留升级新增数据，再将完整备份恢复至空目标。不得仅降PRAGMA user_version或只恢复Control库冒充完整回退。

前端同事依据主文档接入Run恢复、状态、可信Part、草稿和审计。后续重点是前端各状态联调、受控故障恢复补验和少量真实模型效果检查；草稿敏感信息检测不是通用PII识别器，必须人工复核后保存。
