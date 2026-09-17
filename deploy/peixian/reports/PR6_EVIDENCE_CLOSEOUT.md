# PR-6 / N3-E 本轮交付记录

日期：2026-09-17。分支：`codex/pr6-evidence-closeout`。开发起点 `1b3fff97ecc7a90f1620df1527117b5ab0daa5ea`。

## 本轮结果

**完成了 N3-E 首批工具开发、合成测试、归档更正及本机只读采集；N3-E 的全部退出条件尚未关闭，PR-6 仍为 blocked。** N4/N5 仅提供画像预检与手册，不称完整执行工具已完成。

没有修改 EventHub、Store、Worker 协议或控制数据库，没有重建/重启容器，没有执行恢复、强杀、网络故障、负载或真实服务调用。Docker 最初不可达，用户自行启动后，工具仅继续读取。原 14090/A/B 未由本轮操作。

## 版本与证据

| 对象 | 固定版本或证据 |
|---|---|
| 既有运行候选 | `95896a843f2bd83dc0ee695713cf5dccbebbaad1` |
| 既有包源码 | `1b3fff97ecc7a90f1620df1527117b5ab0daa5ea` |
| 最终只读采集工具 | `e0ee94eab397744e4159777e725364bfc6815e78` |
| 最新只读批次 | `24ee83b1f014468dae2abb7c51d56672`，`pr6-identity-03.json` |
| 自动生成身份更正 | `PR6_IDENTITY_CORRECTION_03.md`；supersedes 早先本轮 02 采集范围，原文件保留 |
| 归档离线检查 | `pr6-archive-correction.json` / `PR6_ARCHIVE_CORRECTION.md`，仅归档，不代表现场 |
| 发布核对 | 以 `pr6-release-check-06.json` 为最终工具快照结果；此前结果全部保留 |

源码、构建候选、工具、报告和包提交分别记录，没有要求不同职责的 SHA 字面相同。工具验证候选与包提交的 Control/共享/Worker 相关源码等价；构建输入子集也相同。完整静态资源构建来源和 Worker 启动时加载摘要仍没有足够证据，不伪装为整个镜像或运行进程已验证。

## 已执行

- 镜像归档中 config → manifest → index 描述符关系和原始字节摘要已验证。旧 JSON 的 `image_config_id` 实际来自 Docker inspect Id，命名与对象不符；新报告明确区分它们，不覆盖旧 JSON。归档证明 Markdown 中 config 数值具有依据，不支持“部署了错误镜像”的结论。
- 固定候选预期集与运行容器实际 Python 集合双向核对通过：26 个文件，没有 missing/unexpected/changed。宿主七项脚本/共享依赖磁盘源码通过；不能由此推断已有 Worker 进程加载版本。
- 采集前后检查容器身份、容器源码、宿主源码和 journal 稳定性；不可接受混合快照。
- 新批次只读，不认领旧操作：169 份历史 journal、本批次 0、其他批次 0、无法归属 0。批次私有清单保存在 Git 忽略的 `.runtime/pr6`。
- 两份旧 pending 只读查询：原 operation 回执均未命中，关联服务端 job 为 succeeded、对应 attempt 为 finished。原操作结果和根因仍不能确定，旧 journal 未删除、未改写。逐条内部身份保存在私有 `identity-03.historical.json`。
- 两组实际三组件均 running；控制库 applied/desired 分别 8/8、2/2，Gate closed，security_blocked=false，历史任务 recovery_required=0。宿主 mutation 记录为 idle。这些观测不构成 Gateway 活动和遗留子进程完整证明，也没有因此开放 Gate。
- 既有包 124 项原始字节校验和通过；四组件归档对象关联与提交源码检查通过；生产 profile 必需验收缺失，因此发布核对为 blocked。没有重打包或编辑既有包。

## 测试

最终部署工具全量：**222 passed，2 skipped，163 subtests passed，9.14 秒**。其中新增 27 个证据工具测试，覆盖对象类型交换、摘要链损坏、无 index 合法格式、双向集合、同数量不同路径、批次混入/缺失/变更、rejected/unknown 期望、独占文件、失败清单、源码虚报、秘密字段、候选替换及发布阻断。

新 CLI 输出元数据后，发布核对再次实际执行，checker_source_commit 与 checker_inputs 记录其独立来源。运行代码未变，未把此前 Control 310 passed 写成本轮重新运行；前端也未改、未重跑。两项跳过仍为跳过。

保留的非通过过程：

1. `pr6-identity-01.json`：Docker Linux 引擎管道不可达，结果 incomplete；没有启动 Docker 以绕过只读边界。用户启动后新建 02、03 批次。
2. `pr6-historical-disposition.json`：引擎不可达时只读磁盘检查，不能代表后续在线查询；03 私有记录追加在线观测。
3. `pr6-release-check-04.json`：新增 Git blob 核验首次使用原始字节比较，遇到既有 Git archive 的 Windows 文本 CRLF 导出差异。定位为文本换行差异；最终使用显式文本后缀等价策略，迁移脚本和二进制仍要求原始字节，包/镜像/归档摘要始终按原始字节验证。05/06 为调整后的新记录，04 未覆盖。

## 未完成与阻断

| 项目 | 状态 | 原因 |
|---|---|---|
| N3-E 工具与新证据内部一致 | 源码测试及本机只读采集通过 | 不等同所有退出门槛完成 |
| 历史 unknown 根因、残余风险批准 | blocked | 原回执未命中；负责人尚未书面接受，不由开发自动关闭 |
| 全部当前活动/遗留宿主进程责任 | 未完整验证 | 仅三容器、控制库与宿主记录，缺 Gateway 活动及实际子进程核对 |
| Worker 已加载来源、完整构建输入 | 未完整验证 | 现有启动记录无启动摘要，静态构建来源仍需完整绑定 |
| N4 预检 | blocked | 缺获准空目标、完整备份、基线、匹配密钥和 RPO/RTO 等资料 |
| N4 完整验收执行器与实机演练 | 待实现/未执行 | 本轮只有预检字段与步骤手册 |
| N5 画像 | blocked | 未批准目标、阈值、时长、范围和执行权限 |
| N5 真故障/混合负载执行器适配 | 待实施/未执行 | 不将已有合成测试称为真实强杀或丢响应 |
| PR-6 生产发布 | blocked | 必需项尚未通过 |

下一步是核对并补齐运行责任与启动来源证据，再由负责人确定历史风险和 N4/N5 目标及执行范围。本轮不自动恢复账号、不自动推送远端、不宣称生产可发布。
