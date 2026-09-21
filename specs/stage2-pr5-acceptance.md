# PR-5 开发回执与独立验收记录

日期：2026-09-21。依据《第二阶段实施方案 V1.1 修订版》。

## 交付状态

PR-5 源码与确定性测试已完成，等待独立审阅。尚未发布、未进行 A/B 灰度，未启动 PR-6。当前代码不能被表述为第二阶段整体完成。

- 基线：`ecefc20a01949b0ebd7f5c966608cf6762d310c9`。
- 开发分支：`codex/stage2-task-spec-v1`。
- 实现提交：`458e56ad9b716c74ba37506542cec2a84b761c78`；后续交付文档提交不改变实现。
- 独立工作树：`/root/PeiXianDB/stage2-task-spec-v1`。
- 原 `frontend-alignment` 工作区的前端改动、运行数据、账号配置均保留。本轮未修改前端源码、Skill 原文和插件发布包。
- schema v6 保持不变；新增状态仅为现有 Run 的 phase，不增加业务状态枚举或数据库表。

## 已完成

1. TaskCandidate/TaskSpec 闭合契约；先 query_mode，再方法。普通对话、明确不重新查询、矛盾请求不能因选了 Skill 而开始取数。
2. 固定意图到方法映射，未知不回退总流程；明确总流程可收窄，专项与问题冲突则澄清。
3. 自动发现账号已有官方副本，校验正文身份、启用、实际应用版本和依赖。没有自动复制、安装或启用。
4. 场景主对象与精确 record_filter 分开校验，未知对象不替代；当前账号会话之外的对象来源不能用于本轮解析。
5. 冻结加密任务、配置版本与固定计划；受理事务中重新核对，同请求重放保持原任务；facts_plan 再验证意图、方法、目标和能力。
6. 澄清/历史解释占位使用确定性本地答复，零模型投递、零插件查询；完成表示路由答复完成，不表示资料查询成功。
7. 新增本人 Run `/task` 只读接口、OpenAPI 与消息/报告兼容投影。
8. Control/Gateway/证据/事件图使用同一目标筛选口径，原始响应保留在加密审计状态；没有修改历史结果。
9. 按账号白名单开启，默认关闭；新建 PR-5 CI 配置，但本轮没有推送，因此没有本轮远端 CI 执行结果。

## 最终测试结果

测试在服务器独立测试环境运行，使用临时控制库、无外网容器、合成 HTTP 服务。未访问真实业务接口、未调用付费模型、未更改在线 A/B。没有并发容量或持续负载验收。

| 测试组 | 最终结果 | 范围 |
|---|---|---|
| Control 完整回归 | 555 passed，0 skipped | 真实 SQLite、认证、任务受理、官方方法、作用域、事实/证据、取消、幂等；包含新增 PR-5 和旧 Stage1 回归 |
| Gateway 完整回归 | 95 passed，0 skipped | 入口活动、出口、上传解析、协议、取消与现有安全边界 |
| 部署及历史交付检查 | 36 passed，10 subtests passed | seven_runtime、console_runtime、stage1_release |
| 七插件 Bun 测试 | 14 pass，0 fail | 固定模块、健康检查及不匹配响应拒绝 |
| 固定路由样例 | 16 passed | 数据/普通问答、query_mode、否定、冲突；不是开放中文路由准确率评测 |
| 第一阶段历史清单 | validated=true | recorded-evidence；没有核验镜像在线身份，不代表在线关账完成 |
| 补丁格式 | git diff --check 通过 | 本轮源码与文档 |

Control/Gateway 使用 Python 3.12 测试镜像 `sha256:fe27c561ce1dafcfd3ee846c68e98cab9707d24eab63219101f33ccc1717c08d`；它只是测试工具镜像，不是本轮发布镜像。单测试容器限制 2 CPU/2 GiB，无公网。Bun 1.3.14。存在 FastAPI/Starlette 测试依赖弃用警告，未声称依赖升级完成。

## 实际发现和修复

- Agent 提示词绑定会附加元数据并修改上下文对象，曾造成 TaskSpec 复核误报变化；受控任务与 Agent 元数据改用分离对象。
- 新增目标筛选时，编译器读取 `facts` 而非 `context_facts`。初次完整回归发现原主对象身份背景可能残留；已清理正确字段，并检查模型原始 items、事实 subject_ref、卡片来源及事件图来源均符合目标范围。
- 未知姓名不一定含“的”，不能只匹配“张三的资金”；采用保守固定语法，未知残余不静默替换主对象。
- 明确不重新查询优先于所选副本状态；不能因用户仍选已停用 Skill 而重新取数。
- 官方副本不仅比正文，还校验实际生效版本，避免内容相同但未应用的新版本被提前使用。

集成测试真实执行合成 HTTP 服务、生产插件 JS、Gateway、Control 与事实编译器；Agent 消息身份读取使用测试替身，未运行真实模型。因此只能证明受控链路与结构/来源校验，不能证明真实模型自然语言行为或前端实际交互。

## 复现

在 `services/peixian-control` 包目录、Python 3.12 及已安装依赖环境执行：

```sh
PX_BACKEND_V6=0 BUN_EXECUTABLE=/path/to/bun PEIXIAN_TEST_JS_COMMAND='["/path/to/bun"]' python -m pytest tests -q -p no:cacheprovider
PX_BACKEND_V6=0 BUN_EXECUTABLE=/path/to/bun python -m pytest gateway/tests -q -p no:cacheprovider
```

在 `deploy/peixian` 包目录执行：

```sh
PX_BACKEND_V6=0 python -m pytest tests/test_seven_runtime.py tests/test_console_runtime.py tests/test_stage1_release.py -q -p no:cacheprovider
python stage1-release-check.py
```

在 `deploy/peixian/examples/seven_data_plugins` 执行 `bun test plugin.test.mjs`。固定路由样例位于 stage2-pr5-routing-cases.jsonl，逐条调用 task_router.parse 对比 query_mode/intent。

## 明确保留的缺口

- 第一阶段匹配 Control/Gateway 发布与 A/B 在线关账依旧是独立前置项；没有用历史清单检查代替在线验收。
- PR-6 历史 Claim、双 Run 来源链与完整 Session Task Context 尚未实施。PR-5 只识别解释意图并明确停止，不伪称解释完成。
- PR-7 对象候选、澄清选项写接口与幂等尚未实施；当前保守澄清要求提交新的明确请求。
- PR-8 Result V2、数据使用状态及自由说明冲突核对，PR-9 评测与 A/B 灰度未实施。
- 未构建/发布新运行镜像，未做浏览器视觉验收、真实模型验收、真实业务接口、容量压测。
- 本轮真实模型请求 0 次，未消耗模型预算；不得把此前账本未核对的余额作为当前承诺。

## 文件

stage2-pr5-contract.md 为接入说明；stage2-pr5-openapi.json 从该源码的临时 schema v6 控制库导出，非线上抓取；stage2-pr5-routing-cases.jsonl 为可复现样例；stage2-pr5-release.json 记录源码和测试证据身份；stage2-pr5-SHA256SUMS.txt 校验交付文档。

审阅通过后再进入 PR-6。本轮不自动推送 GitHub、不直接发布。
