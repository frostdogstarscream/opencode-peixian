# N1 外层关闭链与 N2 本机候选记录

基线为已推送的 `df7a111327a748c603f6195c9cfe0359bb2b5d3d`。保留 EH-B01/EH-B02、R4 缓存与打包改进。本记录不改变 V1.2 的 PR 编号。

## N1 源码修改

- Registry 在第一个 await 前关闭 viewer/download/Hub 准入。reaper、响应 owner 和所有 reservation 均请求停止；某账号或 Hub join 失败不阻止其他清理。
- Reservation 的关闭使用独立任务；调用方取消不撤销其清理。计数只释放一次；订阅关闭失败时仍执行响应关闭。
- Registry 使用现有 `hub_shutdown_seconds` 作为观察总预算，依次观察 Hub、reaper、owner、reservation；应用总预算为该值四倍，先观察 safety/streams，再顺序关闭三类 HTTP client 和两类工作池。不新增 schema/协议/配置字段。
- 阶段按固定资源类别记录 done/incomplete、timeout/close_failed/cancelled、未完成任务及工作线程数量；不记录异常文本、账号、凭据或正文。超时保留清理任务引用，不能等同成功回收。
- 应用收到退出异常或取消时，必要有界收尾后保留原异常；正常退出遇到组件失败则报告 `shutdown_incomplete`。
- 容量压力遇到慢 closing Hub，等待上限为 `min(1秒, hub_shutdown_seconds)`，之后返回 503。没有清理完成前不移除账号占位、不创建第二个 reader。
- 应用日志的 `shutdown_summary` 是退出时快照，不是进程外持久监控。线程与不合作清理在预算后可能仍未结束，需要进程监督策略处理，不保证强制清理成功。
- 容器 Uvicorn 设置 5 秒连接退出等待上限；Compose 停止宽限期为 `10 + 4 * hub_shutdown_seconds` 秒，覆盖进入 lifespan 前的等待和应用清理预算。退出摘要使用 Uvicorn 已配置的日志通道。

新增 `tests/test_app_shutdown.py`；扩展 Registry、EventHub 测试覆盖前置失败、独立账号、调用方取消、原异常保留及容量压力。已有 HF1 正向回归保留。

## N2 执行记录

候选源码提交后执行最终完整回归与本机独立环境验证，结果在后续证据提交记录。此文件初始版本不预填通过；镜像、运行环境和包均需单独核对。

打包部署资料白名单新增本文件及 `EVENTHUB_HF1_REVIEW.md`，真实临时 Git 打包测试同时核对两份文件在源码归档和部署资料目录中存在。

正式包要求 `source_matches_commit=true`、固定源码 SHA、镜像身份、配置、SHA256SUMS 与对应测试证据；开发包 assembled 不替代正式门槛。

## 范围保留

仅授权 Windows 本机初检，禁止触碰原 14090/A/B。N3 Worker unknown 尚未定位，不能选一个可能原因当根因；N4 空引擎恢复、N5 目标主机和持续负载未执行。PR-6 退出审批、PR-7/8 与多节点不由本小补丁宣称完成。
