# 第二轮独立合成验收工具

当前执行范围已收敛为本机初步验证：两账号顺序检查使用 `r2-local-smoke.py`（参数以 `python r2-local-smoke.py --help` 为准）。下列 3/4 账号、公平性和 4 小时工具保留为后续可选能力，本轮不据此启动远端部署、并发或持续压力测试，也不声称这些场景已经实机通过。

`platform-manage.py up` 重建 Control 后，会在返回 `started` 前恢复已登记 Runtime 的管理网络连接。恢复使用本地 `state.json` 身份和实际 Docker 标签核验，要求管理网络为 internal 且账号、Runtime、部署归属一致；重复执行只确认现有连接。仅已暂停、实际三组件全停且历史网络缺失的记录可以跳过，其余缺失或未知情况返回 `runtime_management_recovery_pending`，由维护人员检查，不能报告启动恢复成功。Gate 的重新开放仍需当前 Control/Worker 协议完成观测与确认。

`r2-acceptance.py` 只接受一个配置版本 3 的独立部署和明确列出的 3 或 4 个合成账号。必须先由部署负责人创建这些账号并完成首次开通。每账号维持两条 SSE；工具不创建账号、不扩大容量、不构建镜像、不接触 A/B 旧环境，不自动重试模型或工具提交。Python 要求 3.11 或更新版本，安装现有 `requirements.txt` 即可。

私有 manifest 示例（所有凭据仅示意，不能写入报告或 Git）：

```json
{
  "deployment_id": "loadtest-r2-20260916",
  "config_file": "/data/agent-loadtest-r2-20260916/platform.json",
  "base_url": "https://127.0.0.1:19444",
  "control_url": "http://127.0.0.1:14096",
  "worker_key_file": "/private/console-worker.key",
  "fixture": {"url": "http://127.0.0.1:18996", "key_file": "/private/fixture.key"},
  "model_id": "control-model-id",
  "admin": {"username": "synthetic-admin", "password": "private-password"},
  "users": [
    {"label": "A", "username": "synthetic-a", "uid": "32-lowercase-hex", "runtime_id": "32-lowercase-hex", "token": "private-token"},
    {"label": "B", "username": "synthetic-b", "uid": "32-lowercase-hex", "runtime_id": "32-lowercase-hex", "token": "private-token"},
    {"label": "C", "username": "synthetic-c", "uid": "32-lowercase-hex", "runtime_id": "32-lowercase-hex", "token": "private-token"}
  ]
}
```

第 4 个账号使用标签 D。配置里的 `max_runtimes` 必须为 3 或 4，部署 ID 必须以 `loadtest-r2-` 或 `synthetic-r2-` 开头。Control 与 fixture 管理入口必须为本机 loopback；应用公开地址必须与配置一致。工具会核对 Control 协议标签、所有普通账号名单、每个 Runtime 的部署/账号/运行时标签和严格三个容器。fixture 上游模型必须使用 `synthetic-openai-compatible`，持久模型结果不得代表真实 DeepSeek 质量。

```bash
python r2-acceptance.py --synthetic-deployment --manifest /private/r2.json --scenario smoke --output /reports/r2-smoke.json --ca-file /private/ca.pem
python r2-acceptance.py --synthetic-deployment --manifest /private/r2.json --scenario fairness --rounds 10 --output /reports/r2-fairness.json --ca-file /private/ca.pem
python r2-acceptance.py --synthetic-deployment --manifest /private/r2.json --scenario versions --output /reports/r2-versions.json --ca-file /private/ca.pem
python r2-acceptance.py --synthetic-deployment --manifest /private/r2.json --scenario security --output /reports/r2-token.json --ca-file /private/ca.pem
python r2-acceptance.py --synthetic-deployment --manifest /private/r2.json --scenario restart --output /reports/r2-restart.json --ca-file /private/ca.pem
python r2-acceptance.py --synthetic-deployment --manifest /private/r2.json --scenario soak --seconds 14400 --output /reports/r2-soak.json --ca-file /private/ca.pem
```

所有输出必须为新文件；JSON 与同名 Markdown 只包含固定代码、合成标签和聚合数据，不记录地址、凭据、消息内容或数据库明文。工具执行前先查看命令与 manifest 对应的独立部署；没有 `--synthetic-deployment` 则不执行。

| 场景 | 实际行为与硬门槛 | 结论边界 |
| --- | --- | --- |
| smoke | 各账号各一个真实 API→Agent→Relay→fixture→持久消息短回答 | 协议与链路，不是模型效果 |
| fairness | 每轮先暂停 B/C；A 长回答待配置更新；B retry 重开已有环境、C resume；A defer ≤5 秒，B 在 A claim 后 ≤10 秒启动，C 在 B 完成后 ≤5 秒启动，B/C 执行各 ≤120 秒；默认 10 轮 | B 首轮明确是 reprovision，不冒称新账号开通；poll 观测存在最多约 0.3 秒误差 |
| versions | A busy/defer 后再写一次配置；第一已领取版本不被改写，最终 revision=desired | 未在每个 publish stage 注入崩溃 |
| security | 临时 Token 撤销后 ≤5 秒返回 401；普通账号管理接口 403 | 不等于账号/模型撤权取消与 4 秒 permit 全链通过 |
| restart | 对重新核验标签后的 A Gateway 重启，验证新 StartedAt 和随后完整短回答 | 仅 idle Gateway 重启；未覆盖 Control/Worker 每个 stage |
| soak | 至少 4 小时，3/4 个账号短回答及普通查询、每账号 2 SSE；≥1000 个普通 API 样本，汇总 p95 ≤500 ms、p99 ≤1500 ms、非预期失败 ≤0.1% | 样本不足即不通过性能门槛；按接口细分、资源与泄漏结论需配套采样 |

用 `platform-sample.py` 和独立 cgroup 证据补 CPU、内存、OOM、FD、连接、队列、Gate/lease 残留门槛；总测试负载受 16 CPU / 28 GiB 测试上限与 4 GiB 宿主保留约束。候选配置使用 shared CPU 预算、factor=2：每个 Runtime 的 3 CPU ceiling 保持不变，账面 CPU 需求为 `4 + 4×3/2 = 10`，其中 reserve=4 已包括 Control 和 Proxy 的 CPU；这只是接纳预算，不保证吞吐。

v3→v4 的完整停写备份/冻结/恢复、旧镜像拒绝，以及 claimed/draining/closing/applying/publish/complete 各阶段崩溃或丢响应须独立形成证据。单元测试或仅某一个真实场景不能填成整套实机通过。任一容量门槛失败都不得扩大到 50，报告固定 `capacity_50_verified=false`。DeepSeek 若另有授权，仅单独少量短请求，不属于此工具，禁止长时间付费负载。

fixture 还提供受限的基础插件协议能力：对 `r2-` 加 32 位随机十六进制标记配置 `{"tool":true}` 后，携带该标记的流式请求只会调用模型请求中已声明的 `platform_sample_records` 工具（支持插件命名前缀），收到对应后续工具消息后返回合成文本；不指定该模式则保持普通回答。`GET /records` 复用 fixture Bearer 鉴权，只返回最多 3 条固定合成记录，`/internal/fixture/stats` 提供 `tool_calls` 和 `record_queries` 计数。这里没有自动发布、授权或安装插件的 seed 命令；协议 fixture 的单元测试不能替代实际插件调用验收。
