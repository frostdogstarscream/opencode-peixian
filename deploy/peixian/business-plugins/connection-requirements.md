# 统一数据适配服务连接要求

在管理中心创建一个固定 Service Connection，并将所有业务插件的 `peixian_data` 别名绑定到该连接。

| 配置项 | 要求 |
|---|---|
| 根地址 | 测试服务器账号出口能够访问的适配服务 HTTPS 地址 |
| 鉴权 | Bearer，值与服务器 `PEIXIAN_ADAPTER_TOKEN` 一致 |
| 方法 | `GET`、`POST` |
| 健康检查 | `/health` |
| 允许路径 | `/health`、`/v1/person/*`、`/v1/police/*`、`/v1/mobility/*`、`/v1/vehicle/*` |
| 超时 | 首期 15 秒，真实接口压测后再调整 |
| 最大响应 | 首期 1 MiB，禁止无限放大 |

适配服务不得以 Mock 模式供业务用户使用。管理员应先调用 `/health`，确认返回的 `mode` 为 `legacy`，再授权正式测试账号。
