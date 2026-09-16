# Schema v4 与运行环境协议 2

本文说明第二轮单宿主编排实现的持久化边界与内部契约。规范来源是 `control/migrations_v4.py`、`control/orchestration.py`、`control/store.py`、`control/worker_api.py`、`control/runtime_security.py` 和 `shared/orchestration_config.py`。当前验收范围为本机初步测试及独立合成数据；不包含服务器部署、并发或持续负载验收，不涉及既有本机 A/B 环境。

## 1. 版本与迁移身份

| 对象 | 当前版本或身份 | 校验位置 |
| --- | --- | --- |
| Control SQLite schema | `PRAGMA user_version = 4` | `Store.initialize`、`migrations_v4.validate` |
| 平台配置文件 | config version `3` | 部署侧配置读取与验证 |
| Worker / Gateway / Relay 内部协议 | `protocol_version = 2` | 各内部接口及部署 Worker |
| v4 migration ID | `control.runtime-orchestration.v4.1` | `schema_migrations` |
| 迁移脚本指纹 | 迁移脚本实际文件字节的 SHA-256 | `SCRIPT_DIGEST` |
| 数据库结构指纹 | 排序后的非 SQLite 内置 `sqlite_master` 对象规范 JSON 的 SHA-256 | `structure_digest` |

版本号、迁移身份、脚本摘要与实际结构必须同时符合。仅把 `user_version` 改成 4 不构成迁移。已有 v4 库在执行建表兼容逻辑前先验证，不能用 `CREATE IF NOT EXISTS` 隐藏缺失对象。已经用于迁移的脚本必须保持字节身份，后续结构变更应使用新的迁移身份和明确迁移路径。

空数据库可以直接初始化完整 v4，维护状态为 `normal`。已有 v3 数据库必须在获准的停机迁移窗口设置 `PX_ALLOW_V4_MIGRATION=1`；升级后维护状态为 `frozen`。较早的受支持版本先经过已有升级路径，再执行完整 v4 迁移。未知较新版本、重复运行任务、孤儿记录、未知旧状态、错误摘要或不完整结构均拒绝启动。

## 2. 持久化对象与关键约束

| 对象 | 关键字段与用途 |
| --- | --- |
| `jobs` 增量字段 | `not_before`、`phase`、`defer_count`、`drain_started_at`、`observation_deadline`、`reason`、`cancel_requested`、`recovery_required`、`previous_status`、`enqueue_seq` |
| `runtimes` 增量字段 | `state_version`、`gate_epoch`、`drain_job_id`、`gate_policy`、`gateway_boot_id`、`relay_boot_id`、`recovery_required`、`stop_reason`、`applied_spec_ciphertext`、`applied_spec_digest` |
| 运行环境安全字段 | `authorization_version`、`security_blocked`、`security_intent_id`、`cancel_requested_at`、`security_confirmed_at`、`cancellation_confirmed`、`drain_intent_id` |
| `job_attempts` | 主键 `(job_id, attempt)`；冻结 `revision`、`authorization_version`、加密 spec 与 digest；保存 `lease_hash`、阶段、`recovery_of_attempt`、最终 `outcome` 与摘要 |
| `worker_operation_receipts` | 主键 `(job_id, attempt, operation_id)`；请求摘要、历史 lease 摘要、不可变响应、创建与过期时间 |
| `request_idempotency` | 主键 `(uid, action, request_key)`；HMAC 请求摘要、资源引用、加密响应、`created`、`expires` |
| `runtime_observations` | `observation_id` 主键；绑定 runtime、job/attempt、state version、宿主 boot、Gateway boot、gate epoch；三组件、宿主 mutation、活动、版本与摘要证据 |
| `capacity_release_receipts` | `operation_id` 主键；释放请求摘要、结果与运行环境，防止重复释放 |
| `platform_state` | 固定 `id = 1`；维护状态、状态版本、容量健康性、冻结原因、周期核对游标、全局入队序号 |
| `schema_migrations` | 迁移身份主键；前后版本、脚本指纹、实际结构指纹、创建时间 |

唯一部分索引保证每个账号至多一个 `running` job。入队触发器在同一事务分配全局递增、非零且唯一的 `enqueue_seq`。普通任务保持该顺序，defer 不更换序号；未到 `not_before` 的任务不阻挡其他账号。安全 pause 最优先，其次其他 pause，之后是普通任务的入队顺序。

加密 spec 中独立保存 `gateway_key`、`agent_password`、`runtime_key`、`relay_management_key`。这些内容仅用于受保护的内部运行配置；公共账号接口、操作回执、审计与文档不得返回原始 spec 或凭据。`runtime_key` 用于 Gateway 向 Control 请求 permit，Relay 管理密钥用于 Gateway 与 Relay 的私有管理通信。

## 3. 短事务、desired 与冻结快照

`Store.tx()` 使用短 SQLite 写事务；`Store.read(snapshot=True)` 提供一致读取。`Store.atomic_request()` 是外层事务入口，同一线程内部 Store 的 `tx/read` 复用该连接，用于把请求幂等记录与业务变更原子提交。外层事务不得包含网络调用、宿主操作、等待或密码哈希。

`queue(uid, action='apply', reason='normal', bump_desired=True)` 与 `queue_in_transaction(db, ...)` 表示业务期望发生变化；普通手动 apply 应传 `bump_desired=False`。`ensure_apply_job(db, uid)` 仅在需要时合并或补排，不增加 desired，也不启动未占位的环境。

claim 在同一事务内读取配置、授权与 desired，并把完整 spec 加密冻结到 attempt。之后对配置的编辑只能影响后续 attempt。进入 `closing/applying/reconciling` 后丢失租约，恢复 attempt 必须使用原 attempt 的 revision、授权版本及 spec，不能用当前 desired 重建原配置。

已就绪环境意外重启而没有未完成 job 时，`ensure_recovery_job(db, uid)` 为已保存的实际 applied 快照补 `runtime_reconcile` 责任。普通 queued apply 等待它先完成核对，随后才处理最新 desired。没有已验证历史快照的遗留状态不编造恢复快照；明确停止或超管修复仍是必要路径。

## 4. Worker 接口与操作回执

内部写入接口必须同时携带 `X-Worker-Key` 与 `X-Peixian-Protocol: 2`。旧 Worker 的 claim、阶段变更、完成、迁移写入与回退写入都会被拒绝。`busy` 和包下载是保留旧认证的只读接口。

| 接口 | 主要请求和响应 |
| --- | --- |
| `POST /internal/worker/claim` | 返回 `{protocol_version: 2, job, spec}` 或 `job: null`；job 包含 `attempt`、lease、revision、spec digest、当前 gate/state/owner 与恢复来源 |
| `POST .../jobs/{jid}/heartbeat` | 请求 `lease, attempt`；返回租约到期时间 |
| `POST .../jobs/{jid}/phase` | 请求 `lease, attempt, operation_id, expected_phase, phase`，需要证据时追加 `observation_id` |
| `POST .../jobs/{jid}/boot` | 请求 `lease, attempt, operation_id, runtime_id, gateway_boot_id, relay_boot_id`；仅 applying/reconciling 登记新 boot，返回新的关闭命令身份 |
| `POST .../jobs/{jid}/complete` | 互斥的成功、失败或 defer 结果，均包含 `lease, attempt, operation_id` |
| `GET .../jobs/{jid}` | 返回当前公开 job/attempt；历史回执查询同时指定 `attempt` 与 `operation_id` |
| `POST /internal/worker/observations` | 提交完整运行证据，返回 observation ID、状态版本、过期时间及分类 |
| `GET/POST /internal/worker/reconcile` | 有界轮转候选查询与宿主只读核对记录 |
| `GET/POST /internal/worker/maintenance` | 查询或按 `expected_state_version` 条件变更维护状态 |

阶段和完成操作的幂等身份为 `(job_id, attempt, operation_id)`，同身份换内容返回冲突。回执在提交事务中保存，重复请求返回原始回执，不重复计数、释放、延后或增加 desired。历史 lease 只能用于证明该历史操作的身份，不能恢复当前执行权。

回执包含 `job_status_after_commit`、`phase_after_commit`、`state_version`、`gate_epoch`、`authorization_version`、`gate_policy_after_commit`、`gate_owner` 和 `gate_action`。历史 applying 回执不能直接授权新的宿主操作；Worker 在执行前还须验证当前 attempt、租约与 gate 状态。完成响应丢失后查询历史回执，不能再次执行宿主 mutation 来猜测结果。

成功完成要求 `ok: true, observation_id`。普通失败使用 `ok: false` 和不含敏感信息的错误码；rollback 还必须有原 applied revision 与 spec digest 的运行证据。单独 `cleanup_confirmed: true` 或 `rolled_back: true` 不构成释放或回滚证据。

busy defer 使用 `deferred: true, defer_reason: 'runtime_busy', observation_id`，不能同时带成功或失败字段。仅在 draining、入口已关、活动仍存在且宿主 mutation 为 idle 时接受。

## 5. 阶段、门控与新 boot

普通路径为 `claimed → draining → closing → applying → finished`；恢复路径为 `reconciling → closing → applying`，也可在 reconciling 直接提交已核实的实际结果。

1. draining 先关闭新入口，允许原有请求继续使用 Relay 出口。此阶段不执行宿主更新。
2. busy 可以 defer；已确认 idle 才能进入 closing。closing 返回递增 epoch 的 `close` 意图，Worker 必须关闭 Gateway 入口和 Relay 出口。
3. applying 必须引用至多 3 秒前的完整当前观测，确认入口、出口均关闭，活动为 0，宿主 mutation 为 idle。收到 applying 确认后，Worker 才能修改容器、配置或挂载。
4. 新容器启动时保持关闭。新 Gateway/Relay boot 经 permit 或 boot 接口登记后使用新 epoch/state/owner 关闭并重新观测，不能把旧 boot 的回执套在新 boot 上。
5. complete 仅写入 `reopen_check`；Control 安全协调器验证当前许可后打开门控，再条件写入 `gate_policy='open'`。Worker 不自行宣布开放。

门控命令绑定 runtime、boot、gate epoch、state version、owner 与 operation ID。owner 使用 `job:{jid}:{attempt}`、`security:{intent_id}`、`drain:{intent_id}` 或 `runtime:{runtime_id}`。已登记 Gateway boot 与 running 观测中的 boot 必须一致；全部已停时允许 `absent`。

## 6. 观测、容量与恢复责任

attempt 观测覆盖 `agent/gateway/relay` 三组件及本机 mutation 状态，并携带 `complete`、`accepting`、`egress_closed`、`activity_count`、`applied_revision`、`spec_digest`、`evidence_ref`。未知活动用 `null`，不能伪装为 0。提交时间只能落在 Control 当前时间前后 5 秒内；Control 决定 60 秒有效期。

只接受当前 runtime/state/epoch/attempt 且未过期的最新观测。`running` 表示三组件全部 running、证据完整且 mutation idle；`stopped` 表示三组件全部 stopped 且 mutation idle；其余分类为 unknown。最终成功还必须有当前冻结 revision/digest 和两端关闭、活动为 0 的证据。

所有释放都通过 `release_capacity_and_promote` / `Orchestration.release` 的单一事务入口：条件匹配 state version，使用最新完整全停证据，不存在其他运行或启动责任，并保存释放回执。unknown、部分停止、超时、Worker 退出或孤立布尔值都不能释放名额。当前 v4 不包含等待容量队列自动晋升，返回 `promotion_enabled: false`。

周期核对只做记录与保护，不自动打开或停止容器。发现账外运行先补 reserved 并冻结，发现 unknown 或孤儿资源保持容量受限。只有无未完成 job/drain/recovery 责任的已停环境才可按统一入口释放。正常调度的恢复还需所有已知环境都有同宿主的新鲜完整证据；孤儿资源冻结不能靠一次普通报告清除。

一次恢复仍无法核实实际状态时，任务停在 `failed + recovery_required` 保留责任，等待超管修复，不循环盲目修改宿主。显式 pause 可以在完成全停核对后退休旧责任。

## 7. 安全撤权与普通长排空

撤权、停用、受限连接或资源禁用在原业务事务中增加授权版本、生成独立安全意图、关闭许可并取消旧运行 job。安全许可与取消通道不依赖 Docker Worker 的任务等待。旧授权 attempt 不得清除当前安全阻断。

在 claimed/draining 尚未修改宿主时取消，可关闭旧 attempt 并补最新 apply。旧 applying/recovery 已被安全意图取代且无法确认原结果时，优先排 safety pause，原责任一直保留到完整全停证据。全停后，仍 active、仅安全授权变化且已有验证过的 applied 快照的账号可以自动排最新授权 resume；新 attempt 成功应用当前授权版本后才清除阻断并交由 Control 重开。停用账号、没有可验证历史快照或修复结果仍未知的账号保持受限；启用停用账号使用明确的恢复流程。

普通 apply 首次排空的前 300 秒内，busy defer 可暂时进入 `reopen_check`，每次延后 15 秒；超过 300 秒持续 draining。首次 drain 的起点不会被重试重置。900 秒观测期限到达后停止自动领取，超管可以继续等待或取消在途后更新。继续等待只延长观测期限；取消使用独立 drain intent，与安全撤权意图分开，后台确认取消后原 apply 再核对。

## 8. 默认配置与回执保留

统一配置源为 `shared/orchestration_config.py`，环境变量命名为 `PX_R2_{KEY.upper()}`，部署 config v3 负责分发相同值。非法类型、越界值及不一致的时间组合拒绝启动。

| 配置 | 默认值 |
| --- | --- |
| Worker lease / heartbeat / heartbeat timeout | 90 秒 / 20 秒 / 5 秒 |
| busy defer / gate probe | 15 秒 / 2 秒 |
| 周期核对 / 每批数量 | 30 秒 / 4 个 |
| 观测保留有效期 / applying gate 证据最大年龄 | 60 秒 / 3 秒 |
| 普通 apply 可临时重开时限 / 排空提醒期限 | 300 秒 / 900 秒 |
| permit TTL / renew / watchdog | 4 秒 / 1 秒 / 100 毫秒 |
| 安全请求时限 / 连接上限 / 取消观察时间 | 1 秒 / 4 / 10 秒 |
| Worker 完成回执最低保留 | 604800 秒，即 7 天 |

Worker 回执仅在任务终态、没有 recovery 责任、对应 attempt 已有最终 outcome，且关闭后满保留期时清理。未关闭或仍恢复中的记录不因时间到期删除。周期候选查询顺带执行最多 100 条的有界清理。当前没有自动删除冻结 attempt 快照或容量释放回执；不能把 Worker 回执清理理解为全部历史数据清理。

## 9. 停机升级、备份与回退边界

升级前必须停止旧调度写入和宿主 mutation，核对 Worker 退出、实际运行组件和数据库状态，保存一致的数据库备份、加密密钥、运行数据卷、已生效配置及对应镜像/版本身份。备份与恢复文件不得写入代码库，密钥和原始 spec 不得进入日志或验收报告。

旧 running 记录在迁移后保留 `previous_status`，置为 queued/reconciling/recovery_required 并清除旧 lease；迁移不会补造并不存在的冻结 attempt。失败但仍 reserved 的环境继续占位。旧暂停环境写入 `admin_review`，不能迁移后被自动重新启动。

迁移在一个 SQLite 事务中完成 DDL、元数据、序号与状态变换，验证成功后才设置 user_version。中途失败必须整笔回滚，不能用手工改版本号或单独补表绕过。v3 → v4 没有在线混跑兼容窗口；旧 Worker 与新库不能交叉执行。

回退旧版本只能在停止新写入和新宿主 mutation 后，恢复迁移前的成套备份及匹配版本，再核对实际组件。禁止让 v3 程序读取已写入的 v4 库，禁止只把 user_version 改回 3，也不能只回退数据库而忽略迁移后已改变的运行资源。代码、数据库、配置、加密密钥和数据卷必须作为同一恢复边界。

## 10. 本机验证与尚未验收项

`tests/test_r2_orchestration.py` 使用独立临时数据库、合成账号与可控时钟，覆盖迁移事务回滚、结构指纹、固定快照、阶段与 boot fencing、操作回执重放、defer、维护模式、容量释放、重启核对、取消与撤权竞态。`tests/test_store_transactions.py` 保留 Store 的读写事务和资源关闭回归。旧 Worker、迁移和账号恢复测试已经适配协议 2 的真实证据路径。

本轮按最新要求只做本机初步验收。合成 SQLite 回归不等价于 Docker 实际停止证据；本机容器联调不等价于远端部署通过；短请求成功不等价于并发、长时间恢复或资源上限压力验收。服务器、长负载、真实备份恢复演练与既有 A/B 升级均不在这份文档的通过声明内，后续必须另外记录授权范围与实际证据。
