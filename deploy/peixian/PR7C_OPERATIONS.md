# PR-7C 空闲暂停使用和维护

默认 idle_pause_enabled=false。仅配套新版 Control/Worker/Gateway/Relay/Agent 才可在独立配置开启；镜像标签与运行期活动证明均校验 idle_activity_v1。首次开启将持久池策略提升为 3，schema 保持 5，历史迁移不变。旧程序不能直连策略 3 控制库。

隔离配置启用：runtime_pool.idle_pause_enabled=true；idle_timeout_seconds 默认 600，min_ready_seconds 和 resume_cooldown_seconds 默认各 60。不得用缩短阈值代替容量验收。现有库开启或关闭须冻结平台、停止旧写入组件、完整备份，再单次以 PX_ALLOW_POOL_POLICY_CHANGE=1 启动匹配 Control；其他未完成任务／恢复责任阻止切换。关闭不撤销已经进入执行的自动暂停责任；尚未领取的自动任务由新版 Worker 领取检查时取消。

Worker 每个 scheduler_tick_seconds 周期最多探测一个轮转账号，降低单宿主调度阻塞；晚回收不抢占繁忙账号。Control 返回受限候选，Worker 在数据库事务外取得实际状态，再条件提交。候选不改变名额。长任务结束、解析完成、插件测试、下载和确认回复会重置计时；列表、SSE、登录和轮询不重置。

关闭入口之后再次即时采集 Agent/Relay。活动代次变化、证据未知或启动身份不符时撤销自动暂停，不执行 Docker stop，也不释放名额。入口恢复仍受当前权限和安全许可约束。已进入 applying 后不能撤销，确认全部停止后才归还并晋升等待者。

普通用户看到“因空闲已暂停”，原文件、会话和配置保留；继续使用时点击启动助手，可能进入容量等待。不会自动重发问题或插件请求。管理员人工暂停不能由空闲回收撤销操作解除。

生产发布沿用 PR6、PR7A/B 门槛，另要求 PR7C-activity-contract、PR7C-idle-cancel-race、PR7C-real-idle-release。源码测试、真实本机容器、Linux 与负载证据必须分别记录。测试源码或镜像可用不代表正式发布批准。
