# 控制层合成负载工具

`control_layer_load.py` 只验证单进程 Control 的并发基础。它使用真实 Uvicorn 回环 TCP、SQLite WAL、账号令牌校验、密码验证、消息读取、SSE 注册和撤销路径；Gateway 及模型生成使用 `httpx.MockTransport` 合成。客户端和服务端运行于同一 Python 进程的事件循环。

**它不能证明 50 个真实 Agent / 150 个容器、模型吞吐、实际 Gateway 网络连接池、目标服务器容量或生产持续稳定性通过。** JSON 内记录这条证据边界，不将合成生成计数描述为真实模型并发。

## 短时检查

从 `services/peixian-control` 目录，使用已安装此服务依赖的 Python：

```powershell
.venv/Scripts/python.exe -B benchmarks/control_layer_load.py --stage-seconds 10 --output <新的脱敏报告路径.json>
```

Linux 使用 `python3` 替代上述解释器路径。默认分 10、20、35、50 账号逐级运行，各账号 2 条 SSE；消息最多每 500 毫秒读取一次、会话每 2 秒、身份和健康每 5 秒、目录每 30 秒读取，使用分散相位避免人为同步全部浏览器定时器。模型回复只是小型合成消息，每 250 毫秒产生原生事件。

工具预置独立临时数据库及合成账号，不调用 Docker、不连接外部模型、不读取现有账号资料。只有一次初始化密码哈希用于账号预置；实际 Cookie 登录及密码更新另经 HTTP 验证。浏览器工作流负载和这些初始化操作分开统计。

报告包含每阶段各接口的 p95/p99、返回码、并发读取峰值、SSE/上游/owner 峰值、合成生成数、交叉会话访问、49 个其他账号继续读取时的令牌撤销延迟，以及清理后的计数。超过 50,000 个样本时采用固定种子、有限大小的采样池，报告 `sample_count`。失败也保存已完成阶段及数据库拒绝计数，不将过载隐藏为通过；不覆盖已有报告文件。

`control_fixture_passed` 只表示指定合成场景的状态断言通过；默认各已采样接口 p95 ≤ 500 毫秒、p99 ≤ 1500 毫秒，统计客户端收到完整响应正文的耗时；可通过 `--p95-ms` / `--p99-ms` 显式调整并记录报告。空样本接口保持未测，不补造分位值。短时通过不代表四小时测试已执行。

## 长时间人工验收

```powershell
.venv/Scripts/python.exe -B benchmarks/control_layer_load.py --stage-seconds 3600 --output <新的四小时报告路径.json>
```

四阶段各 1 小时，另有环境准备和撤销检查时间。此命令是可执行入口，不能因文档存在即将四小时结果标为通过。增加压力可以显式调整 `--request-pause-ms`（消息周期）、`--gateway-delay-ms` 和 `--event-interval-ms`；实际值写入报告，不自动修改平台线程池或容量限制。

## 独立浏览器合成界面

先构建 `packages/peixian-console` 前端，再执行：

```powershell
.venv/Scripts/python.exe -B benchmarks/control_layer_load.py --serve-only --stages 2 --port 19490 --serve-seconds 900 --credentials-file <Git忽略目录中的新私密凭据文件.json>
```

只绑定 `127.0.0.1`，端口占用会失败，不接管现有进程。控制台加载本地 `dist`，包含两个合成普通用户和一个合成管理员。凭据仅写到显式指定的新文件，日志不输出密码；文件由调用方验收完毕后自行按本地私密文件管理方式处理。界面模式与负载模式不同，输出不会宣称执行过负载验收。服务到期自动停止；过程使用临时目录，退出后清理合成数据。
