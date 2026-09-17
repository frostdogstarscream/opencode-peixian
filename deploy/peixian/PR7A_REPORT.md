# PR-7A 源码与本机自动化初检记录

日期：2026-09-17。依据《沛县公安智能体_PR7按需Runtime与容量池开发实施计划_V1.0_2a697f0.md》。本轮只实施 PR-7A；容量等待与自动休眠开关仍为 false。

## 版本与结论

- 基线：`2a697f02b286ea89d77e3e8f231b07a13b05be4e`。
- 分支：`codex/pr7a-runtime-on-demand`。
- 契约检查点：`18f6e49ca`。
- 功能提交：`d1bc7ffeb3c5df21bec1f1c8c04fc32a8f537eee`。
- 最终可执行源码与工具提交：`fe7365656cd2fde01782ba91b042534c44c75640`；后续文档提交不改变被测实现。
- 源码及自动化初检通过；PR-7A 完整集成退出条件尚未通过验收，不能宣称真实容器按需启停或生产发布已完成。

## 已实现

1. 显式配置 v4 启用 on_demand；旧配置保持 eager。完整 schema v5 独立迁移，历史 v4 迁移文件未修改。真实已有数据库需要离线迁移许可，拒绝模式与结构不一致。
2. 注册普通账号只建立元数据。用户显式启动原子申请名额，容量满明确拒绝；启动去重、停止状态版本及幂等重放均受服务端约束。无队列、无自动休眠、无自动重发问题。
3. 管理员人工暂停与账号停用分别保存。重新启用账号不自动启动，不解除人工禁止；安全修复保留名额责任，普通排空保留存量活动所需出口。
4. Worker 能力握手、全局宿主资源清单、责任集核对和过期证据拒绝。实际资源与账面不符时保护容量，未执行过的账号不进入逐账号高频运行检查。
5. 用户状态栏与显式启停按钮、Python 客户端和 OpenAPI、配置示例、备份元数据与包清单适配。未落地账号不伪造卷；丢失已落地资源不按正常元数据账号处理。
6. 新候选不能套用旧发布用例表：发布检查增加 PR7A-2slot-5account、PR7A-v5-restore、PR7A-component-compatibility，并检查新模式配置和能力声明。原 PR6 证据门槛仍保留；添加用例名称本身不等于通过，结果还须绑定包内证据与源码身份。

## 已执行测试

| 测试 | 结果 | 证据范围 |
|---|---|---|
| Control 全量 pytest | 325 passed，2 条依赖弃用警告 | 临时 SQLite、ASGI、确定性交错与替身 |
| 部署工具全量 pytest | 226 passed，2 skipped，163 subtests passed | 临时文件、合成数据库、宿主命令替身 |
| 前端 Bun 测试 | 52 passed，0 failed，2154 expect 调用 | 自动化逻辑测试 |
| 前端 typecheck / build | 通过 | 类型检查与静态构建，不等于浏览器验收 |
| git diff --check | 通过 | 差异格式检查 |

Control 命令在 `services/peixian-control` 执行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q --tb=short --basetemp=.pytest-pr7a-release
```

部署命令在 `deploy/peixian` 执行：

```powershell
..\..\services\peixian-control\.venv\Scripts\python.exe -m pytest tests -q --tb=short --basetemp=.pytest-r4-pr7a-release-final
```

前端从 `packages/peixian-console` 使用仓库本机 Bun 1.3.14 分别执行 `bun test`、`bun run typecheck`、`bun run build`。Control 与前端结果来自功能提交对应的实现；随后发布门槛工具改动由最终部署全量测试覆盖。

新增 Control 专项覆盖：5 个合成账号与 2 名额的事务竞争、重复启动、过期停止、HTTP 所有权、幂等重放、Worker 能力拒绝、人工暂停、账号恢复、首次失败责任保留、安全修复名额、清单过期／漂移，以及未启动账号停止无副作用。这里的“5 账号、2 名额”是数据库与协议测试，不是 5 账号真实容器集成证据。

## 未执行与发布限制

| 项目 | 状态 |
|---|---|
| 独立部署：5 账号、2 名额、2 套真实 Agent/Gateway/Relay，停止后会话文件保留 | not_run |
| 真实已有数据库离线升级及中断恢复 | not_run |
| 成套用户卷、配置、密钥备份与空命名空间恢复 | not_run |
| 浏览器实际启停、中文输入与三种宽度视觉验收 | not_run |
| 匹配镜像构建、运行身份核验与完整离线镜像包 | not_run |
| Linux、服务器、50 并发与持续负载 | not_run |
| 真实付费模型请求 | not_run |

本轮没有启动、停止、升级既有服务，没有迁移现有账号库、卷及 A/B 环境；没有推送远端。示例中的 pr7a-candidate 标签尚无本轮构建证明，不能当作可直接部署的交付镜像。原有 PR6 发布阻断报告保留，未补记历史通过。

后续先在获准的独立本机部署完成 2 名额／5 账号真实集成与匹配镜像证据，再判断 PR-7A 退出；PR-7B/7C 不因本报告自动获得启用资格。
