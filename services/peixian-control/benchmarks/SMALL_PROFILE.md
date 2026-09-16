# 1～2 账号真实环境资源画像

`small_profile.py` 为独立合成部署执行固定次数的真实控制台操作，用来与宿主 cgroup 采样时间窗对应。它不创建账号、不调整容器资源、不连接业务数据库，也不构成 50 路并发验收。

## 前置条件

- 仅在独立 `loadtest-*` 部署使用。提前开通一至两个 `loadtest-*` 普通用户，完成首次改密并签发独立令牌。
- 两个账号必须不同，令牌也必须不同。所有账号身份、就绪状态及所需授权在首次写入前检查。
- 模型阶段需要显式提供平台模型 ID。该模型必须已经获授权，不接受上游模型 URL。
- 插件阶段固定使用仓库 `deploy/peixian/examples/records-plugin` 的 `sample-records` 合成插件，账号只能启用这一项插件，且处于 `active` 状态。默认版本 `1.0.0`；测试其他合成版本时显式指定 `--plugin-version`。
- 合成插件的 `records` 服务连接必须由平台管理员绑定至独立合成接口。脚本不接受服务地址、任意 URL 转发或公共凭据。
- 先运行独立 cgroup 采样工具，再运行本工具。报告记录 UTC 开始/结束时间，便于对应容器 CPU、内存、OOM、重启与父级资源限制。

## 私密清单与 TLS

清单必须保存在 Git 忽略的私密目录，Linux 下使用 `chmod 600`。以下仅为格式示意，令牌占位值不能登录：

```json
{
  "base_url": "https://test.example:19443",
  "deployment_id": "loadtest-profile",
  "users": [
    {"username": "loadtest-001", "token": "px_PLACEHOLDER_001"},
    {"username": "loadtest-002", "token": "px_PLACEHOLDER_002"}
  ]
}
```

脚本默认验证服务器证书；自签环境通过 `--ca-file` 指定可信 PEM CA 文件，普通请求和 SSE 使用同一份信任配置，仍验证主机名。没有跳过 TLS 校验的选项。远程入口必须使用 HTTPS；HTTP 仅允许回环地址。

`examples/console_client.py` 也支持 `--ca-file`，Python 调用可传 `ConsoleClient(origin, token=token, ca_file=Path("ca.pem"))`。不传此项时保留原有系统证书校验行为。

## 分阶段执行

从 `services/peixian-control` 目录执行。`--output` 必须是尚不存在的文件，脚本在任何远端写入前拒绝覆盖已有报告。

```bash
python benchmarks/small_profile.py \
  --synthetic-deployment \
  --credentials /private/profile-users.json \
  --accounts 2 \
  --scenario answers \
  --model-id PLATFORM_MODEL_ID \
  --ca-file /private/ca.pem \
  --output /private/profile-answers.json
```

按下面顺序分别运行，使用不同报告名称，并让外部资源采样覆盖每个阶段：

| `--scenario` | 每账号最多执行的操作 | 证据边界 |
|---|---|---|
| `idle` | 观察 30 秒后检查身份与就绪状态 | 常驻空闲阶段；不是冷启动峰值 |
| `answers` | 新建一个会话，提交一次不少于 1600 字的合成长回答请求 | 新增已完成回答少于 1000 字时标为 `not_verified`，不自动补发 |
| `plugin-test` | 调用一次 `sample-records` 连接测试入口 | 验证插件测试链路；不是模型工具调用 |
| `tool` | 新建一个会话，提交一次要求实际调用合成工具的模型请求 | 仅统计本轮新增消息中的已完成工具及匹配的合成输出指纹 |
| `files` | 生成一个小 TXT，上传一次并等待解析 | 校验随机合成标记；不读取本机业务文档 |
| `events` | 建立一条事件订阅，观察 30 秒后关闭 | 不重连，提前关闭或无连接事件即失败 |

可用 `--file-type docx` 替换 TXT；DOCX 由程序从固定合成段落生成，不读取模板或外部文档。默认 `--scenario all` 顺序执行六阶段，当前阶段失败便停止后续阶段；同阶段两账号并行，已提交的操作不会因另一账号失败而被重复提交。仅一个账号时设置 `--accounts 1`。

默认任务超时 300 秒，可设置 10～900 秒。观察时间默认 30 秒，可设置 1～300 秒且不超过任务超时。程序没有无限压测循环；每次执行每账号每阶段只有一次提交机会。

## 结果解读与失败处理

- 报告只保存阶段时间、账号序号、耗时、计数、解析状态以及脱敏错误类型/HTTP 状态；不保存用户名、令牌、服务地址、正文、查询结果或上传内容。
- `tool` 检查本轮新增消息 ID，旧会话历史不会计入。公共消息将底层工具名称统一处理，因此还需核对 `source=示例资料服务`、版本和数量指纹。它是公共消息工具证据，需要与模型/出口证据结合，不能单独证明原始工具身份。
- 连接测试不等于工具执行成功，订阅数不等于同时生成数，长回答完成不等于目标模型吞吐通过。
- 写请求出现 429/503/504、网络中断或结果未知后不重放。SDK 对已确认接受且随后超时/取消的模型请求尝试停止；接受结果未知时先核对平台会话历史和运行状态，不直接重新运行该阶段。
- 程序结束后保留合成会话和上传文件用于核对，不自动删除远端数据。临时生成的本地文件自动清理。
- cgroup 总预算、容器内存峰值、CPU 限制、OOM、非计划重启、资源余量需要独立报告。本工具成功不能替代 16 核/32 GiB 的容量门槛或 50 组环境的分级验收。
