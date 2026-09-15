# 托管控制台运维与 A/B 迁移

本文对应 `compose.console.yaml`、`console-worker.py`、`console-runtime.py`、`console-migrate.py` 和三角色升级检查 `console-guard.py`。所有命令在仓库的 `deploy/peixian` 目录执行。控制台默认地址为 `http://127.0.0.1:14090`；每个账号的 Agent、Gateway、模型 Relay 均没有宿主公开端口。

三角色版本使用 `peixian-control:console-r2-roles`；保留旧控制镜像 r1，不表示旧镜像可打开 schema 2。Agent 的 `peixian-opencode:1.18.30-managed-r1` 和 Gateway 的 `peixian-gateway:console-r1` 在这次角色变更中不升级。升级合同和权限见 [ROLES.md](ROLES.md)。本轮文档没有执行 Linux 部署测试。

只有普通用户分配业务运行环境；两个管理角色均无 runtime。普通用户从停用变为启用（active: false → true）时，服务端在同一事务内检查并预留容量、排入 resume，随后由执行器恢复原环境；管理员可通过“启用账号”完成这一业务动作，无需独立 runtime 权限。若停用引发的 pause 尚未完成，或没有可用名额，返回 409 并回滚本次启用，账号继续保持停用；待暂停完成或释放名额后再试。已经 active、只是被超级管理员手动暂停空间的用户，不会因修改其他设置或重复启用而自动恢复，仍须超级管理员“恢复空间”。

## 运行边界

- 宿主 worker 通过本机 Docker 管理每账号独立的 `px-{runtime_id}` 项目。应用容器不挂载 Docker socket。
- 每账号保存独立 HOME、workspace、files 卷。Agent 只有内部网络；Gateway 使用该账号独立管理网；Relay 使用该账号独立出口网。
- 每账号配额为 Agent 2 CPU/2 GiB、Gateway 0.5 CPU/512 MiB、Relay 0.5 CPU/128 MiB，合计 3 CPU/2.625 GiB。4 账号加控制台 512 MiB、系统预留 1 GiB，要求 Docker 引擎至少 12 GiB 内存；CPU 预算为 4×3+1=13。预算不足时，worker 在创建资源前拒绝开通。
- worker 读取 `.secrets/console-worker.key`，发布文件位于 `.runtime/console/runtimes/{runtime_id}/releases/{revision}`。发布目录只读挂入容器，模型密钥目录仅挂入 Relay。
- 运行时只使用本地 `linux/amd64` 镜像，不自动拉取镜像、安装插件依赖或下载模型。插件须先由超级管理员发布，自带所需代码。
- 网络与卷由宿主管理并按所有权标签校验，实际运行的 Compose 将它们声明为 external，避免发布修订变化导致网络重建。不要直接对 `releases/{revision}/compose.json` 执行 `up`；使用 worker 或迁移工具生成的 `operations/{revision}-compose.json`。
- worker 等待正在执行的会话最多 300 秒；仍忙则延后任务。暂停、迁移和回退不能与另一个宿主 worker 并行执行，脚本使用同一宿主锁。

## Linux 主机准备

需要本机 Linux Docker Engine、Docker Compose v2、Python 3.12，以及提供 `setfacl`/`getfacl` 的 `acl` 包。宿主 worker 运行账号必须能访问本机 Docker；这属于宿主管理权限。不要把该权限授予平台普通账号。

以下路径以完整仓库部署到 `/opt/peixian-opencode` 为例。首次准备 Python 环境：

```sh
cd /opt/peixian-opencode
python3 -m venv services/peixian-control/.venv
services/peixian-control/.venv/bin/python -m pip install -r services/peixian-control/requirements.lock
cd deploy/peixian
command -v setfacl
command -v getfacl
```

离线环境需要提前准备与目标 Linux 架构、Python 版本匹配的 wheels，使用 `pip install --no-index --find-links <wheel目录> -r ...`。Windows wheels 不能作为 Linux 依赖包使用。镜像应由已验证的构建产物导入：

```sh
sha256sum -c peixian-console-images.tar.sha256
docker load -i peixian-console-images.tar
docker image inspect --format '{{.Os}}/{{.Architecture}} {{.Id}}' \
  peixian-control:console-r2-roles peixian-gateway:console-r1 peixian-opencode:1.18.30-managed-r1
```

初始化凭据不会覆盖已有文件。不要把密钥写入命令行参数、服务单元、Git 或普通交付压缩包。Linux 上应确保宿主操作者拥有目录和文件，仅给容器 UID 10001 增加读取权：

```sh
../../services/peixian-control/.venv/bin/python console-bootstrap.py
chmod 700 .secrets
chmod 600 .secrets/console-control.key .secrets/console-worker.key .secrets/console-admin.password
setfacl -m u:10001:r,m::r .secrets/console-control.key .secrets/console-worker.key .secrets/console-admin.password
getfacl .secrets/console-control.key .secrets/console-worker.key .secrets/console-admin.password
```

ACL 的 `mask::r--` 使 `ls -l` 的组权限位显示为可读；实际 `group::---` 和 `other::---` 保持禁止，具名 UID 10001 具有读取权。以 `getfacl` 的结果为准。平台用户初始密码文件不需要授予容器 UID 读取权。

全新安装检查后启动；旧库首次升级需先安全停止实际宿主 Worker 服务及控制台，并创建停写备份。以下仍在 deploy/peixian 目录，备份只涵盖 control-data，不包含用户卷与独立密钥：

```sh
# 旧库升级前，先停止并确认实际宿主 Worker 已退出，再执行：
docker compose -f compose.console.yaml stop
../../services/peixian-control/.venv/bin/python console-guard.py backup
```

备份失败则停止升级。后续全新安装或已满足备份要求的升级都使用以下校验并固定镜像的启动方式：

```sh
peixian_guard_json="$(../../services/peixian-control/.venv/bin/python console-guard.py check)" || exit 1
peixian_checked_image="$(printf '%s' "$peixian_guard_json" | ../../services/peixian-control/.venv/bin/python -c 'import json,re,sys; value=json.load(sys.stdin); image=value.get("image_id",""); assert value.get("status")=="passed" and re.fullmatch(r"sha256:[0-9a-f]{64}", image), "Invalid guard result"; print(image)')" || exit 1
PEIXIAN_CONTROL_IMAGE="$peixian_checked_image" docker compose -f compose.console.yaml up -d --no-build --pull never --wait || exit 1
../../services/peixian-control/.venv/bin/python console-worker.py
```

guard 返回的 image_id 是本次实际校验的不可变镜像；设置 PEIXIAN_CONTROL_IMAGE 后再启动，防止检查通过后标签被另一构建替换。校验失败、不合法结果或缺失镜像时不要改回直接标签启动。Windows 的 console.ps1 up/start 已内置相同流程；Linux 示例仅作操作说明，未在本轮实际部署验证。

worker 默认使用 `http://127.0.0.1:14090`、`.secrets/console-worker.key`、`.runtime/console` 和最多 4 个运行实例。可通过 `--control-url`、`--key-file`、`--state-root`、`--max-runtimes` 覆盖。控制台 Compose 的 `MAX_RUNTIMES` 与 worker 上限应保持一致。

需要从另一台电脑访问时，可通过 SSH 本地转发访问回环入口，例如 `ssh -L 14090:127.0.0.1:14090 <运维账号>@<服务器>`。若改为正式域名，应同时配置 TLS 和控制台允许的 Origin，不能只扩大监听范围。

## 宿主 worker 常驻示例

由运维人员按实际安装路径和服务账号创建 systemd 单元，平台容器仍保持不接触 Docker socket：

```ini
[Unit]
Description=Peixian console host worker
After=docker.service
Requires=docker.service

[Service]
Type=simple
User=peixian
Group=peixian
WorkingDirectory=/opt/peixian-opencode/deploy/peixian
ExecStart=/opt/peixian-opencode/services/peixian-control/.venv/bin/python /opt/peixian-opencode/deploy/peixian/console-worker.py
Environment=PYTHONUNBUFFERED=1
Restart=on-failure
RestartSec=10
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
```

`peixian` 是示例宿主服务账号，不是平台普通账号。启用前应检查它的 Docker 权限和 `.secrets`、`.runtime/console` 的所有权。worker 日志只输出任务 ID、动作与错误代码，故障时不要把原始模型配置或容器环境变量粘贴进工单。

## 已核对的 A/B 原卷

迁移接口和脚本只接受下面的固定对应关系，不允许通过请求传入任意 Docker 卷：

| 原实例 | HOME 卷 | workspace 卷 |
| --- | --- | --- |
| client-a | `peixian-opencode_client-a-home` | `peixian-opencode_client-a-workspace` |
| client-b | `peixian-opencode_client-b-home` | `peixian-opencode_client-b-workspace` |

这些名称来自原 `peixian-opencode` 项目的实际容器挂载核查。若源环境名称不同，脚本会拒绝迁移，需要重新审阅允许列表，不能绕过检查。新账号会额外创建自己的 files 卷，原 HOME/workspace 作为 external 卷复用，不复制到其他账号，也不修改其所有权。

## 迁移前只读检查

以下命令在仓库的 `deploy/peixian` 目录执行。Windows 使用控制服务专属 Python 环境 `../../services/peixian-control/.venv/Scripts/python.exe`；Linux 替换为 `../../services/peixian-control/.venv/bin/python`。

```powershell
..\..\services\peixian-control\.venv\Scripts\python.exe .\console-migrate.py inventory --client client-a
..\..\services\peixian-control\.venv\Scripts\python.exe .\console-migrate.py inventory --client client-b
..\..\services\peixian-control\.venv\Scripts\python.exe .\console-migrate.py snapshot --client client-a
..\..\services\peixian-control\.venv\Scripts\python.exe .\console-migrate.py snapshot --client client-b
```

`inventory` 只读取 Docker 容器、标签和卷映射；不读取容器环境变量或密码。`snapshot` 使用本地现有镜像启动一个短暂辅助容器，以 UID 10001、只读源卷和无网络方式读取数据，并直接通过 stdout 写入宿主私有备份；不停止或修改原服务。

在线快照标记为 `offline: false`，不能视为数据库一致性备份，也不能用于正式导入。`--require-stopped` 会要求旧入口、旧 Relay、旧 Agent 以及原卷的全部消费者均停止。归档逐文件记录 SHA-256，保留普通文件、目录和符号链接；归档校验不会解压或跟随链接。读取过程中检测到文件变化、无法读取或不支持的文件类型时失败，保留失败记录和已有数据。

快照路径位于 `.runtime/console/migrations/{client}/{snapshot_id}`，包括 `home_volume.tar`、`workspace_volume.tar`、每个归档内部的文件摘要、`snapshot.json` 和报告 SHA-256。该目录包含真实会话和文件，应按业务数据备份管理，不要混入公开源码包或普通验收截图目录。

校验指定快照：

```powershell
..\..\services\peixian-control\.venv\Scripts\python.exe .\console-migrate.py verify --client client-a --path <输出的快照目录>
```

## 正式逐账号迁移

先确认控制台和两种账号镜像已验证、控制台有可用运行名额，以及目标账号尚未在新平台开通。暂停宿主 worker 的常驻进程，并确认当前环境操作已经结束；迁移工具必须取得同一宿主锁，否则直接退出。它会在锁内单步运行 worker，因此不要另开一个 worker。

先查看动作计划，无 `--execute` 不改变服务：

```powershell
..\..\services\peixian-control\.venv\Scripts\python.exe .\console-migrate.py migrate --client client-a
```

正式迁移命令：

```powershell
..\..\services\peixian-control\.venv\Scripts\python.exe .\console-migrate.py migrate --client client-a --execute
..\..\services\peixian-control\.venv\Scripts\python.exe .\console-migrate.py migrate --client client-b --execute
```

默认不给迁移账号授予模型。如果要沿用管理员已经登记的模型，显式追加 `--model-id <模型资源ID>`，多个授权可重复参数。这里使用控制台的模型资源 ID，不是直接填写上游模型名称，也不在命令行传 API key。

每个账号按以下顺序执行：

1. 读取原会话 ID 清单，记录原容器运行状态，先停止旧入口。通过原 Agent 的本地认证接口等待会话空闲，最多 300 秒；确认空闲后才停止旧模型 Relay 和旧 Agent。
2. 确认原卷没有运行消费者，生成离线快照并校验归档。再次独立读取原卷，比较两次逐文件摘要；一致后才允许新 Agent 写入。
3. 创建独立的新平台初始密码，保存到 `.secrets/console-client-a.password` 或 `.secrets/console-client-b.password`，不复用旧 Basic Auth 密码。
4. 通过 worker-key 保护的 `POST /internal/worker/legacy-import` 原子导入固定卷映射、快照 ID/摘要及模型授权，随后在宿主锁内推进账号开通任务。
5. 检查控制层状态、Gateway 修订号、Agent 版本与受控 Skills 初始化；比较全部原会话的消息数量和规范摘要、工作区文件清单摘要。旧服务必须继续停止；HOME 只允许当前账号 Agent 使用，workspace 只允许同账号已核实的 Agent 和 Gateway 使用，按容器 ID、标签和挂载核实，其他消费者一律拒绝。
6. 写入 `status: passed` 的迁移日志。A 验收完成后再迁移 B；全部完成后恢复常驻 worker。

脚本不会自动发送模型问题，迁移验证不产生新的模型调用。离线双快照比对发生在新实例启动前；会话、消息及工作区摘要比对发生在接管后。启动后 OpenCode 可能更新数据库、缓存和状态，不要求整个 HOME 始终与迁移前字节完全相同。

## 回退与保留新增数据

迁移失败会尝试自动回退。后续需要人工触发回退时，使用该账号的具体迁移日志，而不是快照目录：

```powershell
..\..\services\peixian-control\.venv\Scripts\python.exe .\console-migrate.py rollback --client client-a --path <migration-UUID.json> --execute
```

回退会等待新账号会话空闲，停止新账号项目并确认全部停止，然后调用 `legacy-rollback` 停用新平台登录、撤销相关作业并释放名额。接着对当前 HOME/workspace 再次备份，并额外归档新账号的 files 卷，保留迁移后的新增数据，再恢复原先运行的旧容器。旧服务仍读取同一组当前 HOME/workspace 卷，脚本不会用迁移前快照覆盖它们。

若新实例停止无法确认，脚本不会启动旧实例并发写同一卷。若回退备份失败，保留卷和失败记录，等待运维处理。若发现数据格式无法由旧实例读取，应保留当前卷和备份，单独恢复到新命名卷进行验证；不要对原卷执行覆盖解压、`docker volume rm` 或 `docker compose down -v`。

已回退账号处于停用状态。核对失败原因并修正后，用显式重试命令重新建立离线快照，不复用旧快照跳过当前数据检查：

```powershell
..\..\services\peixian-control\.venv\Scripts\python.exe .\console-migrate.py migrate --client client-a --execute --retry-failed
```

模型授权参数按前述规则补充。宿主再次确认旧服务和全部卷写入者停止后，调用仅 worker-key 可访问的 `legacy-retry`。接口核对固定账号与卷、当前快照及既往回退记录，只有停用、失败且名额已释放、没有活动任务的账号才能在同一事务中恢复并排入 resume；保留密码、实例 ID 和数据卷。重复同次请求只返回原任务，后续停用、再次回退或认证版本变化会使旧请求失效。

## 日常备份与故障定位

- 源码、镜像包、控制数据库、账号卷和密钥属于不同备份对象。控制数据库加密内容需要对应的 `console-control.key` 才能恢复，密钥应单独保护。
- 宿主 worker 启动前应先启动控制容器；重启后已有命名卷和发布目录保持不变。worker 每次轮询会核对已登记账号的自有管理网标签，恢复控制容器重建后丢失的连接。不可用镜像、缺失依赖、无效配置或未确认停止都会以失败状态保留证据，不自动清理数据。
- 先查看控制台状态和最小化 worker 错误代码，再定位 `.runtime/console/runtimes/{runtime_id}/state.json`、`pending.json` 与发布修订号。不要通过修改 HOME/project 配置绕过托管控制。
- 当前工具的在线快照仅用于预备核查。正式一致性备份应安排账号暂停，在确认所有写入者停止后执行离线快照，并验证归档摘要；备份恢复需要在独立卷上演练。

迁移验收还会在旧入口停止、旧会话进入空闲之后，并在旧 Agent 停止之前，采集完整会话消息的数量与规范 JSON SHA-256 摘要。新网关必须保留原会话及每个会话的消息摘要；证据只写 ID、数量和哈希，不写消息正文。迁移后工作区会再做只读归档，其文件清单摘要必须与离线快照一致；HOME 因首次启动会更新缓存，不做整卷相等判定。任何消息或工作区摘要不一致都会进入已有回退流程，保留新旧数据。

`console-fault-acceptance.py` 默认只打印计划。显式 `python console-fault-acceptance.py --execute` 会创建专用 `console-fault` 合成账号；执行前需让普通宿主 worker 停止，并确保其他账号没有待处理任务。驱动在首次真实卷创建成功后退出子进程，等待至少 95 秒让租约自然失效，再由新的执行器领取相同任务和运行时，检查原卷复用、三卷唯一及就绪状态。最后只暂停这个合成账号并核对名额释放和数据保留，不调用模型。新密码保存在 `.secrets/console-fault.password`；脱敏结果保存在 `.runtime/console-fault-acceptance.json`，卷与合成哨兵保留。如驱动本身中断，先检查状态与其他队列，再以 `--execute --resume` 继续，不要删除卷。

真实启动失败可使用 `python console-startup-fault.py --execute` 做独立验收，默认不加参数仅输出计划。它要求前述 `console-fault` 中断验收已完成且账号已暂停，其他账号队列为空、普通 worker 已停止。驱动固定当时正常镜像 ID 到独立测试标签，以独立 `/bin/false` 入口镜像验证失败后的容器清理、名额释放和卷/哨兵保留，随后使用固定正常镜像恢复并再次暂停该合成账号。不会覆盖正式镜像标签；结果写入 `.runtime/console-startup-fault.json`，两个测试标签和卷保留供复核。该单次验收已有状态时会拒绝重跑，需先人工核对上次记录，不能删除卷绕过。
