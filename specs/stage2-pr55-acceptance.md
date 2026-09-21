# PR-5.5 验收记录（候选，未关闭）

本轮只进行隔离源码与协议测试；生产未发布、模型请求 0、未访问真实业务资料，PR-6 Not Started。

检查点 A：d64396cdd9f0daedc0823689fdc20f71ea7d6f2c。Control 600 passed；Stage 1 部署回归 36 passed / 10 subtests；PR-5 原提交严格检查通过。

B 的最终源码回归通过：Control 673 passed，Gateway 95 passed，部署与新交付检查器 98 passed / 10 subtests，Bun 插件 14 passed，原 PR-5 检查器 63 passed。全部无跳过；Control/Gateway 有 2 条既有 Starlette 弃用警告。40 条新增语料与原 21 条涉赌语料均通过。GitHub CI 尚未执行，不能以本地结果代替。历史已知测试中曾发现方法验证局部变量遮蔽 Profile，已修复并通过 107 项定向回归。语料中的明确跨 Agent 场景按 409 拒绝，与普通 unsupported 的本地澄清分别验证。

验收层次：Registry、准入/冻结、执行前校验、真实 Git 交付检查、GitHub CI。没有真实模型、A/B 页面或生产工具调用证据，不将它们标为通过。


## 验收用例映射

| 项目 | 自动化证据 | 判定范围 |
| --- | --- | --- |
| Registry 闭合、Prompt 路径、版本、方法、不可变 Hash | test_agent_registry.py | 内置配置启动校验 |
| 两助手方法范围、跨 Agent Skill、会话双向绑定、reset/开关回退 | test_multi_agent.py | 源码与真实 SQLite 准入 |
| TaskSpec/Profile/Prompt 冻结、升级不改旧 Run、并发幂等 | test_multi_agent.py | 不产生第二次受理 |
| 40 条固定表达及原 21 条涉赌语料 | stage2-pr55-agent-cases.jsonl / test_multi_agent.py | 固定合同，不是泛化准确率 |
| 车辆单项、盗窃三模块综合、HTTP 取数、编译、摘要核对、历史证据 | test_multi_agent_execution.py | 真实 Bun 入口 + 回环合成 HTTP + Control/Gateway 协议；Agent 消息身份读取使用测试替身 |
| Gateway 重启后未知模块不重发 | test_multi_agent_execution.py | 既有未知结果保护；不代表真实宿主崩溃演练 |
| 公开接口字段、非法 Agent、客户端伪造字段、错误账号/会话 | test_multi_agent.py | 鉴权与字段边界 |
| 源码漂移、伪造 CI、Hash/制品集、历史证据改写拒绝 | test_stage2_pr55_release.py | 真实临时 Git 历史；离线检查不认证 GitHub，需另核对远端 |

## 未执行与后续事项

- A/B 部署、生产镜像构建、线上开关启用：未执行。
- 模型请求：0；Prompt 内容及绑定通过确定性测试，模型是否始终遵守中文和事实边界未进行行为验收。
- 真实业务资料、并发/容量/持续压测：未执行。
- 前端 Agent 选择页面：本轮不开发；既有前端源码无修改。
- PR-6 Session Task Context、历史 Claim 解释与来源链：Not Started。不得把本轮 session_agent 绑定当作 PR-6 已完成。

## 回退

本轮源码尚未部署，线上无升级回退操作；原稳定分支与 d78451a 提交保留。未来若启用新路径，先关闭多 Agent 开关并排空活动请求，保留 theft 历史读取，不能将其重标为 gambling 或重发查询。恢复生产版本必须另行核验镜像和运行状态。
