# 沛县公安测试服务器项目共享上下文

更新时间：2026-09-18。本文只记录可共享的项目结构、接口和运维事实，不记录账号密码、令牌、模型密钥、业务接口凭据、证书私钥或真实业务数据。后续对话连接服务器前应先阅读本文，避免重复梳理或误操作旧环境。

## 1. 服务器与代码基线

- 服务器：`36.134.45.38:22`，登录用户 `root`；SSH 密钥由用户单独保管。
- 当前正式测试源码：`/root/PeiXianDB/frontend-alignment`。
- 当前分支：`frontend-alignment`。
- 本次盘点 HEAD：`630a0929d037812d43e418ae5539471d5e5c755e`，对应提交 `feat(console): connect personal capabilities and file workflows`。
- Git 远端：`origin=https://github.com/frostdogstarscream/opencode-peixian.git`；上游为 OpenCode 官方仓库。
- 部署根目录：`/srv/peixian-alignment-20260917`。
- 历史仓库 `/root/PeiXianDB/opencode` 不属于当前统一入口部署，不得在本任务中修改或用于构建。

服务器源码当前不是干净工作区，已有下列现网验收相关修改，后续工作必须保留：

```text
M  deploy/peixian/console-runtime.py
M  deploy/peixian/tests/test_console_runtime.py
?? deploy/peixian/UI_ALIGNMENT_LIVE.md
?? deploy/peixian/alignment-live-acceptance.py
?? deploy/peixian/evidence/ui-alignment-live-20260917.json
?? packages/peixian-console/tests/alignment-live-browser.mjs
```

不得执行 `git reset --hard`、覆盖这些文件或用本地旧分支整体替换服务器工作区。

## 2. 当前部署

- 外部入口：`https://36.134.45.38:19460/`，当前使用临时自签名证书。
- Control 仅监听服务器回环：`127.0.0.1:14099`。
- 部署标识：`peixian-alignment-20260917`。
- Control 容器：`peixian-alignment-20260917-console`。
- HTTPS 容器：`peixian-alignment-20260917-https`。
- 宿主 Worker：`peixian-alignment-worker.service`。
- 当前运行时镜像基于源码提交 `630a0929d` 构建：Agent 为 `peixian-opencode:alignment-630a0929d`，Gateway/Relay 为 `agent-platform-gateway:alignment-630a0929d`。
- 每个普通用户拥有独立的 Agent、Gateway、model-relay、内部网络、管理网络、出口网络和数据卷；管理员角色没有业务运行时。
- 运行时管理网络命名为 `px-<32位runtime-id>-management`，插件 Service Connection 的 HTTP 请求由账号 Gateway 发出。
- 原有 `pengcheng-platform-*` 服务属于另一套保留环境，不得重启、升级或复用其数据库与凭据。

部署目录职责：

| 路径 | 用途 |
|---|---|
| `/srv/peixian-alignment-20260917/platform.json` | 当前平台部署配置，权限 `0600` |
| `/srv/peixian-alignment-20260917/runtime` | Worker 状态、运行时生成配置和秘密文件 |
| `/srv/peixian-alignment-20260917/tls` | TLS 证书与私钥 |
| `/srv/peixian-alignment-20260917/private.json` | 当前验收账号私密信息，权限 `0600`，禁止输出或复制进仓库 |
| `/data/docker/volumes/peixian-alignment-20260917-control-data/_data` | Control 持久数据库和平台发布包数据卷 |

## 3. 系统组成与调用链

```text
浏览器 / Python 客户端
    ↓ HTTPS 19460
Nginx HTTPS 入口
    ↓
Control（身份、权限、目录、配置、审计、任务）
    ↓ 每账号 management 网络
Gateway（会话代理、文件、插件测试、Service Connection 出口）
    ↓ internal 网络
Agent / OpenCode 1.18.30
    ↓
model-relay（模型出口）
```

业务数据插件的目标链路：

```text
Agent → Skill → 数据域插件 → platform.connections.request
→ Gateway Service Connection → 沛县统一数据适配服务 → 公安旧接口
```

统一数据适配服务必须同时能被 Control 的连接测试和每个账号 Gateway 访问。不能把 `127.0.0.1` 配置为 Service Connection 的服务地址；`localhost` 在容器内只指向当前容器。

## 4. 前端与后端代码入口

前端位于 `packages/peixian-console`，技术栈为 SolidJS 1.9、Vite 7、TypeScript、`marked` 和 DOMPurify。主要入口：

- `src/App.tsx`：身份和页面路由总入口；
- `src/pages/Chat.tsx`：智能研判、会话、模型、文件、Skill 与插件能力；
- `src/pages/Admin.tsx`：用户、模型、审计等管理页面；
- `src/pages/Connections.tsx`：超级管理员 Service Connection；
- `src/pages/Skills.tsx`、`Plugins.tsx`：个人 Skill 与插件；
- `src/api.ts`、`types.ts`：Control API 客户端及类型；
- `src/styles.css`：当前沛县视觉实现。

后端位于 `services/peixian-control`：

- `control/app.py`：认证、会话、文件、公共入口；
- `control/administration.py`：用户、模型、插件发布和 Skill 模板；
- `control/catalog.py`：个人 Skill、个人插件安装与测试；
- `control/connections.py`：服务连接和插件版本连接绑定；
- `gateway/service_connections.py`：账号隔离的服务调用出口；
- `gateway/plugin_launch.py`、`plugin_test.py`：插件加载和测试；
- `deploy/peixian/console-runtime.py`、`console-worker.py`：账号运行时生成与宿主执行。

生产前端由 Control 同源提供，浏览器只访问 `/api/console/v1`，不直接连接 Agent 容器。

## 5. 插件与 Skill 生命周期

平台插件不是直接复制到 Agent 目录：

1. 开发端将 `manifest.json` 和 `entry.mjs` 放在 ZIP 根目录；
2. 超级管理员调用 `POST /api/console/v1/admin/plugins` 发布不可变版本；
3. 超级管理员创建 Service Connection；
4. 对每个插件具体版本调用 `PUT /admin/plugins/{id}/{version}/connections` 绑定声明的连接别名；
5. 超级管理员通过用户更新接口把插件 ID 加入普通用户现有 `plugin_ids`；
6. 普通用户调用 `PUT /plugins/{id}` 选择版本、配置并启用；
7. 等待 Runtime Apply 完成；
8. 普通用户调用 `POST /plugins/{id}/test` 验证账号 Gateway、插件代码与连接链路；
9. 新会话中实际出现工具调用才算模型验收通过。

Skill 与插件独立。个人 Skill 使用 `/skills` 创建；共享交付优先由超级管理员创建 `/admin/templates` 模板，再由普通用户调用 `/templates/{id}/copy` 复制。Skill 生效检查只确认文件已加载，不执行模型分析。

首期本地交付包括 5 个数据域插件、13 个工具和 5 个综合 Skill，源文件在：

```text
deploy/peixian/business-plugins
deploy/peixian/business-skills
services/peixian-data-adapter
```

本地生成的 ZIP 和完整发布目录位于 `deploy/peixian/dist`，该目录被 Git 忽略，需要通过打包脚本重新生成或单独传输。

## 6. 权限与安全边界

- 角色为 `super_admin`、`admin`、`user`。
- 只有超级管理员具有插件发布、插件连接绑定、插件授权、Service Connection 和 Skill 模板治理能力。
- 普通管理员只能管理普通用户、模型和脱敏审计，不能发布或授权插件。
- 普通用户只能管理自己的会话、文件、Skill、已授权插件配置与令牌。
- Cookie 写操作必须带 `X-CSRF-Token`；个人 Bearer Token 不使用 CSRF。
- 已发布的插件 ID + 版本不可覆盖；代码、清单、配置 Schema 或连接声明变化必须提升版本。
- 新版本不会继承旧版本连接绑定。
- Service Connection 凭据只写不读，插件不能设置任意目标 URL 或自定义请求头。
- 真实公安接口凭据只允许存在于适配服务或平台安全凭据存储，不进入插件 ZIP、Skill、Git、日志或共享文档。
- 不直接修改 Control SQLite 数据库，不把插件源代码或 ZIP 复制进账号容器/数据卷。

## 7. 当前验收状态与已知边界

截至服务器现有 `UI_ALIGNMENT_LIVE.md`：

- 两个普通账号环境、个人 Skill、样例插件、文件上传解析、跨账号隔离、真实 DeepSeek 工具调用、插件升级回退和停止恢复已完成小规模联调。
- 当前最大运行名额为 2；存在两个活跃普通用户运行时，另有历史管理网络残留，不能仅按网络数量判断当前账号数量。
- 当前 Windows 跨机 HTTPS 握手尚未验收通过；服务器内 HTTPS 验证成功不等于公网正式可用。
- 未完成 50 并发、持续负载、真实公安业务接口、真实内网 vLLM 或全量灾难恢复验收。
- 新数据插件当前只完成本地 Mock、包结构和容器验证，尚未导入本服务器。

## 8. 后续操作原则

1. 连接服务器后先核对分支、HEAD、`git status`、容器状态和 Worker 状态。
2. 阅读本文件及服务器 `deploy/peixian/UI_ALIGNMENT_LIVE.md`、`PLUGIN_DEVELOPER_GUIDE.md`。
3. 保留服务器已有未提交改动，不整体同步或强制检出本地工作区。
4. 新文件只放入独立目录；发布和授权必须走 `/api/console/v1`。
5. 导入前备份 Control 数据卷或使用项目既有备份流程；不只复制运行中的 SQLite 主文件。
6. 首次只授权一个专用普通测试账号，完成连接测试、插件测试、Runtime Apply 和实际工具调用后再扩大授权。
7. 缺少正式接口的数据域只允许 Mock 测试，不得标记为正式业务验收完成。
