# 第二轮本机初步验收记录

## 1. 范围与结论

本轮按用户最新要求，仅进行 Windows 本机初步验证，暂停 Linux 专项、远端、并发和持续负载验收。PR-4/PR-5 的代码作为同一版本集合交付；源码回归通过和两账号本机功能通过，不等于 V1.2 全部发布门槛通过。

开发分支为 `codex/runtime-orchestration-r2`，第一轮检查点为 `bb7221e706ab0db6832ad0cf88bb505dc4dd6ac9`。原本机 `14090` 服务、原 A/B 账号及已有服务器业务没有升级。本轮独立部署为 `synthetic-r2-local`，HTTPS 入口 `https://127.0.0.1:19444`，私有 Control 端口 `14096`，使用两个独立合成账号、六个实际 Agent/Gateway/Relay 容器。

应用仍使用单 Control、单 Windows 宿主 Worker 和 SQLite。数据库 schema **4**、配置 **3**、Worker/Runtime 协议 **2**；数据库迁移、配置兼容、内部协议分别校验。Agent 基于 OpenCode **1.18.30**。Python 为 **3.12.14**，SQLite 为 **3.53.1**，真实 SQLite 临时库启用 WAL。机器 Docker Desktop 实际可用内存约 15.34 GiB；本轮不模拟或验收 16 CPU / 32 GiB 服务器容量。

## 2. 已交付的主要修改

- 完整 v4 结构、迁移身份及结构指纹；desired/applied 分离；领取时冻结加密配置快照。
- 持久化顺序、busy defer、执行租约、阶段确认、操作回执、HTTP 请求幂等；安全停止优先及未确认执行责任保留。
- Gateway 原子准入、原生 Agent pending-start/执行活动记录、文件/解析/插件测试及 Relay 活动统计。
- 独立安全许可与撤权路径；许可过期关闭并锁定，续租不能单独重新开放，恢复必须核对当前启动身份、版本、权限与代次。
- 有限批次状态核对、维护冻结、完整证据释放容量、真实版本与脱敏展示联动。
- 前端待生效/排空/更新/恢复状态，超级管理员恢复入口，Python 幂等请求支持与 OpenAPI 更新。
- config v1/v2 兼容读取、config v3 参数验证、成套镜像门禁、备份工具、Windows 操作说明及保留的后续验收工具。

源码提交分组：`4492d639f`（Control/v4），`d3abfcfdd`（Gateway/Relay/Agent），`67484b8d5`（Worker/部署），`a662befc9`（前端/Python）。最终测试脚本及交付记录通过后续本地提交收齐；镜像归档的精确源码 SHA 以随包 `release-manifest.json` 为准。

## 3. Windows 自动化回归

| 范围 | 结果 | 实际边界 |
| --- | --- | --- |
| Control 全量 `tests` | 262 passed | 真实临时 SQLite、认证、三角色、幂等、快照、迁移、调度、维护、安全许可及既有功能回归 |
| Gateway 全量 | 86 passed，4 skipped | 其中 3 项仅适用 Linux，1 项因 Windows 缺少符号链接权限跳过；包括真实 Store + Control 的 ASGI 双跳恢复 |
| Windows 部署工具全量 | 176 passed，2 skipped，163 subtests passed | 配置、Worker、宿主回执、网络归属、备份/包清单等；不将模拟 Docker 当作实际故障演练 |
| 前端 | 50 passed，2147 assertions | 类型检查及构建通过；请求合并、会话切换、业务状态和客户端回归 |
| 原生 Agent 定向回归 | 27 passed | managed activity 与 HttpApi 会话路径；类型检查通过 |

上述计数分别属于各套测试，不把局部重复执行相加。Control 与 Gateway 存在现有 FastAPI/Starlette 弃用警告，不影响本轮结果。临时目录位于对应包内 `.pytest-r2-*`，不会进入 Git 或镜像。交付清单补入本轮文档后，必要打包回归为 7 passed、2 subtests passed。

复现应从各包目录运行，使用仓库现有 Python 虚拟环境与固定 Bun；例如 Control：`python -m pytest tests -q --basetemp=.pytest-r2-new-local`，Gateway：`python -m pytest gateway/tests -q --basetemp=.pytest-r2-new-gateway`。每次选择新的测试临时目录，不能指向运行数据目录。

## 4. 实际本机功能与修复证据

顺序脚本为 [r2-local-smoke.py](../r2-local-smoke.py)，最终记录为 [r2-local-smoke-verified.json](r2-local-smoke-verified.json)。外部模型使用受控 OpenAI 兼容合成服务，Agent/Gateway/Relay 均为真实运行组件；没有调用付费模型或业务数据接口。

最终脚本核对：两个环境已验证并开放；管理员不分配 Agent 且不能访问超管维护；A/B 各一次短回答；TXT 上传与解析；跨账号会话及下载被拒绝；A 回答期间保存个人 Skill 后，必须先观察到任务的持久 `defer_count > 0`，才能释放合成回答并检查新版本生效；desired 不因补排再次增加，B 保持可用；更新后文件与历史仍在。最终记录为 **passed，51.063 秒，persisted_defer_count=1**。整个流程仅一路活动生成，不是并发测试。两个账号的六个容器均实际核对为最终 Agent/Gateway 镜像且健康。

较早的 `r2-local-smoke-01.json` 和 `r2-local-smoke-final.json` 只观察待生效版本，没有严格证明 Worker 实际提交 defer。它们保留为中间证据，不作为 busy/defer 通过依据；最终脚本补入持久回执断言后重测。不能用“保存后暂未更新”替代真实排空证明。

本机初检发现 Control 被 Compose 替换后丢失动态管理网络，页面返回 503。修复后 `platform-manage.py up` 在返回 started 前核验并恢复固定归属的管理网络，实际返回 `registered=2 / connected=2`，两个账号随后恢复 ready/open。该修复有 8 项 Windows 模拟检查；实际容器恢复只证明本次事件通过。

短测 Worker 日志存在可恢复的 Control `RemoteProtocolError` 与周期核对被新状态取代的记录，Worker 按既有重试/重新核对路径继续，未导致最终顺序业务检查失败。短测不提供长期重试率或性能承诺，不能据此填写零异常或长期稳定性通过。收尾确认 Worker 空闲后，已将该独立执行器切换为 `platform.ps1 worker-start` 的隐藏、可跟踪进程方式。

Windows Chrome 普通用户 B 首页的 1366 像素复查通过：历史与合成模型加载，输入框可见且可输入，无横向溢出，控制台 0 error/0 warning，捕获的请求没有 503。截图和仅含角色/宽度/错误标记的 metadata 保存在 Git 忽略的 `deploy/peixian/output/playwright/`；此前失败证据以 before-fix 保留。未执行 390/1920 宽度及完整三角色浏览器遍历。

## 5. V1.2 用例关联及证据层级

以下是相关源码用例的关联，不是整组实机验收通过声明。

| V1.2 编号 | 本轮证据 | 尚缺的实机证据 |
| --- | --- | --- |
| DB-01～11、AS-03～05 | Store/事务、v4 迁移、角色、异步与幂等回归 | 合成旧部署的成套升级/备份恢复演练 |
| WK-01～14 | `test_r2_orchestration.py`、`test_orchestration_worker.py` 的确定性调度、defer/回执/租约/冻结用例 | A/B/C 公平性 10 轮、真实宿主各阶段崩溃及丢响应 |
| RT-01～05、RT-14 | 状态/版本、原生受理窗口、Gate 活动、未知拒绝及脱敏回归；本机一次真实 defer/应用 | 每类上传/下载/解析/权限等待/插件测试单独长活动演练 |
| RT-06～13 | 安全意图、许可锁闭、boot fencing、冻结快照及恢复用例；实际 Control 重建后的网络修复 | 在途模型/插件撤权五秒门槛、每阶段崩溃、旧配置撤权回滚完整矩阵 |
| SE-01～08、SE-13 | 既有 SSE 与身份撤销回归纳入 Control；普通用户浏览器基础加载通过 | 实际双端撤销计时、长期断线/重连与泄漏观测 |
| 第 27/31 章与 PR-6 | 工具、配置、诊断及本机记录交付 | 性能分位、4 小时、OOM/重启/泄漏统计、完整恢复演练均未执行 |

AccountEventHub（SE-09～11）、Runtime Pool、等待队列、自动休眠、PostgreSQL、Redis、多 Control、多节点仍不在本轮实现范围。

## 6. 本地交付与后续边界

操作见 [R2_LOCAL_OPERATIONS.md](../R2_LOCAL_OPERATIONS.md)，内部协议与迁移说明见 [schema_v4_protocol.md](../../../services/peixian-control/docs/schema_v4_protocol.md)，后续工具边界见 [R2_ACCEPTANCE.md](../R2_ACCEPTANCE.md)。普通本机入口使用独立自签证书；测试 SDK 使用本机 CA 文件校验，不能据此声称生产证书部署通过。

本地交付包由 `platform-package.py` 按允许清单生成，包含提交源码、配套镜像、离线 Python wheels、操作文档和校验清单。其目标镜像为 linux/amd64，但本轮只在 Windows Docker Desktop 运行应用；导出镜像或收集 Linux wheels 不等于执行 Linux 主机验收。包不含账号、密钥、数据库、工作区数据或私人备份。

| 组件 | 本机最终镜像 ID |
| --- | --- |
| Control | `sha256:984d9966b1ed59cf5f6cdafa1558133741ec66671af6eddcea094ce86a165f81` |
| Gateway / Relay | `sha256:daf6e49d86433f8e85acb9ba9e11080f5d9b96d393f2141bdcfff67e963b2f7e` |
| Agent | `sha256:c267a0ec9213ae7ac0ce38ffcb787e2d8c52554cc797a080ff19578b23ca62cd` |
| HTTPS Proxy | `sha256:30f1c0d78e0ad60901648be663a710bdadf19e4c10ac6782c235200619158284` |

没有执行：Linux 专项/目标服务器、50 路并发、3→4 账号故障矩阵、4 小时持续负载、真实 DeepSeek/vLLM/业务接口、完整备份恢复、原 A/B 升级和正式切换。50 并发结论为 **尚未执行，本轮不作容量声明**；PR-4/PR-5 可供本机初步试用，PR-6 完整发布验收仍待上述证据。全部改动仅保存本地提交，没有自动推送远端。
