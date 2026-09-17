# PR-7B 持久等待队列

这是开发与本机合成验收版本，不是生产批准。原 PR6 门槛继续有效，自动休眠仍关闭。

## 配置和兼容

使用 `server/platform.runtime-pool.example.json`：配置仍为 v4、schema 仍为 v5，显式设置 `capacity_wait_enabled=true`。默认 1000 条等待、1800 秒有效期、10 秒 tick、每批 8 条，按实际部署另行批准。参数仅来自受信部署配置，不接受普通用户覆盖。开启后持久策略为版本 2，旧 PR7A 代码拒绝读取该策略；v4/v5 历史迁移脚本不修改。

空数据库可直接初始化。现有按需库切换必须先冻结、解决已预留／执行任务与恢复责任、备份并停止旧组件，再在单次获准启动中设置 `PX_ALLOW_POOL_POLICY_CHANGE=1`；这不是在线管理 API。启动后移除该临时许可。关闭等待同样要求显式离线许可；已有等待可继续查询、取消和到期清理，但不晋升。存在旧等待时拒绝新的启动，避免插队；清空后按无等待的显式准入处理。策略版本仍保留为 2，不能降版本或用旧镜像直连。既有非按需部署不改变行为。

新版 Worker 声明 `runtime_pool_v1,runtime_pool_wait_v1`；开启等待的 Control 在领取任务及内部写入前检查新能力。构建匹配 Control、前端、Worker 工具；示例 candidate 标签不代表镜像已经存在。

## 用户行为

点击“启动助手”返回申请，可能立即分配或等待。等待显示近似位置和到期时刻；取消只操作本人当前申请。不同设备重复点击保持同一申请，不改变队列顺序和到期时间。关闭网页不取消申请。到期后需手动重新申请，不保留无限自动续期。

没有自动抢占或承诺启动时间。就绪后由用户明确发送问题，草稿不自动执行。只有完成真实停止核对才释放名额；未知活动或恢复责任继续占用。安全修复使用原名额，管理员暂停及账号停用不会被等待晋升覆盖。

Python：`start_runtime(idempotency_key=...)` 后以低频 `runtime_status()` 查询 `waiting.approximate_position`、`waiting.expires_at` 和 `ready`；不要把历史受理回执当当前状态。取消使用当前 `state_version` 和 `job.id` 调用 `stop_runtime`。429 表示队列或其他资源限额；未知写入结果先查状态，不换键盲重试。

## 调度、备份及发布

Control 的独立有界 tick 只运行短 SQLite 事务，不做 Docker 或 HTTP I/O。新申请、已确认完成和核对释放复用相同 FIFO 分配规则；只有 queued 被 Worker 领取。维护中可取消/过期，但不晋升。恢复工具保存等待记录，空目标恢复后将其取消为 `recovery_reconfirmation_required`，维护冻结、旧认证撤销，不自动重放。

正式发布检查额外要求 PR7B-fifo-cancel-expiry、PR7B-real-slot-transfer、PR7B-waiting-restore，仍需 PR7A 和 PR6 证据且绑定源码与包。当前本机结果见 PR7B_REPORT.md，不替代 Linux、负载及生产恢复验收。
