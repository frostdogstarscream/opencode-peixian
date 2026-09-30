# 单 Control 容器构建与发布本机验收记录

验收日期：2026-09-30。范围：Windows Docker Desktop 上的独立合成部署，目标镜像为 Linux amd64。

## 结论与版本

本轮计划已实现并通过本机验收。从固定 Git 提交生成的正式 Control 镜像包含 SolidJS/Vite 页面及 FastAPI API，运行页面、后端、镜像标签、镜像内构建清单、`/health` 和导出归档已对应同一候选版本。未推送远端，未替换原账号环境，原工作区未提交的合成资料插件改动仍保留。

| 项目 | 验收值 |
| --- | --- |
| 分支 | `codex/control-delivery` |
| 基线 | `ea36aa8ec39bc319b66596f7774537891d8f0d97` |
| 实现及镜像源码提交 | `cb983294d7c08557c59a3d4bd8d6793a39c65e4d` |
| 正式候选标签 | `agent-platform-control:delivery-cb983294d7c0` |
| 构建模式 | `release` |
| build_id | `release-db19b06d2b1c47f0e50e6c2d` |
| frontend_digest | `f36e0ca8ed6f4633cd3a0ed6c8291f5620e0347fe196a785698680c5a63f7e0e` |
| Docker image ID / OCI index digest | `sha256:a28ec2657aa1302170aaed6c547415bea1f8632a5a03cadc9f6a8eff4c844984` |
| OCI amd64 manifest digest | `sha256:54f5b33a9a861dda938e9cb81b06bf8ab9cd3f6df706b5c453cfc9ac98893414` |
| OCI config digest | `sha256:621eedd9926679142f7c058cacdb0a540c564ee729b063861708a45100187e1c` |
| 数据库 / 配置 / 内部协议 | schema 5 / config 4 / protocol 2 |
| 运行用户 | `10001:10001` |

上述三种 OCI 摘要表示不同对象。导出归档已逐层校验 index → amd64 manifest → config 的原始字节摘要，并核对 config 内的源码标签。Docker Desktop 使用 OCI index 作为本机 image ID；不能把它当作 config digest。

同源码的 Windows 入口复建产生了另一个 BuildKit 证明对象，因此 OCI index ID 不同，运行 config、前端摘要、源码提交和 build_id 相同。该入口验证镜像没有替换本表候选或交付归档。

后续验收文档提交仅保存报告和截图。交付镜像仍明确指向上表实现提交，不将后续分支 HEAD 标记为该镜像源码。

## 实现内容

- Docker 多阶段构建使用固定摘要的 Bun 1.3.14 与 Python 3.12。前端冻结包级 `bun.lock`，执行 `bun typecheck` 和 Vite 构建；最终镜像只复制后端、共享模块和生成的静态资源。
- `control-build.py` 提供 dev、release、inspect、export。release 从指定提交的 Git archive 读取白名单输入，dev 不声明源码提交；两个模式均不读取宿主 dist 或依赖目录。
- 生产镜像启动先验证首页、资源清单、文件摘要和引用完整性；失败发生在数据库及后台资源初始化之前。后端开发模式可显式关闭静态要求。
- HTML 使用 no-cache；已核验的 Vite 摘要资源使用一年 immutable 缓存。未知资源、API 和内部路径不会回退为前端首页。
- `/health` 增加可选 build 信息，OpenAPI 已同步。发布记录从实际候选镜像读取资源，正式交付检查拒绝开发模式、错误源码和不匹配的镜像身份。
- Windows `console.ps1 build-control` 已实际调用统一入口完成固定提交构建，无需重建账号 Agent/Gateway 镜像。

## 独立环境与验证结果

部署标识为 `synthetic-control-delivery`，HTTPS 回环端口 19461，Control 回环端口 14111。最多两个合成普通用户环境，另有一个超级管理员和一个管理员；管理账号没有 Agent 环境。沿用匹配的 pr7c Agent/Gateway 与既有 Proxy 镜像。

| 验收项 | 结果与证据 |
| --- | --- |
| 全新构建上下文 | 通过；白名单临时上下文不含宿主 dist、node_modules、Git 元数据、测试输出或运行数据 |
| 构建失败保护 | 类型错误、冻结锁文件不一致、Vite 配置异常均使真实 Docker 构建失败；均无成功候选 JSON 或新镜像标签 |
| 开发镜像发布拒绝 | 开发镜像导出被拒绝，未创建目标目录；正式包门槛对错误模式、源码及镜像 ID 的负向测试通过 |
| 镜像内容 | 普通用户运行；`/app` 为 control、shared、static、requirements.lock、build-manifest.json；无 Bun、Node、npm 或宿主依赖目录 |
| 启动保护 | 正常镜像可启动；只读挂载缺首页、缺 JS 或被修改首页时拒绝启动 |
| 后端独立开发 | 在断网、只读镜像中使用临时合成 Store 和真实 lifespan，关闭静态要求后 API 与 health 正常，无前端 build 字段 |
| 页面与缓存 | 禁用浏览器缓存后 JS/CSS 均成功加载；首页 no-cache；资源 immutable；条件请求 304；HTTP 字节摘要与清单相同 |
| SPA 与 404 | 无扩展名前端路径回退正常；资源及未知 API 404；内部路径不返回前端首页 |
| 三角色权限 | 三角色浏览器登录、菜单和刷新正常；普通用户管理接口被拒绝；管理员不能访问插件发布和用户业务接口 |
| 会话和文件 | 两个合成用户均可创建、列出会话并上传、提取中文文本文件 |
| Skill 与插件 | 两用户均可创建个人 Skill、配置已授权合成插件；浏览器文件、技能及插件页面与 API 数据一致 |
| 认证与事件 | Secure、HttpOnly、SameSite=Strict Cookie；缺 CSRF 写入被拒；令牌可访问且撤销后 401；真实 SSE 收到变更；退出后旧订阅结束且旧凭据 401 |
| Control 重建 | 备份验证后替换测试 Control 容器，原控制卷、两用户的六个运行容器和业务卷保留，管理网络重连，Worker 重检后数据读取通过 |
| 兼容镜像切换 | 切至既有 schema 5/config 4/protocol 2 的 Control 镜像，再切回正式候选；每次备份校验、网络恢复和账号/会话/文件/技能/插件读取均通过 |
| 版本对应 | 切回候选后再次核验 health、静态摘要、镜像标签、清单和导出 OCI 身份链，一致 |
| 展示回归 | 三角色分别检查 1366、1920、390 像素，无整页横向溢出；中文输入、Tab 键、移动导航、登录错误和技能表单错误可用 |
| 归档导入 | Docker load 成功，导入 image ID 与本表候选一致 |
| 清理 | 两个测试用户环境经停止 API 确认为 paused；本轮 Worker、Control、HTTPS 均已停止；无本轮运行容器，7 个持久卷保留 |

HTTPS Proxy 对 `/internal` 使用既有 Nginx 404 错误页面，FastAPI 直连返回 JSON 404。两者都不是前端 SPA 首页；不能把 Nginx 自身错误页面误记为 SPA 回退。

Control 重启会按既有规则关闭安全入口。验收等待 Worker 完成重检及 API 返回 `ready=true`，没有绕过安全门，也没有将 `status=ready` 单独当作可交互证明。

## 测试统计

| 范围 | 结果 |
| --- | --- |
| Control 后端包完整 pytest | 387 passed |
| 部署包完整 pytest | 269 passed，2 skipped，163 subtests passed |
| 前端 Bun 测试 | 55 pass，0 fail，2165 expect 调用 |
| 前端类型检查及 Vite 构建 | 独立包目录与正式 Docker 阶段均通过 |
| Windows 单独 Control 构建入口 | 通过 |

部署包两个跳过项要求 Windows 普通权限创建符号链接，本机无该权限。链接拒绝相关代码和其他测试已执行；不把这两个跳过项写成通过。后端仅出现现有 TestClient 兼容弃用提示，测试无失败。

## 交付与复验

机器可读记录见 [control-delivery-local.json](control-delivery-local.json)，截图见 [超级管理员 1366](control-delivery-screenshots/super_admin-1366.png)、[管理员 390](control-delivery-screenshots/admin-390.png)、[普通用户 1920](control-delivery-screenshots/user-1920.png)、[移动端插件页](control-delivery-screenshots/user-mobile-plugins.png)。共保存 13 张脱敏截图。

交付目录为 `deploy/peixian/dist/control-release-cb983294d7c0`：

- `control-image.tar`：69,843,456 字节，SHA256 `a1384b7dc90ee7e01ad8ae59cbe2ee83cb95d1978a3592724184ec83c82467f5`。
- `release-manifest.json`：实际候选镜像身份、构建清单和静态文件摘要。
- `control-source.tar.gz`：从实现提交直接归档的 Control 前后端源码、共享样式及部署白名单。保留源码来源 SHA，不包含 Git 数据库，也不替代完整仓库及其提交历史。
- 操作说明、脱敏验收记录及截图；最终 `SHA256SUMS` 覆盖交付目录所有文件。

这是仅 Control 运行镜像的交付，不包含 Agent/Gateway/Proxy 镜像、用户卷、数据库、TLS 私钥、测试账号密码或 Worker 密钥，也不是完整平台离线部署包。固定版本构建仍允许下载锁定依赖；未承诺完全离线或逐字节重建。

```powershell
# 从完整仓库的该提交构建。Python 3.12 构建工具只需要标准库。
$python = '.\services\peixian-control\.venv\Scripts\python.exe'
& $python deploy/peixian/control-build.py release --commit cb983294d7c08557c59a3d4bd8d6793a39c65e4d --output deploy/peixian/dist/new-control-build.json
& $python deploy/peixian/control-build.py inspect --image agent-platform-control:delivery-cb983294d7c0

# 校验交付文件后导入，依据清单打部署所需标签。
docker load --input control-image.tar
docker tag sha256:a28ec2657aa1302170aaed6c547415bea1f8632a5a03cadc9f6a8eff4c844984 agent-platform-control:delivery-cb983294d7c0
```

其他 Docker 后端可能用 config digest 表示导入 image ID，应以导入输出和对应源码标签核对身份后再打标签；本机已验证的 ID 属于本机 OCI index 对象。

## 已处理问题与验收边界

Docker Desktop 最初无法启动，按用户授权保留本地目录备份后恢复；未重置 Docker，也未清除现有镜像或业务数据。测试 Worker 首次在较深的测试数据路径发布失败，改用较短数据根目录后通过。本轮没有修改 Worker 的 Windows 长路径处理，实际部署仍应选择较短路径。

未执行真实或付费模型请求、大规模并发、Linux 主机压测、真实内网端点调用或完整平台离线包验收。前端中文文本输入、键盘交互已验证；实体中文输入法的操作体验不由自动浏览器测试推断。现有账号环境不属于本轮升级范围。
