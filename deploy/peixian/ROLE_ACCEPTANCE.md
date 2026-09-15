# 三角色改造验收记录

日期：2026-09-15。范围：沛县控制台基础权限批次；Windows Docker Desktop 本机。

## 1. 交付范围与结论

本次已实现 `super_admin / admin / user` 三角色、前后端权限分离、旧账号一次性迁移、兼容性启动检查及本机部署。测试与实际访问检查通过后保存独立本地提交，不自动推送远端。

- 工作分支：`codex/peixian-p0-hardening`，基于 `codex/peixian-console` 的 `2f87198cc963b8f4253b94353c7306d5a2485c69`。
- 控制台入口：`http://127.0.0.1:14090`。健康接口 `/health` 返回 `status=ok`、`version=1.1.0`、`schema_version=2`。
- 控制镜像：`peixian-control:console-r2-roles`。
- 本机实际运行镜像 ID：`sha256:6739f69e584579766f95c9c06c47c145bab3a278b6e7898b7a6165b09d155420`。这是本机 Docker 镜像标识，未宣称已推送镜像仓库。
- Agent 和 Gateway 沿用已有镜像；没有重新编译 OpenCode 内核或修改用户会话数据库格式。
- 已核对运行容器内全部 `control/*.py` 与本地源码一致（只规范化换行后比较 SHA-256），实际 HTTP 提供的 JS/CSS 与本次前端构建字节摘要一致。

原需求 DOCX 和正式方案 v1.0 保留。新增根目录正式方案 v1.1 与仓库内 [FORMAL_PLAN_v1.1.md](FORMAL_PLAN_v1.1.md) 内容一致；同步 [三角色与迁移说明](ROLES.md)、[使用手册](USER_GUIDE.md)、[离线 HTML 手册](USER_GUIDE.html) 及 OpenAPI。

## 2. 已完成行为

| 边界 | 实现与验证结果 |
|---|---|
| 超级管理员 | 管理普通用户及管理员、模型、平台插件、模板和环境任务；不能通过管理角色取得他人私有业务资源 |
| 管理员 | 管理全部普通用户、模型及脱敏管理操作记录；没有同级账号、超级管理员、插件治理、模板或独立环境维护权限 |
| 普通用户 | 继续使用自己的会话、文件、个人 Skill 和已获授权插件；无管理权限 |
| 管理账号环境 | 创建管理员不创建 runtime/job，不占用普通用户运行名额 |
| 混合请求 | 管理员夹带 `role`、`plugin_ids` 或未知字段时整笔拒绝；单独修改模型授权不清空插件授权 |
| 账号恢复 | 从停用转启用时原子预留名额并排队恢复；暂停在途或容量不足返回 409，账号保持停用；手动暂停但仍启用的账号不因编辑自动恢复 |
| 审计 | 记录操作者、当时角色、固定动作、目标、时间及成功/拒绝/失败结果；公开响应不包含请求正文、凭据或 Worker 负载 |
| 前端加载 | 按服务端 capabilities 加载菜单和资源，管理页面不无条件请求插件、模板、任务或普通用户事件流 |

账号名与角色分开：原有用户名 `admin` 保留，现为 `super_admin`。其密码未重置；升级撤销旧认证，需要重新登录。后来创建的受限管理员不会被重复启动自动提升。

## 3. 自动化测试

| 层次 | 结果 | 覆盖 |
|---|---:|---|
| 控制后端完整 pytest | 114 通过 | 原功能回归、三角色、迁移/事务、账号恢复、所有权、认证/SSE 撤销、OpenAPI 等 |
| 部署脚本 unittest | 59 通过 | 既有部署检查、schema 兼容、备份及 WAL 读取、验收清理和失败报告 |
| 前端权限测试 | 13 通过，34 个断言 | capability 菜单、角色表单及允许提交字段 |
| 实际 HTTP 验收 | 118 项检查通过，0 失败 | 真实控制台/宿主 Worker/Docker 环境中的开通、暂停恢复、跨权限调用、授权分离、令牌和密码重置 |
| 前端构建与类型 | 通过 | 包目录 `bun typecheck`、`bun run build` |
| OpenAPI | 9 项合同测试通过，已包含在后端总数中 | 导出文件与当前服务定义一致；OpenAPI 3.1.0，57 条路径，62 个 Schema |

自动化测试合计为 186 个测试；118 项实际 HTTP 检查单列，不与测试数量混算。定向重跑不重复计数。后端仅出现既有依赖弃用警告。

本机实际验收只创建合成账号、会话、Skill、插件和模型连接。合成模型指向本机不可用测试端口，用于模型配置和失败响应验证，不执行模型推理。密码重置只操作本轮创建的测试账号。

## 4. 实际升级与数据保持

1. 记录旧控制库并停止空闲 Worker 和控制服务；普通用户实例数据不改动。
2. `console-guard.py backup` 在无运行消费者时归档控制卷，核对归档及源文件摘要；迁移前检查要求备份与当前状态匹配。
3. 实际控制库从 schema 0 升到 2，原角色统计从 `admin=1,user=5` 变为 `super_admin=1,user=5`。
4. 迁移前后九类数据摘要全部匹配：账号、环境关联、授权、插件安装、个人 Skill、文件元数据、模型、模板、任务。账号摘要对明确迁移的角色及认证版本做规范化，其余字段（包括 ID 和密码哈希）参与比较。
5. 后续再次部署后，原最高权限账号仍为 `super_admin`；新增管理员仍为 `admin` 且没有环境。
6. 最终 A/B 各三个容器全部健康；角色验收账号全部停用，成功开通的合成环境已暂停，数据卷保留。

私密备份保存于 Git 忽略的 `.runtime/role-backups/20260915T100147Z-521163ac/`。本次归档 SHA-256：`0e225fe3255a2b9918246c71d2982fce9eaded856ef41951f1f82f0f780133cd`。

该备份只覆盖控制卷，不是用户工作区和密钥的全平台备份。验收没有恢复覆盖现有控制库，没有删除用户容器卷或复制他人业务正文到报告。

## 5. 浏览器检查

使用三个独立 Chrome 浏览器会话分别检查超级管理员、管理员和合成普通用户，未改动用户已打开的浏览器会话。

- 三类页面分别检查 1366、1920、390 像素宽度，共 9 组；文档宽度与视口一致，未出现整页横向溢出。窄屏账号表格允许在表格内部横向滚动。
- 超级管理员有完整管理入口；管理员仅有用户管理、模型管理、操作记录；普通用户直接显示聊天输入框和个人功能入口。
- 管理员创建账号表单没有角色选择或插件授权，保留模型授权；Tab 焦点在原生对话框内，Escape 可以关闭。
- 管理员、普通用户登录后禁用 HTTP 缓存并阻断非本机来源重新加载，页面正常显示；该检查未产生 JS 异常或 HTTP 错误，也未请求受限管理资源。管理员不订阅普通用户业务事件。
- 合成普通用户的模型在验收清理时已禁用，页面正确显示“暂无可用模型”，发送按钮禁用；没有把该页面显示当作推理成功。

本地截图留在 Git 忽略的 `output/playwright/roles-{super,admin,user}-{1366,1920,390}.png`。实际 HTTP、迁移及最终状态的脱敏机器记录分别留在 `output/role-acceptance.json`、`output/role-migration.json`、`output/role-final-state.json`。

## 6. 回退保护与运行环境处理

- 已实际执行 `console-guard.py check --image peixian-control:console-r1`：升级库被旧双角色镜像拒绝，返回 `image_database_schema_incompatible`。
- Windows `up/start` 校验 schema 后使用同一次检查返回的不可变镜像 ID 启动，防止可变标签被替换；Linux 文档采用相同方式。
- 兼容保护覆盖提供的脚本入口；具有宿主 Docker 管理权的人仍能手工绕过，不声称它限制宿主管理员。
- 保留旧镜像和升级备份；本次只验证拒绝不兼容启动，没有执行备份恢复演练或自动降级。

本机 Docker 引擎最初不能启动，检查后保留并重建了仅包含失效 IPC 文件的目录，未重置 Docker 数据。首次合成开通遇到默认地址池耗尽；保存定义后只移除了四个已确认无容器连接的历史冷启动测试网络，没有删除任何数据卷。随后实际 HTTP 验收完整通过。失败合成任务及可识别资源记录保留，其账号已停用。

## 7. 尚未完成及后续边界

- 部门/公共 Skill 的完整审核、发布、下架及范围授权仍是正式计划批次 D；本次落实现有模板管理仅超级管理员可用，没有以模板改名替代完整治理。
- 部门组织、业务数据范围授权及后续正式业务功能不包含在此次角色增补中。
- 本轮未调用真实 DeepSeek 模型、未联调内网 vLLM、未执行真实业务数据插件、Linux 实机部署或备份恢复。
- 已同步源码、测试、OpenAPI、迁移说明及本地部署；没有推送 GitHub、发布镜像或部署真实内网服务器。

## 8. 复核命令

以下为本项目隔离依赖环境中的命令，测试应在所属目录执行。实际 HTTP 脚本会创建并停用合成账号，需要空闲运行名额，不能作为无副作用健康探针反复运行。

```powershell
Set-Location -LiteralPath 'D:\Code\PeiXianDB\opencode\services\peixian-control'
.\.venv\Scripts\python.exe -m pytest -q

Set-Location -LiteralPath 'D:\Code\PeiXianDB\opencode\deploy\peixian'
..\..\services\peixian-control\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_console_*.py'
..\..\services\peixian-control\.venv\Scripts\python.exe console-guard.py check
# 仅在需要重新执行有副作用的合成验收时：
..\..\services\peixian-control\.venv\Scripts\python.exe console-role-acceptance.py --execute

Set-Location -LiteralPath 'D:\Code\PeiXianDB\opencode\packages\peixian-console'
& '..\..\deploy\peixian\.runtime\bun-1.3.14\bun-windows-x64\bun.exe' typecheck
& '..\..\deploy\peixian\.runtime\bun-1.3.14\bun-windows-x64\bun.exe' test tests/access.test.ts
& '..\..\deploy\peixian\.runtime\bun-1.3.14\bun-windows-x64\bun.exe' run build
```
