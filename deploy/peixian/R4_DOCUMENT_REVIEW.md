# 第一轮方案对照检查与第四轮补齐记录

## 1. 基线与适用范围

本次依据用户提供的 `通用Agent平台_第一轮并发与稳定性修改方案_50并发_16核32G_V1.0.md` 核对现有代码，并在 `codex/stability-followup-r4` 修改。开发起点为第三轮已推送的 `1ebcc34b91906eacd98f66742bb62f6e619d46d6`。

原方案属于较早基线，其“尚未实施”“保持 schema v3”“下一轮才做调度”“本轮不做 EventHub”等文字是当时的阶段安排。当前已经完成后续版本，本次保留 schema 4、配置 v3、协议 2、调度与安全控制、AccountEventHub；没有退回旧分支或重新创建原第一轮分支。原文档保持不变。

按用户后续明确要求，只在 Windows 本机初步验证，不执行 Linux 主机、远端、50 并发或持续负载测试。不修改原 `14090` 和原 A/B；实际试用继续使用独立合成环境 `synthetic-r2-local` 的 `https://127.0.0.1:19444`。

## 2. 逐项对照

| 原方案要求 | 当前核对结果 | 本次处理 |
| --- | --- | --- |
| R0：独立 50-I/O profile、统一预算、旧配置兼容 | 已有 `platform-capacity.py`、`platform-config.py` 和 `platform.50-io.example.json`；v2/v3 软件上限 64、旧 v1 保留旧边界 | 保留现有逻辑，不修改为未经测量的低内存配额 |
| R0：资源画像、网络规模、16 核/32 GB 上 50 路实际容量 | 模板和工具不构成实际容量通过证明；本次未执行规模测试 | 明确列为未验收，不放宽内存检查、不增加 swap 作为容量 |
| R1：普通只读、短快照、WAL、写事务原子性、失败清理 | 已有 `Store.read/tx`、初始化 WAL、有界锁等待及真实 SQLite 回归 | 保留，并运行完整后端回归 |
| R2：有界线程、密码计算与提交复核、登录限流 | 已有独立 DB/密码工作池、有限队列、限流 TTL 与来源控制 | 增加工作池排队、执行、容量和拒绝的脱敏汇总诊断 |
| R3：HTTP/SSE/下载资源分离、响应前准入、每流认证和释放 | 已有独立客户端、StreamRegistry 和 AccountEventHub | 保留并回归真实两账号订阅和令牌撤销 |
| R3：临时正文有界、超限重取历史、缓存淘汰指标 | 缓存已经有界且不会输出截断前缀，但淘汰缺少明确通知和原因计数 | **本次补齐**账号级 resync 与固定原因计数 |
| R4：按资源变化刷新、单请求在途、尾随合并、可见性、草稿 | 已有 `refresh.ts`、`events.ts`、资源总线及对应测试 | 复用原重同步处理；仅增加超管折叠诊断，不向普通用户展示内部指标 |
| §11：备份、匹配镜像、OpenAPI、源码与离线包 | 已有全量 backup 与控制卷 upgrade-backup 区分；旧打包程序仅 source-only 路径自动生成源码归档 | **本次修复**完整镜像包也自动归档指定 Git 提交；同步 API 与说明 |
| L2/L3/L4、100 订阅、4 小时、真实模型与接口 | 不能由单元测试或两个账号推导 | 本次明确未执行，原生产验收门槛继续保留 |

当前旧 50-I/O 模板保留每账号 2,688 MiB 内存上限、3 CPU 上限。按现有预算算法：50 账号加 Control 和预留内存需要 **140,544 MiB（137.25 GiB）**；CPU 规划为 **4 + 150/4 = 41.5 核**。这些是配额预算计算，不是实测最低硬件需求；它不能通过 16 核、32 GB 的预检。没有通过降低配额或忽略预算把模板包装成“50 并发可用”。

## 3. 本次实现

### 临时正文淘汰与恢复

`control/live_text.py` 为部分字节超限、总字节、账号字节、部分/消息数量、文本/消息过期、owner 过期增加固定原因计数。正常原文覆盖、消息完成和主动释放不被记成容量淘汰。

活跃 owner 对应的账号最多保留一个待同步标记，多个淘汰合并；释放或过期时清理标记，不形成无限账号记录。只有相同账号、相同 owner 能消费标记。EventHub 在读循环中检测标记，即使上游没有再发 token，也通知该账号订阅 `resync_required`；重新取得过期 owner 时同样要求读取历史。不会向其他账号广播，也不重发生成请求。

### 管理诊断

现有超管接口 `GET /api/console/v1/admin/diagnostics/events` 增加 `cache` 和 `work` 字段，原 `hub/streams` 保持兼容。工作池返回 outstanding/running/queued/capacity/rejected/closed，缓存返回原有大小计数、待同步数量和固定淘汰原因。计数不含账号、任务参数、正文或密钥，进程重启清零。

管理页面增加“后台资源诊断”折叠区。普通管理员、普通用户仍返回 403；没有新增外部任意转发能力。诊断用于排查，不能代替历史监控或容量验收。

### 完整源码交付

`platform-package.py` 的完整镜像包与 source-only 包均自动执行指定提交的 `git archive`，不再依赖手动预置 `source.tar.gz`。源码归档已存在时拒绝覆盖，要求新目录；原镜像和归档不删除。不要再使用旧操作方式先手动创建 source.tar.gz 再运行本程序。

## 4. 本机验证记录

| 检查 | 结果与边界 |
| --- | --- |
| Control 全量 | **277 passed**，85.80 秒，保留两个既有 FastAPI/Starlette 弃用警告 |
| 新工作池断言定向复核 | **6 passed**；线程取消后仍占容量、排队/拒绝计数及最终释放 |
| Windows 部署全量 | **178 passed，2 skipped，163 subtests passed** |
| 最后打包保护定向复核 | **8 passed，2 subtests passed**；包含真实临时 Git 提交归档、PAX 提交标识、文件内容与不覆盖旧归档 |
| 前端 | **51 passed，2151 assertions**，类型检查与构建通过 |
| 淘汰隔离与通知 | 确定性测试覆盖字节超限、跨账号容量淘汰、过期、owner 清理；Hub 没有后续事件时仍通知受影响订阅，另一账号未收到通知 |
| 实际两账号初检 | `reports/r4-local-check.json`：三订阅两上游、合成短回答、账号边界、单令牌撤销、最后订阅回收和重开历史均通过 |
| 实际管理页面 | Chrome 独立上下文中展开“后台资源诊断”，确认缓存、数据／密码排队和拒绝计数可见；平台正常服务，待恢复及停止待确认均为 0 |

此次实际令牌撤销记录为 **0.312 秒**，只是单次功能计时，不是延迟分位。合成模型在本机提供 OpenAI 兼容响应，未调用付费模型。超大缓存边界由有界合成用例验证，不声称进行了真实长回答或资源压力测试。

实际替换 Control 后读回两个管理网络连接；两个普通环境为 ready/open、desired 与 applied 一致。首次用另一个配置文件路径启动 Worker，被已有进程记录的配置身份保护拒绝；随后备份原配置，在原配置路径更新测试镜像并正常启动，没有绕过进程保护或修改账号数据。

## 5. 本机操作与交付

Control 镜像：`agent-platform-control:stability-followup-r4`，本机镜像身份：

`sha256:adc2921fe1ee23e52f2b7a4a8f921546f6c469210fdc21dd7541e3afdafd25b5`

Gateway/Relay、Agent、HTTPS Proxy 沿用 R3 匹配镜像；本次不改它们的内部协议。独立配置仍位于 `deploy/peixian/.runtime/r2-local/profile.json`，旧配置已留本机备份。按 `R3_LOCAL_OPERATIONS.md` 使用相同配置路径管理 Worker；操作脚本不会因为另一个文件内容相同就接管已有 Worker。

从仓库根目录打包，目标必须是新的目录，**无需预先创建源码归档**：

```powershell
services/peixian-control/.venv/Scripts/python.exe deploy/peixian/platform-package.py --destination deploy/peixian/dist/agent-platform-r4-local-NEW --config deploy/peixian/.runtime/r2-local/profile.json --source-commit HEAD
```

完整包包含已提交源码、匹配镜像、原有离线 wheels、文档及校验清单。不会收集 `.runtime`、真实账号、私密凭据或备份。包目标镜像为 linux/amd64，在 Windows Docker Desktop 上运行应用不等于 Linux 主机验收。

本轮保存本地提交，不自动推送。完整恢复演练、真实服务器、Linux 压测、50 路容量、持续负载和生产切换仍未执行；R3 记录的完成回执竞态诊断保留项也不因本次缓存修复被宣称解决。
