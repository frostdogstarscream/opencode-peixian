# 第三轮：本机稳定性与账号事件共享

## 适用范围

本轮在 `codex/account-eventhub-r3` 开发，从 R2 检查点 `241a4a3495010be85ed1bb1af3d88874947cd7bb` 继续。实现 V1.2 的独立 PR-5A AccountEventHub，并修复本机验证发现的问题。只使用 Windows 本机、Docker Desktop 和两个合成普通账号；不进行远程、Linux 主机、并发、持续负载或付费模型测试。

默认仍为单 Control 进程、单宿主 Worker、SQLite schema 4、部署配置 v3、Worker 协议 2。保留 v1/v2 配置读取。不启用多进程 Control、Runtime Pool、休眠、业务队列、Redis 或 PostgreSQL。

原 `14090` 和原 A/B 不在本轮升级范围。独立试用入口为 `https://127.0.0.1:19444`，部署标识沿用 `synthetic-r2-local`。这里的模型是本机合成协议服务，回答用于验证流程，不能评价真实模型能力。

## 用户能看到的变化

- 同一个账号打开多个页面或同时使用 Python，订阅共用一个上游读取器，各自的登录或令牌仍独立验证。
- 撤销一个令牌会关闭对应订阅，其他有效订阅继续使用；停用账号会关闭整个账号的事件读取。
- 网络断开、环境版本变化或通知堆积时，页面重新查询历史与资源列表，不把断线前后不完整的正文直接拼起来，不自动重发生成或工具调用。
- 超级管理员的运行环境维护区域增加事件连接计数。普通管理员与用户不能读取这个诊断接口，也不会看到其他账号信息。
- 明确恢复手动暂停的环境时清除原手动暂停意图；普通配置完成、回滚或安全阻断不能代替此操作。

## 配置和有界资源

部署配置的 `concurrency` 可以增加以下字段；不填写则使用默认值。统一约束在 `services/peixian-control/shared/eventhub_config.py`，Control 和部署脚本读取同一来源。

| 字段 | 默认值 | 范围与用途 |
| --- | --- | --- |
| `hub_queue` | 64 | 每订阅 1～256 条通知；只存资源失效通知，不复制回答正文 |
| `hub_idle_seconds` | 10 | 最后订阅离开后的空闲保留秒数，1～60 |
| `hub_retention_seconds` | 60 | 仍生成或活动不明时的最长保留秒数，1～300；不得小于 idle |
| `hub_reconnect_seconds` | 15 | 上游退避等待上限，1～30 秒，另有小幅随机抖动 |
| `hub_shutdown_seconds` | 5 | 关闭 Hub 集合的预算，1～5 秒 |

Hub 数不超过运行环境上限、正文 owner 上限和 SSE viewer 上限三者中的最小值。保留旧 SSE 的总订阅及单账号限制，不因共享上游取消客户端名额检查。容量紧张时可以提前回收没有订阅者的 Hub，这不取消模型任务。

每个订阅队列去重，满时用 `resync_required` 替代积压通知；其他订阅不等待慢消费者。正文仍由账号独立的 LiveTextCache 有界管理，上游不连续时释放旧 owner 和不完整正文，通过持久消息补齐。保留时间结束或 Control 重启后没有离线连续采集保证。

## API 与 Python

保留 `GET /api/console/v1/events` 与 `event: change`。增加以下通知：

```text
event: change
data: {"type":"resync_required"}
```

收到后合并刷新当前会话历史、会话列表和资源状态，不以该通知触发新回答。前端已有请求合并器负责单请求在途和后续一次补刷。Python 示例 `services/peixian-control/examples/console_client.py` 的 `events()` 和 `run_message()` 使用相同原则。

超级管理员可读取 `GET /api/console/v1/admin/diagnostics/events`，返回 Hub、上游连接、订阅、保留、重连、队列溢出和固定关闭原因计数。不返回账号标识、正文、服务地址或凭据。计数随 Control 进程重启清零，不能作为持久监控历史。

## 本机启停与验证

以下命令从仓库根目录使用现有虚拟环境运行。配置和私密测试清单均位于 Git 忽略的 `.runtime/r2-local/`，不要复制进源码仓库或交付包。停止 Worker 前应确保没有进行中的宿主变更。

```powershell
$env:Path = 'C:\Program Files\Docker\Docker\resources\bin;' + $env:Path
powershell -NoProfile -ExecutionPolicy Bypass -File deploy/peixian/platform.ps1 -Action up -Config deploy/peixian/.runtime/r2-local/profile.json
powershell -NoProfile -ExecutionPolicy Bypass -File deploy/peixian/platform.ps1 -Action worker-start -Config deploy/peixian/.runtime/r2-local/profile.json
```

每次更换 Control 后，核对 `runtime_management` 的已登记与已连接数量，并等待两个账号 `ready/open`。重启后默认保护，不能把容器 healthy 直接当作业务入口已开放。存在恢复责任时，由超管在维护界面处理；不要编辑数据库状态、跳过许可或重复提交模型请求。

顺序功能脚本需要两个环境已就绪，使用新的报告文件名：

```powershell
services/peixian-control/.venv/Scripts/python.exe deploy/peixian/r3-local-check.py --manifest deploy/peixian/.runtime/r2-local/manifest.json --output deploy/peixian/reports/r3-local-new.json
services/peixian-control/.venv/Scripts/python.exe deploy/peixian/r3-revocation-check.py --manifest deploy/peixian/.runtime/r2-local/manifest.json --output deploy/peixian/reports/r3-revocation-new.json
services/peixian-control/.venv/Scripts/python.exe deploy/peixian/r3-restart-check.py --manifest deploy/peixian/.runtime/r2-local/manifest.json --output deploy/peixian/reports/r3-restart-new.json
services/peixian-control/.venv/Scripts/python.exe deploy/peixian/r2-local-smoke.py --manifest deploy/peixian/.runtime/r2-local/manifest.json --output deploy/peixian/reports/r3-smoke-new.json
```

这些脚本仅接受固定本机合成部署。第一个创建并撤销临时测试令牌；第二个停用并重新启用合成 B，原认证全部失效，新测试令牌只写回私密清单。第三个核验 Docker 归属标签后仅重启空闲合成 A Gateway，检查历史和恢复后的新请求；先确认没有其他任务在该账号执行。若中途恢复失败，检查账号状态和失败报告，通过平台管理入口恢复，不清空账号数据。不要同时运行多个脚本或在测试期间另开同账号页面，以免改变期望订阅数。

## 备份、恢复与回退

沿用 `R2_LOCAL_OPERATIONS.md` 的冻结、暂停、停止写入者和全量备份流程。`backup` 包含控制库、账号卷、发布和 Worker 状态、配置及匹配密钥；`upgrade-backup` 是控制卷升级保护，不能代替全量备份。

本轮修复备份辅助容器的 Python 搜索路径，显式设置固定 `PYTHONPATH=/app`，使 schema 4 的身份校验模块可以加载。本机已成功备份并验证七个卷、两个账号及匹配密钥。

完整恢复要求目标账号容器、网络和卷不存在。当前工具保留账号 Runtime ID 和全局资源名；仅更换部署 ID、端口或数据根路径，不会自动给这些资源重新编号。当前机器仍保留源账号卷，因此新命名空间恢复预检正确拒绝 `restore_target_resources_already_exist`。没有删除源资源，也没有宣称完整恢复成功。以后可在资源确实为空的独立目标执行恢复演练。

回退只能使用兼容 schema 4 / 协议 2 的匹配版本，先关闭本轮 reader 并保留数据。不能降低数据库版本号或回退到原始 schema 3 组件。实际版本与镜像以交付包 `release-manifest.json` 和 `SHA256SUMS` 为准。

## 交付边界

包包含提交源码、四类匹配镜像、离线依赖、手册、OpenAPI、脚本和脱敏报告，不包含现有账号数据、密码、密钥、浏览器状态、完整备份或运行目录。镜像为 linux/amd64，仅在 Windows Docker Desktop 上验证；镜像导出不代表 Linux 主机部署通过。

验收记录见 `reports/R3_LOCAL_REPORT.md`。PR-5A 的代码与本机初检结果独立记录；V1.2 的生产持续负载、全部协议故障场景、完整恢复和 50 路活动任务验收仍未完成。
