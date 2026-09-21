# PR-5.5 多 Agent 接入契约

本轮基线：`d78451a26feff089f0ce1b7fea40f0ab482dd1d0`。独立分支：`codex/stage2-multi-agent-v1`。
实现为内置、只读、随源码版本发布的 Registry 与通用 Runtime，未提供在线编辑、任意模块加载、多 Agent 转派或前端切换页面。数据库仍为 schema v6。

## 1. 开关与客户端兼容

仅服务端同时将账号 ID 纳入 `PX_MULTI_AGENT_V1_UIDS` 与 `PX_TASKSPEC_V1_UIDS` 才启用多 Agent。缺少任一开关时新请求仅接受原 gambling/default；关开关不删除或重算历史 theft Run。

新客户端必须明确发送 `agent_id`。省略时兼容旧客户端，默认 `gambling-assistant`；原始请求规范化不补写该字段，保持既有幂等指纹。显式未知 ID 返回 422 `unsupported_agent`。客户端不能上传 Profile、Prompt、Hash 或 TaskSpec。

首个成功受理 Run 将会话绑定 Agent（包括普通聊天）。创建时在原短写事务内核对所有已有 Run，两个不同 Agent 并发竞争时只能一个绑定成功。场景 reset 不解除绑定。切换 Agent 必须创建新会话。无 `agent_profile` 的历史 Run，仅在原请求为空或 gambling 时识别为 legacy gambling；只读，不迁移。

## 2. 只读接口

沿用 `/api/console/v1`、现有 Cookie/CSRF 或个人令牌认证。以下接口仅本人普通用户可用，不开放匿名读取或管理角色私人空间。

| 接口 | 响应与含义 |
| --- | --- |
| `GET /agents` | `{items: AgentPublic[]}`；只列当前开关开放的内置助手 |
| `GET /agents/{agent_id}` | 单个 AgentPublic；不存在或未开放返回 422 |
| `GET /sessions/{sid}/runs/{rid}/task` | 原 run_id/task_spec/response，加可选 agent_profile、effective_system_prompt_sha256；旧 Run 可以为 null |
| `GET /sessions/{sid}/runs/{rid}/report` | 已终态报告包含冻结的 Agent ID、版本及 Profile Hash |

AgentPublic 白名单为 `id/name/version/domain/description/supported_intents`，不返回完整 Prompt、工具授权、连接、密钥或文件路径。

```json
{"id":"theft-assistant","name":"盗窃研判助手","version":"1.0.0","domain":"theft","description":"固定场景的夜间、同行共现与车辆资料核对","supported_intents":["night_activity","companions_check","vehicle_activity","integrated_analysis"]}
```

消息仍使用 `POST /sessions/{sid}/messages`，例：

```json
{"text":"看看车辆记录","agent_id":"theft-assistant","model_id":"本人已授权模型ID","skill_ids":[],"plugin_ids":[],"file_ids":[],"mode":"standard","client_request_id":"为本次请求生成的UUID"}
```

成功仍为 202 `{accepted,run_id,message_id}`。相同账号、会话、请求 ID、内容返回原受理；不同内容拒绝；重放不重新选 Profile，不再执行模型。普通聊天无 TaskSpec、无资料工具；澄清和暂未实施的历史解释为本地完成结果，无模型/插件投递。历史解释仍明确 `history_explanation_pending_pr6`。

## 3. 路由与固定方法

| Agent | 意图 | 官方副本 | 固定方法 / 模块 |
| --- | --- | --- | --- |
| gambling | night_activity | night | night / night |
| gambling | companions_check | companions | companions / portrait |
| gambling | funds_analysis | funds | funds / funds |
| gambling | relations_check | relations | relations / lookup+composite |
| gambling | integrated_analysis | gambling | night+companions+funds+relations / night+portrait+funds+lookup+composite |
| theft | night_activity | night | night / night |
| theft | companions_check | companions | companions / portrait |
| theft | vehicle_activity | theft | vehicles / vehicle（总流程只缩小，不扩展） |
| theft | integrated_analysis | theft | night+companions+vehicles / night+portrait+vehicle |

方法必须是本人已安装、启用、内容身份正确、依赖授权且 applied 生效的官方副本。Skill 选择不能扩展 Profile；共享 night/portrait 插件不赋予资金或关系方法。盗窃资金请求进入本地澄清；选择资金官方副本直接 409。任意人员、车辆、地点、时间范围不支持时不默认替换为场景主对象。

## 4. 冻结与执行约束

新路径采用 `peixian-router-v2`、`task-spec-v2`，历史/未启用路径保留 v1。

TaskSpec V2 增加必填 `agent_id/agent_version/agent_profile_sha256`。Agent Profile 元数据包括 schema_version、registry_version、id、version、domain、default_scenario_id、profile_sha256、prompt_sha256，冻结于 Run 加密快照。另保存最终 System Prompt 的 SHA256。

Profile Hash = SHA256（按键排序、UTF-8、不转义中文、紧凑 JSON + 换行 + Prompt 内容）；Prompt Hash 只覆盖 UTF-8 Prompt。Profile 更新只影响新请求。提交前重新核对身份，冻结之后执行不按当前 Registry 重新解释旧计划。

执行前核对 TaskSpec、固定计划、Run Profile、方法、场景及最终 Prompt Hash。Gateway 已有受控调用链向 Control 校验每个模块，未授权或计划外模块在取数前拒绝。文本、文件、Skill 内容和工具输出不能更改 Agent 身份或解锁工具。模型仍可能偏离叙述规则，提示词测试不等于真实模型行为保证。

主要错误：

| code | HTTP | 处理 |
| --- | --- | --- |
| unsupported_agent | 422 | 选择开放的助手 |
| session_agent_mismatch | 409 | 新建对应助手会话，reset 无法切换 |
| agent_scenario_mismatch | 409 | 请求场景与助手不符 |
| agent_method_not_allowed | 409 | 取消跨助手 Skill 或换会话 |
| agent_profile_changed | 409 | 受理期间 Profile 改变，重新确认后用新请求 ID 提交 |
| agent_task_mismatch | 409 | 执行身份无法核对，未查询资料 |

跨账号/会话读取 Run 延续 404。幂等键、429/503、未知结果不自动重发等原接口规则不变。

## 5. 安全语义与范围

两类 Prompt 均要求简体中文，明确事实、计算、缺口。时空接近不等于实施行为，同框不等于同行，同车牌不等于同乘，独行观测不等于单人作案，资金流水不直接称为赌资。不输出犯罪结论、嫌疑排名或风险分数。

`target_contract_profile` 区分 gambling-target-v1/theft-target-v1；`claim_profile` 仅冻结声明，不代表 PR-8 Claim 已实现。PR-6 上下文来源链、PR-7 澄清写接口、PR-8 Result、开放 Agent 平台均未实施。

## 6. 运维与交付

本轮不部署、不启用线上开关、不生成生产镜像、模型请求为零。将来部署需要另行协调静态资源和匹配镜像，不能仅推 Git 就认为站点升级。

关闭开关后 theft 历史可读，同一 theft 会话不能改用 gambling。若未来回退镜像，应先排空活动 Run；不得删除数据或将 theft 重新解释为 gambling。

原 `stage2-pr5-*` 文件与旧检查器保持不变，CI 在 d78451a 原始 worktree 验证。PR-5.5 单独提供 OpenAPI、40 条固定合同语料、验收记录、发布清单与 SHA256。固定语料不是自然语言泛化准确率。
