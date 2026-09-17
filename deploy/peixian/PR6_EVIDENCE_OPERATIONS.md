# PR-6：证据更正、恢复与目标验收准备

开发起点：`1b3fff97ecc7a90f1620df1527117b5ab0daa5ea`。本轮工具不迁移数据库、不改变 schema 4 / config 3 / protocol 2，不重启原 14090/A/B 或独立测试环境，不执行恢复、故障或负载。

## N3-E 工具职责

| 工具 | 本次实现 |
|---|---|
| `evidence_contract.py` | 原始字节归档对象校验、Python 双向集合、独占批次、回执归属和公开字段校验 |
| `n3-local-evidence.py` | 固定 Git 候选，检查前后容器身份/源码/宿主源码/journal 稳定；只读归档、容器受控目录和可信内部 GET；更正证据独立输出 |
| `render-evidence-report.py` | 验证白名单后从 JSON 生成摘要；不人工复制 config/manifest/index |
| `evidence-run.py` | 在原测试工具之前创建私有批次与完整 journal 基线；不触发业务 |
| `r2-local-smoke.py` / `r3-local-check.py` | 可选 `--run-manifest`，原 CLI 仍可用；前者记录实际配置保存返回的 job，后者不认领其他配置操作 |
| `release-check.py` | 包文件与源码归档、四组件 config、Control 对象关系、必需项及候选绑定；输出在包外，非 pass 返回 2；不修改开发打包器行为 |
| `acceptance-preflight.py` | N4/N5 画像字段与授权准备检查；只读计划校验，不据此宣布真实目标已核验 |

采集的 Python 范围为 `control/**/*.py` 与 `shared/**/*.py`；预期来自固定提交，实际来自对应容器目录，缺失/多余/变化先单列。宿主 Worker、runtime、config、capacity 及三个共享依赖单独核对。CRLF/LF 仅用于 Python 源码等价，不用于镜像、归档或迁移身份。运行中的迁移验证仍由既有系统执行，没有绕过。

构建输入记录目前覆盖 Dockerfile、依赖锁、启动/管理脚本、前端包清单和 Bun 锁；不把该子集或 Python 检查称为整个静态资源构建证明。现有 Worker 启动记录没有启动时源码摘要，新工具只能证明当前磁盘文件，不能反推旧进程加载内容。未重启 Worker 来补造此证据。

## 只读采集与更正

先提交工具并得到完整 tool SHA，保证工具本身与提交一致。下面 `<…>` 为必填真实值，不能原样执行；输出必须新建。

```powershell
services/peixian-control/.venv/Scripts/python.exe deploy/peixian/n3-local-evidence.py --config deploy/peixian/.runtime/r2-local/profile.json --source-commit 95896a843f2bd83dc0ee695713cf5dccbebbaad1 --tool-commit <工具完整SHA> --package-source-commit 1b3fff97ecc7a90f1620df1527117b5ab0daa5ea --archive deploy/peixian/dist/agent-platform-n3-candidate-1b3fff97e/images.tar --run-manifest deploy/peixian/.runtime/pr6/<新批次>.json --output deploy/peixian/reports/<新证据>.json
services/peixian-control/.venv/Scripts/python.exe deploy/peixian/render-evidence-report.py --evidence deploy/peixian/reports/<新证据>.json --output deploy/peixian/reports/<更正说明>.md
```

公开证据不含内部 job/attempt/operation 明细。私有 manifest 及 `.historical.json` 保存这些关联和旧回执只读查询，留在 `.runtime`；不打包、不提交。没有查到旧回执不证明原宿主操作未执行，当前 job 已结束也不证明历史操作当时成功。两条历史 pending 不修改、不删除，负责人残余风险决定未获得前发布保持 blocked。

报告明确区分控制库观测与即时全组件/宿主变更核对；当前责任如仍无完整证据，不能因为收集脚本成功就批准发布。

## 后续已授权测试的批次关联

先用 `evidence-run.py --config ... --output <私有新文件> --baseline <SHA> --runtime-commit <SHA> --tool-commit <SHA> --case busy_update` 创建批次，再向 `r2-local-smoke.py` 传 `--run-manifest <私有新文件>`。事件测试使用 case `event_subscriptions`。

manifest 的预期场景必须与工具一致。当前工具一个批次一个场景；不支持多人同时写同一 manifest。由 job 唯一归属，attempt/operation 从实际 journal 采集。测试前后的 journal 消失或无归属新增/变更是 incomplete；时间戳和字段格式都不授予归属。历史、其他已知批次和本批次有明确分类函数；现有 CLI 不导入其他批次，所以并发新增会保守报告 unattributed。

正常场景期望 recorded；故障工具使用 rejected/unknown 时需另外声明，并提供 applied、容量、Gate 和恢复终态证据。仅期望状态匹配不能证明恢复完成。工具在内层业务异常之前失败也会终结私有 manifest 为 failed/incomplete，不打印 traceback 或响应正文。

## 发布核对

```powershell
services/peixian-control/.venv/Scripts/python.exe deploy/peixian/release-check.py --package deploy/peixian/dist/agent-platform-n3-candidate-1b3fff97e --evidence deploy/peixian/reports/<新证据>.json --profile deploy/peixian/server/pr6-release.profile.json --output deploy/peixian/reports/<新发布核对>.json
```

profile 初始无批准引用、必需 N4/N5 等结果为空。预期返回 blocked（退出码 2），不是运行故障。来源 false、内容篡改或对象冲突返回 fail。不得为了变绿删除必需项、手改证据状态或修改已冻结包。审批引用是人工审批材料的关联，不是密码，也不代表脚本代替负责人审批。

## N4 准备与未执行项

`acceptance-preflight.py --profile deploy/peixian/server/n4-prep.profile.json --output <新文件>` 只检查规划字段；默认 blocked。它不会获取/创建第二个 Docker 引擎，也不执行 restore。实际引擎、资源空置、目录隔离、磁盘和兼容性仍须授权后独立核验。不同 context 名称不证明不同引擎。

复用 `platform-backup.py` / `platform.ps1 -Action backup,verify-backup,restore`：新 deployment_id、真正空目标、完整备份及匹配密钥；源冻结并停止所有写入者后建立 T0。严禁只用 upgrade-backup、删原卷、改标签或降低数据库版本。恢复后先验证暂停、认证撤销和保护状态，再经管理入口恢复合成账号。

验收基线须含两账号身份/角色、授权、历史、文件原始摘要、结果、个人技能和插件配置。对照恢复后的逻辑不变量，而非强求撤销认证后的库字节相同。RS-01～05、损坏副本、缺密钥、恢复中断、新请求验证均尚未实际执行。当前交付是预检字段与手册；真正空目标恢复验收执行器尚未完成，不称 N4 完成。

## N5 准备与未执行项

`acceptance-preflight.py --profile deploy/peixian/server/n5-prep.profile.json --output <新文件>` 分别要求注册账号、viewer、upstream、Runtime、生成、API RPS、生命周期速率、时长和采样周期。执行授权默认为 false，硬件、阈值和停止条件均不得猜测。

后续复用 `services/peixian-control/benchmarks/platform_load.py`、`small_profile.py`、`control_layer_load.py`；本轮没有改动这些执行器，也没有为其增加隐式执行权限。真实 barrier/代理丢响应、强杀子进程及完整采样汇总仍待实现和授权。正常负载与故障分别建批次，安全断言失败优先于性能平均值。

准备字段齐全最多返回 prepared，始终 `execution_performed=false`、`target_verified=false`。不称 Linux、恢复、50 并发、真实模型或 PR-6 整体通过。
