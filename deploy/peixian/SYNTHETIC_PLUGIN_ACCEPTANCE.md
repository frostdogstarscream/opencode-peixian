# 七项合成资料插件：工具链验收修复与结果

日期：2026-09-18；目标：`peixian-alignment-20260917`；服务器工作区：`/root/PeiXianDB/frontend-alignment`。

## 结论

七个工具已经真实注册，新的七请求验收全部通过，临时 Skill 清理完成。此前“未产生工具调用”的判断需要更正为“旧验收脚本只读取最后一条 assistant 消息，漏查前面的工具调用消息”。这不是本轮修复后才让工具能够调用。

## 根因与历史证据

旧 `wait_for_answer()` 只返回最后一条最终回答；`evidence()` / `safe_evidence()` 随后仅扫描该条消息的 parts。OpenCode 将工具调用及工具结果放在较早的 assistant 消息中，最终回答通常只有文本。

对保留的两次历史会话进行只读检查：

- 未挂载 Skill 的资金请求：`user → assistant(tool-calls: funds completed) → assistant(stop)`。
- 挂载模板的资金请求：`user → assistant(tool-calls: skill completed) → assistant(tool-calls: funds completed) → assistant(stop)`。

因此两次资金工具确实都成功执行；旧记录仍原样保留，不改写成七模块验收通过。

## 修改

1. 新增完整轮次验证器 `agent_acceptance_evidence.py`，只读取当前 user 消息之后的 assistant 链，避免旧会话结果串用。
2. 新增 `accept_registered_tools.py`。先读取两名 Agent 的真实注册目录、当前模型工具目录和权限；七工具均存在且允许时，才发起模型请求。
3. 每模块新建独立会话，明确要求先加载本次所选个人 Skill，再调用唯一对应的无参数资料工具。整个调用链必须正好是 `skill → peixian_get_*_records`，两项状态均 completed；校验 Skill 名称与空参数。
4. 通过仅在宿主验收脚本内使用的 Agent 内部认证读取本次会话真实结果，比较完整 items 与固定服务记录；校验 module、synthetic、snapshot_id、data_status、计数和分页标志。普通用户 API 没有新增原生接口透传。
5. 最终回答的 DEMO record_id 必须来自对应模块，同时包含合成资料、快照及完整性说明。原始凭据不写入报告。
6. 修正两份旧驱动的末条消息漏查，允许 Skill 调用，并为每条请求单独创建会话。原验收状态键仍禁止自动重跑。
7. 在服务器工作区 `platform-package.py` 增加 17 个明确的合成插件源码、契约、Skill、部署和测试文件白名单，未采用整目录拷贝。

## 新一轮真实模型验收

一次用户授权轮次，共 **7 条用户级请求**，A 四条、B 三条；没有自动重试。所有请求均通过当前已授权模型，不访问真实资料，不生成风险评分。

| 账号 | 模块 | 返回记录数 | 实际完成的资料工具 | 结果 |
|---|---|---:|---|---|
| alignment-a | funds | 5 | `peixian_get_funds_records` | 通过 |
| alignment-a | calls | 4 | `peixian_get_calls_records` | 通过 |
| alignment-a | portrait | 4 | `peixian_get_portrait_records` | 通过 |
| alignment-a | composite | 4 | `peixian_get_composite_records` | 通过 |
| alignment-b | night | 5 | `peixian_get_night_records` | 通过 |
| alignment-b | vehicle | 5 | `peixian_get_vehicle_records` | 通过 |
| alignment-b | lookup | 3 | `peixian_get_lookup_records` | 通过 |

每条资料工具调用之前均完成一次所选 Skill 加载。返回 `synthetic=true`、`snapshot_id=DEMO-SNAPSHOT-001`、`data_status=complete`。资金与车辆各有重复 record_id，校验完整数组时保留重复记录，不将去重后的 ID 数冒充返回记录数。

工具执行约 2.27～4.82 秒/请求，这只是本轮观察值，不是性能 SLA 或并发压测。

## 清理与回归

- 两个本轮临时 Skill 均删除，原有 Skill ID 保留，配置应用后两个运行环境均 ready。
- 没有修改已存在的个人 Skill、模型、插件安装参数或服务连接。新建的合成验收会话作为证据保留。
- Python：25 passed / 15 subtests passed，覆盖服务契约、插件 ZIP、完整消息链、旧轮次隔离、假记录、错误工具、错误 Skill、非空参数及离线打包逻辑。
- Bun 1.3.14：3 passed / 26 expectations，补跑七工具固定请求、错误响应关闭及健康检查专用测试。
- 17 个白名单源文件存在且通过打包器安全路径检查。

## 完成边界

本次通过的是 **明确指定 Skill 与对应工具的受控调用验收**。它证明七个真实工具链可工作，不等于已验证任意模糊自然语言下的自主工具选择准确率。

本轮没有重做完整控制台 UI 回归、并发测试、真实公安资料或业务系统联调。没有生成成套镜像离线发布包；交付的是插件相关源码修复包和白名单补丁，完整发行仍需匹配源码提交、镜像及发布清单。

工作在服务器工作区完成，本地原始项目文件未被覆盖；源码修复包可用于后续同步。本轮及上一轮未提交改动均保留，尚未创建 Git 提交或推送远端。

## 复现说明

在插件目录运行无模型回归：

```sh
python -m pytest test_records_service.py test_package_plugin.py test_agent_acceptance_evidence.py -q
bun test plugin.test.mjs
```

真实模型验收入口：

```sh
python accept_registered_tools.py --deployment-root /srv/peixian-alignment-20260917 --report /srv/peixian-alignment-20260917/seven-tools-chain-20260918.json
```

上述报告文件已经存在，脚本会拒绝再次执行，以免重复计费。不得通过删除报告文件自动重试；新一轮模型请求需另行明确授权。原始报告及现有会话保留，后续可只读复核。

证据文件：`evidence/synthetic-seven-tools-20260918.json`。其中包含每模块的实际调用链、记录引用、合成回答、清理结果和源码摘要，不包含账号密码、Bearer 密钥或运行环境凭据。
