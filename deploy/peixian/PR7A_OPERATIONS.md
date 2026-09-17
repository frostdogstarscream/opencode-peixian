# PR-7A 按需助手：使用与本机验证说明

本轮只交付显式启停。容量等待、自动休眠不启用。旧部署保持原有创建即开通行为；账号、卷和凭据不自动迁移。本说明不构成生产上线批准。

## 用户操作

按需部署中新建普通账号不占运行名额。完成首次改密后，用户可以编辑个人技能、配置获授权插件、查看授权模型和个人设置。点击顶部“启动助手”申请运行名额；环境与入口核对完成后才能发送消息、上传文件或测试插件连接。

名额满时显示明确提示，用户稍后手动重试，不自动排队。点击“停止助手”会停止新任务准入，等待已有活动结束后停止环境；文件、会话和个人配置保留。启动仍在排队时显示“取消启动”，请求绑定当时任务与状态版本，迟到请求不会停止后来新启动的环境。

同账号换浏览器访问同一环境。点击按钮后结果不明时先刷新状态，不重复自动提交；输入草稿不会因环境启动而自动发给模型。

管理员启用账号只恢复登录资格。超级管理员的环境暂停是独立人工禁止，普通用户无法用自己的启动按钮绕过，也不能用停用／启用账号清除。普通管理员仍不获得环境维护权限。

## API / Python

统一路径 `/api/console/v1/me/runtime`。GET 不访问 Gateway。start 接受空 JSON；stop 要求 `expected_state_version`，取消具体启动另传 `start_job_id`。两个写接口都要求 `Idempotency-Key`，普通 Cookie 请求仍需 Origin 和 CSRF，Python 使用本人令牌。

异步任务受理返回 202，已就绪或无需宿主操作返回 200；重放维持首次返回语义。重放后应 GET 当前状态，不能把历史 202 当作当前已运行。容量满返回 409 `runtime_capacity_full`，旧状态停止返回 409 `runtime_state_changed`。

`services/peixian-control/examples/console_client.py` 新增方法：

```python
state = await client.runtime_status()
accepted = await client.start_runtime(idempotency_key="my-start-request-001")
# 按有限频率查询 runtime_status，ready=true 后由调用方明确决定下一步。
state = await client.runtime_status()
stopped = await client.stop_runtime(state["state_version"],
                                    idempotency_key="my-stop-request-001")
```

这段示例展示三个独立操作，不建议业务代码在启动后立即停止。客户端不会自动重发旧问题，不提供任意上游地址转发。

## 配置、模式和版本

独立示例：`server/platform.on-demand.example.json`，配置 v4、schema v5、2 个运行名额，示例端口 19447/14098、独立数据目录与网络池。实际使用前须检查端口、网络、资源预算、证书和镜像身份。候选镜像标签尚未构建，本轮不能直接当成已有离线镜像。

旧配置 v1/v2/v3 不自动启用新模式。配置 v4 中 runtime_pool 为 on_demand，两个未来开关只能为 false。Control 启动时只初始化或核对数据库中的持久模式，不覆盖它。已有数据库模式与部署配置不一致会拒绝启动。

| 项目 | 本轮契约 |
|---|---|
| 新模式配置 | v4，single-host-on-demand |
| 数据库 | 完整 v5；历史 v4 脚本未修改 |
| Worker 协议 | 2，要求 runtime_pool_v1 及 on_demand 模式声明 |
| Gateway / Relay | 原门控协议 2 |
| 自动休眠能力 | 不声明 idle_activity_v1 |
| 运行名额 | 独立于注册账号数量，仍受内存和 CPU 预算约束 |

已检查原生 `managed-activity.ts`、Gateway `admission.py` 和 `runtime_management.py`：现有 boot、计数和 running/finished 条目支持排空核对，但没有完整的“同 boot 活动代次＋任务完成后空闲时间”契约。本轮不据此开启自动休眠；7C 仍需补齐来源和观测验收。

## 迁移、备份与回退

新空目录可显式初始化 v5。已有 v4 库不能因换镜像就自动迁移：需要另行批准的离线窗口、匹配全量备份和空目标恢复证据、冻结维护、停止旧写入组件、解决执行责任，才可启用 `PX_ALLOW_V5_MIGRATION=1`。该变量仅是代码侧门槛，不能替代上述操作证据。本轮未对真实库设置它。

备份工具分别记录 Runtime 元数据和物理映射。没有执行过的账号可以没有宿主目录和卷；已经落地却丢失目录或卷时不能伪装成合法元数据账号。恢复撤销旧认证、保持维护冻结与 Gate 关闭，丢弃旧宿主清单有效性，不自动启动；未来等待申请恢复后需重新确认。

旧 schema4 镜像不支持 v5；不能降低 user_version 欺骗兼容检查。回退应使用兼容 v5 的完整版本集合，或经批准将升级前完整备份恢复到空目标。

## 验证范围

本轮使用临时 SQLite、ASGI 测试客户端和宿主命令替身；未操作真实 Docker 容器、现有账号库和卷。源码测试不代表容器实际启停、全量恢复或 50 并发已通过。

按附件，PR-7A 完整退出还需获准独立集成证明“5 账号、2 名额、2 套真实环境、其余仅元数据”，以及实际停止后数据保留。现有 PR6 发布阻断保留，后续运行证据必须绑定本轮源码、构建、工具与镜像身份，不能套用旧候选报告。
