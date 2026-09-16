# Agent 工作台：单服务器部署

本入口面向全新单机部署，统一使用 `platform-manage.py` 和一份 JSON 配置。原有 `console.ps1`、14090 本机部署和 A/B 数据继续保留；不要把新配置的 data_root 指向旧部署的私密目录。

目标是 Ubuntu 24.04、x86_64、Docker Engine、Compose v2。Docker 是本机 Linux 引擎，远程 Docker context 不受支持。控制服务单进程使用 SQLite；每个普通账号仍拥有 Agent、HTTP 网关、出口三个容器。宿主执行器直接管理本机 Docker，因此 systemd 服务使用 root；应用容器不挂载 Docker socket。

## 配置与离线前置条件

部署包中的镜像清单和校验清单为所交付版本的依据。先校验并导入镜像，然后从包内 wheelhouse 安装宿主 Python 依赖，安装过程使用 `--no-index`。Docker Engine/Compose、Python 3.12、venv、CA 证书和 `acl` 系统包应预装；完全离线的操作系统必须由部署方准备这些 Ubuntu 系统包及其依赖。部署脚本不现场安装 Docker 或修改主机防火墙。

代理镜像的交付标签为 `agent-platform-proxy:nginx-1.28.0`，来源固定为官方 `nginx:1.28.0-alpine@sha256:30f1c0d78e0ad60901648be663a710bdadf19e4c10ac6782c235200619158284`。离线 save/load 使用本地明确标签，清单记录源摘要和镜像 ID，避免依赖 Docker 重新加载时未保留的 RepoDigests。启动仍固定到已检查的镜像 ID。

将交付包解压到 `/opt/agent-platform`。以下命令中的路径是部署规范，原始私密文件不包含在交付包中：

```bash
cd /opt/agent-platform
python3 -m venv worker-venv
worker-venv/bin/python -m pip install --no-index --find-links wheels -r deploy/peixian/requirements.txt
install -d -m 700 /etc/agent-platform
cp deploy/peixian/server/platform.example.json /etc/agent-platform/platform.json
```

调整配置后再初始化：

| 字段 | 用途与默认值 |
| --- | --- |
| `deployment_id` | 独立 Docker 命名空间；默认 `agent-platform`。不能复用其他部署标识 |
| `product` | 名称、简称、介绍；默认 Agent 工作台 |
| `public_url` | 浏览器使用的 HTTPS Origin，不能包含账号密码、路径、查询串 |
| `https_port` / `bind_host` | HTTPS 入口；必须与 public_url 中的端口一致 |
| `control_port` | 执行器专用本机 HTTP 入口，仅绑定 127.0.0.1，默认 14090 |
| `data_root` | 独立宿主目录，包含 secrets、worker 配置版本和生成配置；控制数据与用户数据保存在 Docker 命名卷 |
| `tls` | 部署方提供的 PEM 证书与匹配私钥。证书应覆盖 public_url 主机名，并被客户机信任 |
| `network_pool` | 为本部署预留的私有 IPv4 CIDR，默认 `10.240.0.0/16`。须与内网网段、VPN 及其他 Docker 网络避开重叠 |
| `max_runtimes` | 同时保留的普通用户运行名额，默认 4；控制台与执行器读取同一值 |
| `resource_limits` | 默认 Agent 2 CPU/2048 MiB、网关 0.5 CPU/512 MiB、出口 0.5 CPU/128 MiB |
| `images` | 明确版本的四种镜像；启动前校验并固定到本机镜像 ID，禁止漂移 latest |

默认总内存预算检查为 12,288 MiB（4 个账号的配额加 1,536 MiB 平台预留），CPU 预算为 13 个逻辑 CPU（账号配额总和加 1 个平台预留）。预算与宿主执行器一致，是上限规划，不代表实际常驻消耗；宿主系统和模型服务还需要另外预留资源。降低或增加名额时同步检查实际容量。

## 首次启动

将证书和私钥放到配置指定的位置，再运行：

```bash
cd /opt/agent-platform
worker-venv/bin/python deploy/peixian/platform-manage.py init --config /etc/agent-platform/platform.json
worker-venv/bin/python deploy/peixian/platform-manage.py check --config /etc/agent-platform/platform.json
worker-venv/bin/python deploy/peixian/platform-manage.py up --config /etc/agent-platform/platform.json
cp deploy/peixian/server/agent-platform-worker.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now agent-platform-worker
```

`init` 只创建缺失凭据，不替换既有密钥和密码；Linux 会给 UID 10001 授予指定凭据、证书的只读 ACL。若外部证书目录有特殊 ACL，应保证容器可以读取被绑定的文件。执行器发布目录单独设置 UID 10001 的只读权限。

初始超级管理员账号为 `admin`。临时密码在 `<data_root>/secrets/console-admin.password`，脚本不会打印密码。首次登录必须修改密码。浏览器使用 HTTPS 和 Secure Cookie；Python 客户端使用该 HTTPS 地址与个人访问令牌，并使用单位 CA 信任链。

Nginx 仅暴露 HTTPS 入口，不暴露 `/internal` 和 `/internal/` 路径；SSE 禁止缓存和缓冲，读超时 1 小时。控制容器 HTTP 入口仅向宿主执行器开放。网络层面还应限制运维人员对宿主机的访问。

## 日常操作与升级

```bash
worker-venv/bin/python deploy/peixian/platform-manage.py status --config /etc/agent-platform/platform.json
journalctl -u agent-platform-worker --since today
```

平台停止命令停止控制台和 HTTPS 入口，账号环境由超级管理员在管理界面独立暂停。准备维护或备份时，先停止接收新操作，暂停所有账号并等待环境任务结束，再停止执行器；不要在正在应用配置时终止执行器。

```bash
systemctl stop agent-platform-worker
worker-venv/bin/python deploy/peixian/platform-manage.py stop --config /etc/agent-platform/platform.json
```

升级前先完成下节的全量备份。控制库跨 schema 升级还必须生成与当下停止状态一致的升级检查备份：

```bash
worker-venv/bin/python deploy/peixian/platform-manage.py upgrade-backup --config /etc/agent-platform/platform.json
worker-venv/bin/python deploy/peixian/platform-manage.py up --config /etc/agent-platform/platform.json
systemctl start agent-platform-worker
```

先导入并验证新镜像，再改配置中的版本。`up` 在检查数据库兼容性后使用同一个不可变镜像 ID，失败不自动删除数据。不兼容的旧镜像不能直接连接升级后的控制库。普通重启、停止和重建均不删除卷。

## 全量备份与受控恢复

这套工具备份控制库、发布包、所有已登记账号卷、执行器配置版本、平台匹配密钥以及 TLS 证书私钥。备份是私密资料，不能上传到源码仓库或与安装包一同公开分发。保留备份时同时保留相应离线镜像包。

备份要求：执行器不持有锁、控制台已停止、所有卷的使用容器已停止、没有等待或执行中的环境任务。脚本不替代暂停流程，也不自动终止任务。

```bash
worker-venv/bin/python deploy/peixian/platform-manage.py backup \
  --config /etc/agent-platform/platform.json \
  --destination /srv/agent-backups/20260915-full
worker-venv/bin/python deploy/peixian/platform-manage.py verify-backup \
  --config /etc/agent-platform/platform.json \
  --archive /srv/agent-backups/20260915-full
```

目标备份目录必须全新且位于 data_root 之外。脚本逐文件验证归档前后摘要，检测源数据变化和链接／路径穿越；失败产物保留供检查，不作为成功备份。备份不会清理历史版本或缓存。

恢复使用**新的部署标识、空 data_root 和空目标 Docker 资源**。账号 ID、运行环境 ID、密码哈希、资料和授权保留；控制卷按新命名空间创建，账号卷保留原名称。目标宿主不得已有对应 `px-<runtime_id>` 容器、网络或卷，因此不能将相同账号身份同时恢复为同一 Docker 引擎上的第二套活动环境。推荐恢复到独立主机；本机测试只能对已验证备份的合成环境执行资源清理。

```bash
worker-venv/bin/python deploy/peixian/platform-manage.py restore \
  --config /etc/agent-platform/restored-platform.json \
  --archive /srv/agent-backups/20260915-full
worker-venv/bin/python deploy/peixian/platform-manage.py init --config /etc/agent-platform/restored-platform.json
worker-venv/bin/python deploy/peixian/platform-manage.py up --config /etc/agent-platform/restored-platform.json
```

恢复配置放在 data_root 之外；TLS 路径可以指向恢复后的 `<data_root>/tls/certificate.pem` 和 `private-key.pem`。恢复后所有环境处于暂停状态，旧登录与访问令牌已撤销；启动执行器后由超级管理员逐个恢复，核对会话、文件及实际调用。恢复会生成脱敏 receipt；部分恢复失败保留目标，不自动回滚或覆盖。重新恢复必须使用另一个空目标，或由运维先检查和处理失败目标。

## Windows 本地入口

Windows 仍使用 Docker Desktop 的 Linux 引擎。使用另一份配置与独立部署标识、空闲端口、未占用的网络池及独立 data_root，可以保留当前旧控制台。配置中的路径使用 Windows 绝对路径或相对于配置文件的路径。

```powershell
.\deploy\peixian\platform.ps1 -Action init -Config D:\AgentPlatform\platform.json
.\deploy\peixian\platform.ps1 -Action check -Config D:\AgentPlatform\platform.json
.\deploy\peixian\platform.ps1 -Action up -Config D:\AgentPlatform\platform.json
.\deploy\peixian\platform.ps1 -Action worker-start -Config D:\AgentPlatform\platform.json
.\deploy\peixian\platform.ps1 -Action status -Config D:\AgentPlatform\platform.json
.\deploy\peixian\platform.ps1 -Action worker-stop -Config D:\AgentPlatform\platform.json
```

可以用 `-Python` 显式指定已安装依赖的 Python。后台执行器使用隐藏窗口，其 PID、创建时间、脚本及配置路径记录在该部署的 worker 目录。Windows venv 启动器及真正执行任务的 Python 子进程会分别记录；停止时先验证身份并检查内部任务是否空闲，再按子进程到父进程的顺序停止。不会寻找或停止旧 `console.ps1` 的执行器，也不会终止未知进程。`stop` 会先安全停止本配置的执行器，再停止控制台与 HTTPS 入口；账号容器仍由超级管理员独立暂停。跨平台停止命令也会检查 worker 锁，未被脚本跟踪的手动执行器仍运行时会拒绝停止控制台。

备份和恢复对应 `-Action backup -Destination <全新目录>`、`-Action verify-backup -Archive <备份目录>`、`-Action restore -Archive <备份目录>`，约束与 Linux 一致。进程 PID 记录和 worker 锁属于主机临时状态，不进入迁移备份。

## 可重复构建离线交付目录

开发机上先准备四个镜像标签及 Linux Python 3.12 wheelhouse。默认 `platform-package.py` 可以导出新 images.tar；如果目标中已经存在归档，必须使用 `--assemble`，脚本不会覆盖镜像归档或源码归档。

```powershell
python deploy/peixian/platform-package.py --assemble --source-commit HEAD
```

默认读取 `deploy/peixian/dist/platform/linux-wheels` 与 `deploy/peixian/dist/agent-platform-v1-linux-amd64/images.tar`，可以用 `--wheels` 和 `--destination` 指定。输出目录限定在部署 dist 下。

组装仅复制明确列出的运行脚本、配置示例、手册、示例插件、OpenAPI 和 wheel 文件；遇到输出目录中的未知文件或私密目录时拒绝组装并保留原内容。四个镜像的架构、标签及 config ID 从 images.tar 本身读取，不用可能已经重建的本地标签代替归档证据。最后生成 `release-manifest.json` 与 `SHA256SUMS`。

`source_matches_commit=false` 表示所复制源码与指定提交不完全一致，只可视为候选包；完成本地提交后重新组装，核对该字段为 true 后交付。源码 `git archive` 可由发布流程另行生成，打包器只记录已存在的 `source.tar.gz`／`source.tar`，不修改它们。

## 验证边界

当前交付要求在 Windows Docker Desktop 的 Linux 容器中完成 HTTPS、配置、权限、插件、备份与恢复验证。Ubuntu 实机、单位证书链、真实内网模型及业务接口尚须在目标服务器复验；本手册不把配置模板或容器测试作为 Linux 实机验收。
# 第一轮并发加固配置说明

新增 `platform.50-io.example.json` 是配置 v2 的独立测试入口；旧 `platform.example.json` 仍按 v1 解释。部署、升级、恢复前应查阅 [第一轮实施指南](../../../services/peixian-control/docs/HARDENING_R1.md) 和 [验收报告](../../../services/peixian-control/docs/HARDENING_R1_REPORT.md)。

50 人示例保留原账号内存上限，严格预算为 137.25 GiB，16 核/32 GiB 上会明确拒绝启动。候选账号配额必须先画像验证。v2 的 Control 镜像须声明 `org.peixian.control.config.max=2`；schema v3 不变不意味着旧镜像兼容新配置。

Windows `platform.ps1` 和 Linux 的 `platform-manage.py --config` 均读取同一份版本化配置。`backup` 为全量备份，`upgrade-backup` 只有控制卷。`platform-package.py --config ...` 按该配置精确选镜像，`--source-only` 包不包含镜像，不能代替完整离线部署包。
