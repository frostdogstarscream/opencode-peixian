# PR-5.1 开发回执与验收记录

日期：2026-09-21。依据《沛县公安涉赌 Agent PR-5.1 修改计划 V1.0》。

## 状态与源码身份

PR-5.1 源码修复和独立回归已完成，当前为候选，等待本次 GitHub CI 和最终证据闭合；此提交不声明 PR-5 已关账。

- 开发分支：`codex/stage2-task-spec-v1`。
- 第一阶段基线：`ecefc20a01949b0ebd7f5c966608cf6762d310c9`。
- PR-5 原实现：`458e56ad9b716c74ba37506542cec2a84b761c78`。
- 本轮起点：`e59715edaa4079d17d0345d71700d597a38dea79`。
- PR-5.1 实现提交：候选提交创建后在文档关账中固定。
- 原 PR-5 CI 已核实为成功：[35576609130](https://github.com/frostdogstarscream/opencode-peixian/actions/runs/35576609130)，其 head 为 e59715e；不作为本轮修复的成功证据。
- 本轮 CI：尚待候选提交推送后执行。

服务器独立工作树 `/root/PeiXianDB/stage2-task-spec-v1` 开发。未修改 `frontend-alignment` 中同事的前端工作，未更改运行镜像、A/B、账号配置、Skill 正文或插件包。数据库保持 schema v6。没有部署，没有新增模型或真实资料请求。

## 完成的四项修复

1. API 入口和 Run 事务内共用 admission_selection。非查询忽略残留 Skill/Plugin 作为准入依赖，原 request 和 Invocation.selected_* 保留不变；实际能力为空。新查询仍严格检查固定计划依赖。
2. Router 不再因 selected=True 判为数据任务。新增整理、统计、列出、展示动作词；已经判定为查询时，所选官方 Skill 才可补齐方法。请说明一下、你好、什么是资金流水保持普通聊天。
3. 新增严格离线交付检查及 63 项真实临时 Git 历史负向/正向测试。检查源码漂移、祖先关系、版本、CI 记录格式、测试数量、21 条语料及五份文件的精确 SHA256 集合。失败不写输出，已有输出不覆盖。
4. CI 增加 Gateway 完整回归、新交付检查测试及 Verify PR-5 delivery evidence。最终源码 SHA 和真实成功 Run 由后续纯文档提交固定。

非查询不附加插件优先使用提示。explain_existing/clarify 产生本地答复，无 delivery；普通聊天允许模型投递但关闭全部工具，不能把“普通聊天零取数”写成“普通聊天零模型”。历史解释尚未实现 PR-6，history_unavailable 只表示明确告知缺口。

## 独立回归结果

| 测试组 | 本轮结果 | 证据范围 |
|---|---|---|
| Control 全量 | 583 passed，0 skipped | 真实 SQLite、HTTP 受理、任务、权限、事实、取消和幂等；包含 TaskSpec 66 项 |
| Gateway 全量 | 95 passed，0 skipped | 入口活动、协议、出口、上传解析及取消 |
| 部署/交付 | 99 passed，10 subtests passed，0 skipped | seven_runtime、console_runtime、stage1_release、stage2_pr5_release |
| 七插件 Bun | 14 pass，0 fail，0 skipped | 固定模块、健康检查、不匹配响应拒绝 |
| Router 语料 | 21 条全部通过 | 由源码测试和交付检查分别执行；不是开放中文准确率评测 |
| 第一阶段历史清单 | validated=true | recorded-evidence，不代表在线验收 |
| 格式和凭据模式检查 | 通过 | git diff --check；差异中常见密钥/私钥模式未检出 |

Control/Gateway 使用禁网测试容器，Python 3.12、2 CPU/2 GiB；镜像 ID `sha256:fe27c561ce1dafcfd3ee846c68e98cab9707d24eab63219101f33ccc1717c08d`。部署检查使用现有隔离 Python 环境与真实临时 Git 仓库。Bun 1.3.14。测试依赖存在 FastAPI/Starlette 弃用警告，无失败。

测试日志在源码目录之外保存；其 SHA256 记录于 release.json。集成链路使用合成 HTTP 数据和生产插件入口，Agent 身份读取使用测试替身；没有真实模型、页面交互、并发容量或线上发布验收。

## 关键用例

- 不存在/停用插件与历史解释、矛盾澄清、普通概念说明组合，HTTP 202；冻结原始选择，非查询 allowed/actual 为空，不写插件偏好提示。
- 普通聊天保持 queued/pending_dispatch；历史解释、澄清完成本地答复且无投递。无真实模型调用。
- 新查询所需 funds 停用，在入口及最终事务重新检查并拒绝，不创建 Run/delivery。
- 四种模式各四个并行相同请求只生成一条 Run/Invocation；应投递者只有一条 delivery，同键不同内容 409。
- 21 条语料覆盖选 Skill 但不查询、通用动作补方法、无方法澄清、禁止刷新、矛盾及不支持范围。
- 交付负向测试覆盖假的 CI 标记、失败/跳过状态、非法 run_id/SHA、不相干祖先、全部固定实现文件漂移、版本不符、负数/布尔数量、语料篡改、哈希缺失/多余/重复/路径越界/符号链接、输出覆盖。

## CI 与提交先后关系

实现提交先使用明确标记 pending 的候选清单，CI 调用 --candidate，只输出 candidate_only。默认严格命令拒绝候选；不得以此宣布完成。获得该实现提交的真实 CI 成功后，文档提交写入 implementation_revision 和 github_ci，切换 completed，由默认命令验证。文档提交也必须通过 CI。

这是防止预先伪填自身 SHA 或未来 CI 的先后处理，不放宽最终交付检查。离线工具不连接 GitHub；CI 真实性必须另行通过 GitHub API 与链接核实。后续文档 commit SHA 在 Git 历史和交付回执提供，不要求文档记录自身哈希。

## 复现命令

在 services/peixian-control：

```sh
PX_BACKEND_V6=0 BUN_EXECUTABLE=/path/to/bun PEIXIAN_TEST_JS_COMMAND='["/path/to/bun"]' python -m pytest tests -q -p no:cacheprovider
PX_BACKEND_V6=0 BUN_EXECUTABLE=/path/to/bun python -m pytest gateway/tests -q -p no:cacheprovider
```

在 deploy/peixian：

```sh
PX_BACKEND_V6=0 python -m pytest tests/test_seven_runtime.py tests/test_console_runtime.py tests/test_stage1_release.py tests/test_stage2_pr5_release.py -q -p no:cacheprovider
python stage1-release-check.py
python stage2-pr5-release-check.py
python stage2-pr5-release-check.py --output /safe/new-pr5-validation.json
```

在 deploy/peixian/examples/seven_data_plugins 执行 `bun test plugin.test.mjs`。五份交付物及 SHA256SUMS 位于 specs；OpenAPI 字节未变，不伪称本轮重新从线上导出。

## 保留边界与下一步

- PR-5.5：Not Started。下一轮为多 Agent 轻量通用化，不在本轮实现。
- PR-6：Not Started。未建设历史 Claim、双 Run 来源链或完整 Session Task Context。
- 第一阶段匹配镜像与 A/B 在线关账仍是独立部署前置项。
- Stage 2 Deployment：Not Performed。Model Requests：0。Real Business Data Access：0。
- 默认白名单保持关闭，本轮不新增生产镜像，不修改数据库版本，不访问真实资料，不做并发测试。
- 用户已授权本轮提交推送 GitHub；推送代码不是发布服务器应用。
