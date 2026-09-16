# 第一轮并发与稳定性加固：实施与验收指南

本轮基线 `dff944188605ff65a681409423347fcb57066501`，分支 `codex/concurrency-hardening`。目标为 16 核、32 GiB 单平台服务器，50 个不同账号各进行一路回答或轻量内网查询，模型服务器独立。数据库仍为 schema v3，Control 和宿主 Worker 均为单进程；不引入 Redis、多节点或业务 Run。

**这是一轮加固及验收工具交付，不是“16 核 32 GB 已承载 50 个真实助手”的承诺。** 实测结果见 [验收报告](HARDENING_R1_REPORT.md)。原部署、账号和卷不在本次测试范围。

## 1. 实现范围

| 层次 | 实现 |
|---|---|
| SQLite | 普通查询只读连接；一致视图用短读快照；检查及修改用短写事务；WAL 只在初始化设置；连接、BEGIN、业务及 COMMIT 失败均清理；忙等待最多 1 秒 |
| 异步执行 | 同步业务段经有界 DB 工作池执行，事务始终在一个线程；请求取消不会提前释放仍在工作的线程；关闭后不再提交排队工作 |
| 认证 | Argon2 独立工作池；哈希不占用写事务；登录、改密、令牌签发及管理密码动作在提交时核验当前身份；登录失败状态有长度、TTL、总量及来源限额 |
| 查询量 | 鉴权读取同时取得本请求的账号环境视图；不跨请求缓存认证和凭据；一次消息请求不再重复读取相同环境 |
| SSE | 与普通 HTTP、下载分池；响应头之前准入；viewer、正文 owner、上游连接分别跟踪；准备态过期及响应取消清理；独立身份复核、不受慢发送阻塞 |
| 前端 | fetch SSE 识别 HTTP 状态及 Retry-After；读取断线退避重连；按资源刷新，消息最快 500 ms、单请求在途；隐藏页降频；旧响应不覆盖新会话；失败保留草稿 |
| 部署 | 配置 v2、显式 CPU 共享规划、严格内存预算、网络池容量、统一 Worker/Control 配置、版本兼容预检 |

SSE 复核首轮按连接标识分散在 0～2 秒内，避免同时建立的订阅周期性挤满队列。慢建连或延后启动响应，在发正文前再次核验身份。常规周期为 2 秒，单次检查最多等 2 秒，过载时关闭流，客户端按规则重连。

管理审计优先写 SQLite；若数据库在有界等待内仍不可写，则用仅含操作者 ID、角色、动作、目标 ID、结果的日志记录降级审计，避免把已执行成功的修改伪装成可重复提交的 500。此降级记录需运维收集容器日志，不承诺 SQLite 审计页在磁盘故障时仍完整。

## 2. 配置 v2 与容量门槛

独立示例：`deploy/peixian/server/platform.50-io.example.json`。

- v1 保持默认 4 个环境、原预算公式和最大 32；v2 允许最多 64，目标示例为 50。
- v2 增加 `profile`、`control_resources`、`capacity_policy`、`concurrency`。不接受任意字段。
- `cpu_mode=shared` 必须显式设置；Docker 每个容器的 CPU cap 仍保留。
- CPU 准入：`cpu_reserve + 全部账号 CPU cap / cpu_overcommit_factor`。这是规划余量，不是为 Control 硬隔离 CPU。
- RAM 准入：`全部账号 RAM cap + Control RAM + host_memory_reserve_mib`。不把 swap 当作容量；主机预留包含 Docker、代理及宿主 Worker，不重复加代理内存。
- 50 账号需要 150 个账号网络和一个入口网；每网 `/28`，预检还计入历史暂停环境和已有 Docker 子网冲突。计算通过不等于已经验证 Linux 内核桥接及 Control 挂接 51 网。
- v2 Control 镜像必须声明 `org.peixian.control.config.max>=2`。数据库版本不变不能代替配置兼容检查。

初始并发限额未因压测而上调：

| 参数 | 默认 |
|---|---:|
| HTTP 连接 / keepalive | 64 / 16 |
| SSE 总订阅 / 每账号 / 正文 owner | 128 / 4 / 64 |
| 下载并发 | 8 |
| DB 工作线程 / 排队 / 排队时间 / 锁等待 | 8 / 32 / 1 秒 / 1000 ms |
| 密码工作线程 / 排队 / 排队时间 | 2 / 16 / 2 秒 |
| 心跳 / owner 续租周期 / owner TTL | 15 / 5 / 20 秒 |
| 身份复核周期 / 撤销关闭门槛 | 2 / 5 秒 |
| Control 候选配额 | 2 CPU / 2048 MiB |

默认正文缓存最多 32 MiB、每账号 1 MiB、单段 256 KiB，并限制段、消息及去重标识数量。它是暂存覆盖层，容量不足、交接或重连后由持久消息历史补齐，不是新的消息数据库。

示例保留原账号容器上限：Agent 2048 MiB、Gateway 512 MiB、Relay 128 MiB。50 组加预留合计 **140544 MiB（137.25 GiB）**，CPU 规划值 **41.5 核**。16 核、32 GiB 必须拒绝该配置。应先对少量独立真实环境采集冷启动、长回答、插件大响应与文件解析峰值，再提出并回归候选配额；不能为了启动成功先填写未经验证的小值。

## 3. 本地代码检查

所有测试从各包目录运行。Windows 如默认 pytest 临时目录 ACL 不可写，指定一个全新的 Git 忽略 `--basetemp`，不要清理或接管已有目录。

```powershell
# services/peixian-control
& ./.venv/Scripts/python.exe -m pytest tests gateway/tests -q --basetemp=../../deploy/peixian/.runtime/r1-check-NEW
& ./.venv/Scripts/python.exe export_openapi.py

# packages/peixian-console
bun test tests
bun run typecheck
bun run build

# deploy/peixian
python -m pytest tests -q
```

本地存在固定 Bun 时可使用 `deploy/peixian/.runtime/bun-1.3.14/bun-windows-x64/bun.exe`，不要求更换机器全局版本。Linux 特有资源限制及符号链接场景若在 Windows 跳过，必须在目标系统重跑。

## 4. 三层证据与工具

### L1：自动化回归

`tests/test_store_transactions.py` 验证真实 SQLite WAL、快照、锁等待、异常清理和名额竞争。`test_concurrency.py`、`test_auth_issuance_races.py` 验证取消、关停、登录及凭据签发竞争。`test_stream_lifecycle.py` 验证准入、慢连接、未开始响应、取消、独立复核和清理。前端测试与浏览器检查互补，浏览器才会覆盖原生计时器等宿主行为。

### L2：真实 Control + 合成 Gateway

```powershell
# services/peixian-control；使用未存在的报告名
& ./.venv/Scripts/python.exe benchmarks/control_layer_load.py `
  --stages 10,20,35,50 --stage-seconds 30 --request-pause-ms 500 `
  --output benchmarks/control-load-NEW.json
```

使用独立临时目录、真实 SQLite、认证、单 Uvicorn 及回环 TCP；Gateway、模型、消息及取数使用测试桩。每账号双 SSE。消息 500 ms、会话 2 秒、身份/健康 5 秒、目录 30 秒；记录完整响应时间、HTTP 状态、池峰值、撤销、账号隔离与清理。

工具从 10→20→35→50 递增；失败保存报告，不覆盖旧结果。`--stage-seconds 3600` 可用于四阶段各一小时的控制层观测；**这不是 50 个真实账号环境持续四小时的替代品**。

### L3：真实独立部署

1. 用与当前部署不同的 deployment_id、数据路径、端口、证书及不重叠网络池配置独立环境。不要把示例的占位地址直接用于正式服务。
2. 先运行资源预检；未通过就停止增加环境。
3. 在通过预算的少量环境上用合成文件和请求采样，再固定候选配额与镜像身份。
4. 准备 50 个 `loadtest-` 开头、已经开通的普通账号及各自令牌。账号和令牌不能共用。私密 manifest 的格式见 `benchmarks/platform_load.py --help`，放在 Git 忽略目录或受限目录。
5. 执行真实访问脚本，并同步保存容器资源样本：

```bash
python deploy/peixian/platform-sample.py budget --config /secure/r1-platform.json --output /reports/budget-NEW.json
python deploy/peixian/platform-sample.py sample --config /secure/r1-platform.json --cgroup --samples 720 --interval 20 --output /reports/resources-NEW.json

python services/peixian-control/benchmarks/platform_load.py \
  --credentials /secure/synthetic-users.json --synthetic-deployment \
  --model-id APPROVED_MODEL --plugin-id SYNTHETIC_PLUGIN \
  --seconds 30 --soak-seconds 14400 --output /reports/real-workflows-NEW.json
```

采样只读、不重置 cgroup 计数；原始样本不包含账号名、凭据、模型文本或工作区路径。采样与负载命令需要并行执行。`platform_load.py` 不创建账号、不改配额、不输出令牌；只接受合成账号名称，失败或结果未知时不自动重发该用户的写操作。

真实脚本包含回答、插件连接测试、混合、双 SSE。**插件 `/test` 只是已发布插件的连接测试入口，不等于模型调用了工具。** 加 `--tool-generation` 的生成场景会要求本轮新消息中出现完成的插件工具；旧历史工具不能充数。单个阶段的工作流成功、抽样 busy 重叠、订阅成功分别记录，不据此直接宣布端到端容量通过。

重连高峰、慢接口、SQLite 锁等待、重启恢复、网络重新挂接和 OOM/重启计数仍须与真实部署联合验收。当前脚本不会主动杀死任何服务来注入故障。需在独立环境按操作记录执行故障演练；不要对现有用户环境使用故障注入。

## 5. 协议与客户端

- API 前缀和 Cookie/Bearer 认证不变。
- SSE 保留 `event: change`，data 的 `type=connected/updated`，可附 `resources` 白名单数组及 `session_id`；不包含正文和内部工具参数。
- 429/503 在适用场景提供 Retry-After。读取可按建议等待；生成、上传、插件调用及其他写操作不因过载自动重放。
- POST 上游超时或断线可能已经提交，返回 504“结果待确认”；先查询会话历史或状态。`run_id` 仍是接受回执，不是持久任务查询 API。
- Python 示例 `examples/console_client.py` 分开普通请求与 SSE 连接，暴露状态及重试等待值，401 结束订阅，保留调用者处理未知结果的责任。
- 新 OpenAPI 已导出到 `docs/openapi.json`。

## 6. 发布、备份与回退

- 新 Control/Gateway 候选标签为 `agent-platform-control:hardening-r1` 和 `agent-platform-gateway:hardening-r1`；Agent 基线不变。
- `platform-manage.py backup` 是完整部署备份：控制库、用户卷、配置发布目录及匹配密钥，过程协调 Worker 与服务。
- `platform-manage.py upgrade-backup` 仅保护控制卷升级，**不能代替完整备份**。
- 恢复仍拒绝静默覆盖现有目标；v2 恢复同样检查镜像配置能力。
- 回退到旧代码需要显式切回匹配的 v1 配置和经过验证的配额/镜像；不能只因 schema 仍为 3 就直接套用旧镜像。

```bash
# 在最终源码提交之后，显式选择配置对应的镜像
python deploy/peixian/platform-package.py --config deploy/peixian/server/platform.50-io.example.json --destination /delivery/r1-full-NEW

# Docker不可用时，只能交付明确标注“没有镜像”的源码/工具/依赖包
python deploy/peixian/platform-package.py --config deploy/peixian/server/platform.50-io.example.json --source-only --destination /delivery/r1-source-NEW
```

包采用允许清单，排除账号、密钥、数据库、运行目录和私有快照；包含源码提交、配置版本、镜像身份或“未包含”、安全有效参数、校验清单。源码工具包不能用于声称已交付完整离线镜像包。

下一轮继续处理执行器公平调度、Gateway 完整准入屏障、全活动跟踪、配置版本补排和安全出口阻断。本轮预先就绪环境的结果不覆盖配置更新期间的完整并发与故障恢复。
