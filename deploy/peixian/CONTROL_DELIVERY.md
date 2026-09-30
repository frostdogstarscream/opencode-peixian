# Control 前后端统一构建与发布

本流程将 SolidJS/Vite 页面和 FastAPI 控制 API 放入同一个 Control 镜像。浏览器访问同源页面和 `/api/console/v1`，最终镜像运行一个 Python 服务。账号 Agent、Gateway、Relay 与宿主 Worker 继续独立运行。

## 客制化开发

前端位于 `packages/peixian-console`，控制后端位于 `services/peixian-control`。Vite 开发服务使用 5178，将 `/api` 代理到 14090。修改页面时保留服务端权限校验和当前 CSRF、Cookie、SSE 调用方式。

正式 Docker 构建自动使用 Bun 1.3.14 及包级 `bun.lock`，执行 `bun typecheck` 和 `bun run build`，包括前端引用的共享 UI 样式。无需先在宿主机生成 `dist`；宿主机旧 `dist`、`node_modules`、运行数据不会进入构建上下文。最终运行镜像保留固定 Python 基础镜像、后端和已生成静态资源，以 10001:10001 运行。

依赖变更必须维护前端包级锁文件；在独立包目录环境中更新锁文件并检查差异，不得将整个上游 monorepo 的依赖装入前端构建阶段。构建阶段需要能访问依赖仓库，预构建镜像的页面加载不依赖公网。基础镜像已锁定版本和摘要，仍不承诺依赖仓库可永久访问或镜像逐字节可重建。

## 构建命令

从仓库根目录执行，Python 必须为 3.12；构建工具本身仅使用标准库。用自己的项目解释器替换下列路径。

```powershell
$python = '.\services\peixian-control\.venv\Scripts\python.exe'

# 当前工作区开发构建，不能作为正式镜像发布。
& $python deploy/peixian/control-build.py dev --tag agent-platform-control:delivery-dev

# 已检查并提交源码后，从固定提交构建；可以指定完整 SHA 或本地已存在的引用。
$commit = git rev-parse HEAD
& $python deploy/peixian/control-build.py release --commit $commit --output deploy/peixian/dist/control-build.json

# 从实际镜像提取并核验版本、首页及全部静态资源。
& $python deploy/peixian/control-build.py inspect --image "agent-platform-control:delivery-$($commit.Substring(0,12))"

# 导出仅 Control 镜像包。目标目录必须不存在。
& $python deploy/peixian/control-build.py export --image "agent-platform-control:delivery-$($commit.Substring(0,12))" --commit $commit --destination deploy/peixian/dist/control-release
```

Windows 旧入口可使用 `console.ps1 build-control -BuildMode release -Commit <SHA>`，只重建 Control；`build` 继续构建原账号镜像再调用统一 Control 构建入口。两者默认 `BuildMode=dev`，只有明确指定 release 与提交才产生正式候选。

构建成功不会启动或升级任何服务。已有镜像标签在构建失败时可能仍指向旧镜像，不得将“标签存在”视为本次构建成功；以命令成功及生成的镜像 ID、构建清单为准。

## 版本与资源保护

- release 从 `git archive` 的指定提交读取白名单源码，不复制当前未提交改动。构建不包含 `.git`、密钥、数据库或用户卷。
- 每个镜像包含 `/app/build-manifest.json`，记录 mode、source_commit、input_digest、build_id、frontend_digest、固定基础镜像及各静态文件摘要。
- dev 的 source_commit 为 null，明确标记为开发镜像；工作区与某提交相似不构成正式来源证明。
- 启动默认 `CONSOLE_REQUIRE_STATIC=1`。缺失首页、清单、资源、存在链接或文件摘要不匹配时，在初始化控制库前拒绝启动。
- 后端单独开发使用 `CONSOLE_REQUIRE_STATIC=0`，可以没有前端清单；若提供了清单，仍需有效。单独开发不得发布为生产镜像。
- `/health` 保留原字段，镜像模式增加 `build`，仅返回 mode、source_commit、build_id、frontend_digest。构建身份不是账号环境版本或模型验收结果。
- `index.html` 不长期缓存；经清单校验且带内容摘要的 assets 使用一年 immutable 缓存。不存在的资源返回 404；API 和内部路径不会回退为 HTML。受保护动态 API 保留先鉴权再判定路径的既有规则。

## 导入、升级与回退

仅 Control 导出包包含 `control-image.tar`、`release-manifest.json` 和 `SHA256SUMS`，不包含账号运行镜像、用户数据或密钥，不应称为完整平台离线部署包。归档按不可变镜像 ID 导出，导入后按清单重新打标签：

```powershell
docker load --input control-image.tar
# 从清单读取 image_id 和 requested_tag / image 后，显式打所需部署标签。
docker tag <image_id> <部署配置中的Control标签>
```

执行升级前使用现有兼容检查与备份流程，暂停受影响写入并确认 Worker 无宿主操作；不要通过新脚本跳过数据库或内部协议检查。普通停止和重建保留持久卷。回退只使用与现有数据库、配置和内部协议兼容的 Control 镜像；页面换回旧版不等于数据库可以降级。

完整平台包继续使用 `platform-package.py` 和 `release-check.py`。新版 Control 必须为 release、源码 SHA 与归档提交相同、实际候选 ID 与镜像归档一致。随包部署源码的 `source_matches_commit=false` 仍阻止正式发布。历史镜像兼容检查保留，但历史包不能因此声称拥有本轮资源清单验证。

## 验收边界

本轮验收使用独立本机部署、回环端口和合成账号，最多两个测试用户环境，不升级原账号。页面、登录、三角色、会话、文件、技能、插件、事件订阅、重启持久化与版本对应需分别记录。真实模型、大规模并发、Linux 主机与真实内网服务不由本轮结果推断为通过。
