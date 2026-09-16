# R2 Windows 本机操作与恢复

本轮使用独立部署 `synthetic-r2-local`，应用入口为 **https://127.0.0.1:19444**，Control 内部入口为 `127.0.0.1:14096`。原 `14090` 环境及原 A/B 数据没有在本轮升级。本文只适用于这套本机独立环境；账号凭据通过既有私密交付渠道获取，不打印或复制私密 manifest。

## 1. 成套版本与路径

| 项目 | 本轮配置 |
| --- | --- |
| 仓库 | `D:\Code\PeiXianDB\opencode` |
| 配置文件 | `deploy\peixian\.runtime\r2-local\profile.json` |
| 宿主数据目录 | `deploy\peixian\.runtime\r2-local\data` |
| Python | `services\peixian-control\.venv\Scripts\python.exe`，本机验证版本 3.12.14 |
| 配置 / 数据库 / 内部协议 | config **3** / schema **4** / Worker 与 Runtime protocol **2** |
| Control | `agent-platform-control:orchestration-r2` |
| Gateway 与 Relay | `agent-platform-gateway:orchestration-r2` |
| Agent | `peixian-opencode:1.18.30-managed-r2` |
| HTTPS Proxy | `agent-platform-proxy:nginx-1.28.0` |

镜像标签可被重新构建覆盖，不能只凭标签文字认定当前运行版本。`check` 核验镜像实际能力标签，`up` 固定本次检查得到的镜像 ID 并检查数据库兼容性。Control 必须支持 config 3、schema 4、worker/runtime protocol 2，Gateway/Relay/Agent 必须声明 runtime protocol 2；不能把旧 Worker、旧 Gateway 或旧 Control 单独换入本轮环境。schema 4 数据库不能交给仅支持 schema 3 的旧镜像启动。

## 2. 使用现有虚拟环境管理服务

在 PowerShell 中设置本轮固定路径：

```powershell
$R2Repo = 'D:\Code\PeiXianDB\opencode'
$R2Deploy = Join-Path $R2Repo 'deploy\peixian'
$R2Profile = Join-Path $R2Deploy '.runtime\r2-local\profile.json'
$R2Python = Join-Path $R2Repo 'services\peixian-control\.venv\Scripts\python.exe'
$R2Wrapper = Join-Path $R2Deploy 'platform.ps1'
$R2Options = @{ Config = $R2Profile; Python = $R2Python }

& $R2Python --version
& $R2Wrapper -Action status @R2Options
& $R2Wrapper -Action check @R2Options
```

现有 `.venv` 已用于本轮验证，无需重建或升级依赖。确需重新准备执行器环境时，应先停用本配置的 Worker，再按 `deploy\peixian\requirements.txt` 安装到指定虚拟环境；不要改系统 Python，也不要在运行中替换虚拟环境。以下命令仅用于依赖准备，不属于日常启动步骤：

```powershell
& $R2Python -m pip install -r (Join-Path $R2Deploy 'requirements.txt')
```

常规启动与隐藏 Worker：

```powershell
& $R2Wrapper -Action up @R2Options
& $R2Wrapper -Action worker-start @R2Options
```

`worker-start` 使用隐藏窗口，记录 PID、创建时间、脚本、配置及已验证 Python 子进程身份。它管理的记录与日志位于 `data\worker\windows-worker.process.json`、`windows-worker.stdout.log`、`windows-worker.stderr.log`。日志与宿主数据应留在本轮私有目录，交付报告只摘取脱敏结果。

停止时先等管理页面中的环境任务结束：

```powershell
& $R2Wrapper -Action worker-stop @R2Options
& $R2Wrapper -Action stop @R2Options
```

停止脚本会检查 Worker 是否空闲，并核验进程身份后按子进程到父进程的顺序停止；`stop` 还会检查宿主 Worker 锁，再停止 Control 与 HTTPS 入口。**账号的三个运行容器需先在管理页面逐个暂停**，该命令不会代替账号暂停流程。历史上直接手动启动、只有 `worker.pid` 的进程不属于此 wrapper 的跟踪记录；出现“无已跟踪 Worker”不能据此认定没有执行器运行。由原启动者核对并停止该进程后，再切换到 wrapper 管理，不能按 Python 进程名批量终止。

## 3. Control 重建后的连接恢复

Control 被 Compose 替换时，动态加入的 Runtime 管理网络会丢失。新版 `up` 在返回 `started` 前，读取本部署已登记 `state.json`，核对实际三组件和管理网络的 internal、managed、账号、Runtime、部署标签，并核验 Control 归属；随后按固定网络和容器 ID 幂等重连、读回确认。

本轮已观察到 `registered=2 / connected=2`，随后 Worker 将两个账号恢复到 `ready / open`。这证明本机这次重建恢复成功；后续每次仍应检查实际返回和账号状态。返回 `runtime_management_recovery_pending` 时保留现场并检查登记状态、Docker 组件与网络，不能将其当作启动成功，也不要手动连接其他项目网络。仅已暂停、实际全停且历史网络缺失的记录允许跳过。

网络恢复之后，仍需当前 Control/Worker 完成启动身份、版本与 Gate 观测。判断账号可用应同时满足 `ready`、`revision=desired`、`gate_policy=open`，且无安全阻断或待恢复责任；只看到容器 running 或 `/health` 成功不足以确认业务恢复。

## 4. 完整备份、跨 schema 升级与恢复

**`backup` 是完整备份；`upgrade-backup` 是跨 schema 启动门禁所需的 Control 卷备份，二者不能互相替代。** 完整备份包含 Control 数据、账号命名卷、Worker 发布状态、匹配的密钥和 TLS 文件；升级备份仅覆盖 Control 数据库与已发布包，存放在本配置数据根目录的 `upgrade-backups` 中。

完整备份的准备顺序：暂停全部账号并等 queued/running 任务完成；schema 4 环境还须在超级管理员维护页面设为 frozen，处理未完成的 drain/recovery 责任；停止 Worker，再停止 Control/HTTPS。所有命名卷写入者均需停止。备份目标必须为数据根目录外的全新目录：

```powershell
$R2Backup = Join-Path $R2Deploy ('.runtime\r2-backups\full-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
& $R2Wrapper -Action backup @R2Options -Destination $R2Backup
& $R2Wrapper -Action verify-backup @R2Options -Archive $R2Backup
```

备份内容含恢复所需私密材料，不进入源码包或公开报告。失败时保留部分产物用于排查，不能把缺少完成清单的目录当成有效备份。

数据库 **schema 3 → 4** 与平台 **config 2 → 3** 是两种版本变化。将来明确授权迁移旧库时，先用与源环境匹配的配置和镜像完成上述全量备份并保留源配置，再准备整套本轮镜像和目标配置，保持数据停止状态，然后执行：

```powershell
& $R2Wrapper -Action render @R2Options
& $R2Wrapper -Action upgrade-backup @R2Options
& $R2Wrapper -Action up @R2Options
& $R2Wrapper -Action worker-start @R2Options
```

升级门禁要求 Control 卷仍处于与升级备份相同的停止状态。旧库迁入 schema 4 后保持 frozen，需核对责任、容量和账号状态后由超级管理员解除维护；不能跳过门禁、手改 schema 版本或仅替换一个旧镜像回退。本轮独立环境的启动与单元测试不等于已完成旧 `14090` 库的迁移演练。

全量恢复要求预先准备**新部署 ID、空数据根目录和无冲突 Docker 资源**的恢复配置，并用 `-Action restore -Config <恢复配置> -Archive <完整备份目录> -Python $R2Python` 执行。即使改了部署 ID，原 Runtime 卷、容器或网络仍存在时也会拒绝恢复，不应为绕过检查而删除原环境。恢复后账号为 paused、平台 frozen，旧浏览器会话与 Token 失效；核对数据和密钥匹配、完成正常恢复观测后，重新登录并逐个恢复账号。

## 5. 本轮结论范围

本轮以 Windows Docker Desktop 的两个独立合成账号做初步顺序功能检查，包含开通、会话、文件与账号隔离、忙时配置 defer 后应用，以及 Control 重建后的管理网络恢复。`r2-local-smoke.py` 读取既有私密测试配置；运行结果以实际脱敏报告为准，本文不附 manifest 或登录信息。

Linux 专项、并发容量、4 小时持续负载、完整备份恢复演练及全部崩溃/丢响应故障阶段没有在本轮实机执行。不能由本机初步通过推导为 50 个同时活动账号通过，也不能把保留的 `r2-acceptance.py` 场景列表当成验收结果。
