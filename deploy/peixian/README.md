# OpenCode 独立客户机环境

> 默认部署为一期无模型基线。另有需要显式启用的 **DeepSeek V4.1 Flash 官方 API 测试配置**，操作和单独验收见 [DEEPSEEK.md](DEEPSEEK.md)。以下启动与离线交付步骤针对无模型基线；可选配置不改变原入口和登录密码。

无模型基线部署两个独立的 OpenCode Web/API 实例。固定官方 v1.18.30，使用普通用户容器运行；每实例有独立密码、HOME/XDG、工作区、临时目录和内部网络。每个实例另配一个专属 TCP 入口容器，共四个容器。

无模型基线不配置模型、数据插件、MCP 或业务 Skill。网页可以查看工作区和管理会话；基线没有模型回答是预期行为。可选 DeepSeek 配置的实际模型结果记录在单独证据中，两种模式都不代表真实 vLLM 或业务分析已经通过。

## 代码来源

- 独立仓库：https://github.com/frostdogstarscream/opencode-peixian
- 官方 upstream：https://github.com/anomalyco/opencode
- 源码基线：`v1.18.30` / `3104c1428ec91f809e5ab86631300de41eb6952e`
- 本地开发分支：`codex/peixian-server`
- 项目镜像：`peixian-opencode:1.18.30-r1`

这个仓库按用户确认的方案独立建立，GitHub 页面不显示 Fork 关系；官方历史通过基线分支保留。已有的 `opencode_moblie` 未被使用。目前仅官方基线已推送；部署修改的本地检查点以 `git log` 为准，推送需要另行授权。

## Windows 快速启动

在本目录打开 PowerShell，确认 Docker Desktop 使用 Linux containers。操作只创建本项目的资源；不要使用 `docker system prune`、WSL 重置或 `docker compose down -v`。

以下命令用于无模型基线。若已经启用 DeepSeek，先运行 `.\deepseek.ps1 -Action disable` 恢复基线；启用标记存在时，`manage.ps1` 会转交模型配置管理，`verify` 会调用真实付费 API。

```powershell
.\manage.ps1 -Action init
.\manage.ps1 -Action build
.\manage.ps1 -Action up -StartDocker
.\manage.ps1 -Action status
.\manage.ps1 -Action verify -Lifecycle
```

`init` 创建本项目 `.venv` 并安装固定的 Python HTTP 客户端依赖，不修改系统或其他项目的 Python 包。可用 `-Python '完整的python.exe路径'` 指定创建虚拟环境的解释器。

| 实例 | 入口 | 用户名 | 本机密码文件 |
|---|---|---|---|
| A | http://127.0.0.1:14091 | `client-a` | `.secrets/client-a.password` |
| B | http://127.0.0.1:14092 | `client-b` | `.secrets/client-b.password` |

密码首次随机生成，重启后保持不变。用本机编辑器查看自己的密码文件并输入浏览器认证框；不在 URL、命令参数、截图、聊天或提交中粘贴密码。两实例采用不同的浏览器配置以避免认证缓存混淆。密码文件和虚拟环境均被 Git 忽略。

入口容器将回环端口固定转发到自己的 OpenCode：A 入口只连接 A，B 入口只连接 B，不处理认证、不保存业务数据、不接受可变目的地址。OpenCode 仍仅连接各自的内部网络。在本次 Docker Desktop 环境中，直接给 internal 网络中的 OpenCode 发布端口无法从宿主机访问，因此采用经用户确认的专属入口层。

端口只绑定回环地址，其他电脑暂时无法连接。此阶段用本机两套浏览器配置和两套 HTTP 凭据模拟客户机；没有物理设备绑定。同一实例的凭据代表该实例的完整访问权。

## 日常操作与数据保留

```powershell
.\manage.ps1 -Action stop -Client client-a
.\manage.ps1 -Action start -Client client-a
.\manage.ps1 -Action restart -Client client-b
.\manage.ps1 -Action recreate -Client client-a
.\manage.ps1 -Action status
```

省略 `-Client` 表示全部实例。操作 all 涵盖两个 OpenCode 和两个入口，指定 client-a/client-b 只操作对应 OpenCode。入口会为每次新连接重新解析对应服务地址，因此 OpenCode 重建后无需重新配置入口。停止和重建不删除命名卷；不要手动删除卷。密码文件缺失或无效时启动失败，不自动更换旧密码。容器使用 `restart: unless-stopped`，人为停止后不会被自动重新启动。

每实例两个卷分别保存 `/home/opencode` 和 `/workspace`；XDG config/data/cache/state 均在独立 HOME 中。应用数据通常包括 SQLite 会话数据库及日志。另有独立 `/tmp` tmpfs。容器根文件系统只读，不挂载宿主机用户目录、Docker socket 或其他实例卷。OpenCode 容器的独立内部网络没有公网出口。入口分别连接自己的普通入口网络和对应的内部网络，并关闭 IP 转发，只执行固定目的 TCP 转发；它们没有客户机密码、HOME 或工作区卷。本期不为排查依赖下载而解除 OpenCode 的网络隔离。

备份前先停止需要备份的实例，再按卷归属导出该实例的 HOME 与工作区，保留对应密码文件。不要仅复制运行中的 SQLite 主文件而遗漏 WAL。恢复与升级应先在复制的数据卷上验证；本期脚本不包含自动数据删除和迁移。

## Python 与验收

```powershell
.\.venv\Scripts\python.exe .\client.py --client client-a --title SYNTHETIC-demo --events-seconds 10
.\.venv\Scripts\python.exe .\verify.py
.\.venv\Scripts\python.exe .\verify.py --lifecycle
```

示例使用真实 HTTP Basic Auth、会话 API 和 SSE，不经过模型。验收会新建合成会话和测试文件；`--lifecycle` 会明确停止、启动和重建 A，并持续检查 B。测试不删除持久卷，不调用模型，不接真实业务数据。

结果写入 `evidence/api-isolation.json`。浏览器实际渲染、空卷冷启动和最终验收结论单独记录；Python 报告的 `passed` 仅表示脚本覆盖的检查通过。实际 API 以此版本 `/doc` 为准。

## 内网 Linux 迁移

准备 Linux amd64、Docker Engine、Compose、Python 3.11 及以上版本（建议 3.12）及其 venv 支持、`unzip` 和 Linux `acl` 包（提供 `setfacl` / `getfacl`）。请管理员提前安装这些系统依赖，脚本不会自动安装。离线 wheels 由 Python 3.12 环境解析；不支持直接用 Python 3.10 或更早版本安装本部署包。首轮保持同样的回环绑定，不直接把端口改成全网可见。

在 Windows 主机先完成 API/生命周期、浏览器和空卷副本的验收；三份报告都必须匹配当前镜像 ID 和主 Compose 文件摘要，才能导出：

```powershell
.\.venv\Scripts\python.exe .\cold_start.py
.\manage.ps1 -Action export
```

`cold_start.py` 使用唯一的 `peixian-opencode-cold-时间-UUID` 项目和回环端口 14093/14094，先确认该副本没有旧容器、卷或网络，再用新卷验证无模型启动。运行后只停止副本，保留副本容器、四个数据卷、网络以及 `.runtime/cold-…/compose.json`，便于审计；不会停止主项目，也不会删除卷。结果写入 `evidence/cold-start.json`，它证明新建副本的空卷启动，不追溯主项目的首次启动历史。

之前已经生成的 `dist` 是当时的一期无模型交付快照，源码更新不会自动改写旧归档。使用更新后的 `export` 重新生成时，ZIP 会按显式白名单同时收录可选 DeepSeek 的说明、脚本、配置和脱敏证据，使文档与脚本引用完整；仍不包含 `.secrets`、`.runtime`、模型密钥或启用标记。新目录解压后默认按无模型基线启动，可选 DeepSeek 需要另行准备凭据并显式 `enable`，该配置的原生 Linux 迁移尚未验收。模型配置启用时继续禁止导出。

传输 `dist` 下的 `peixian-opencode-1.18.30-r1-linux-amd64.tar`、对应 `.tar.sha256`、`peixian-deployment.zip` 和对应 `.zip.sha256` 四个文件。目标服务器先校验两个归档，再解压部署包并导入镜像。请在新的部署目录操作；无网环境直接启动已导入的镜像，`up` / `start` / `recreate` 不构建或拉取镜像。

```sh
sha256sum -c peixian-opencode-1.18.30-r1-linux-amd64.tar.sha256
sha256sum -c peixian-deployment.zip.sha256
unzip peixian-deployment.zip
docker image load -i peixian-opencode-1.18.30-r1-linux-amd64.tar
cd peixian-deployment
sh manage.sh init
sh manage.sh up
sh manage.sh verify-lifecycle
```

部署包里的 `wheels` 提供 Python HTTP 客户端的离线依赖；Linux `init` 优先从该目录安装。目标服务器重新生成两份密码，部署包不携带本机密码或客户机数据。`init` 保留宿主文件所有者的读写权限，仅额外给容器 UID 10001 授予只读 ACL，文件所属组和其他用户没有读取权限；`.secrets` 目录仍只允许宿主所有者访问。原生 Linux 上不能只用宿主用户的 `0600` 文件，否则 UID 10001 无法读取 Compose 挂载的密码。缺少 ACL 工具、文件系统不支持 ACL 或现有文件不归操作者所有时，初始化会明确停止；应由管理员修复后重试，不要改为所有人可读。若管理员需要从自己的电脑查看服务器网页，可用 SSH 转发服务器回环端口；正式多客户机 HTTPS、证书和网络准入另行实施。

## 下一阶段：真实 vLLM

`config/vllm.example.json` 仅为未启用的示例。实际模型 ID 必须匹配 vLLM `/v1/models`，`INTERNAL_LLM_BASE_URL` 应包含 `/v1`。基线入口脚本使用打包的无模型配置，仅编辑 HOME 中的配置不会启用模型；可选 DeepSeek 通过显式覆盖配置启用。

下一阶段需要统一修改运行配置、为指定内网 vLLM 地址开放所需网络路径、按实例提供私密模型凭据，并提前打包模型适配依赖。然后验证真实流式回答、取消和工具调用闭环。本期不改现有 vLLM，不宣称镜像已经通过真实模型离线验收。
