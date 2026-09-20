# 测试服务器导入与验收

## 1 部署统一数据适配服务

将 `services/peixian-data-adapter` 构建为独立容器。首次仅用 Mock 验证链路；切换真实接口时设置 `PEIXIAN_ADAPTER_MODE=legacy`、`PEIXIAN_ADAPTER_TOKEN`、正式 URL、认证环境变量及内部 CA。不要把凭据写进 Compose 文件或镜像。

```powershell
cd services\peixian-data-adapter
docker compose build
docker compose up -d
```

该 Compose 端口只发布到宿主机回环地址。PR7C 的 Service Connection 请求实际从账号 Gateway 发出，而 Gateway 只连接该账号的隔离管理网络。不能将 `127.0.0.1:8091` 或宿主机回环地址填写为 Base URL。

在宿主机预览待接入网络，核对部署标识和列表后再显式执行：

```powershell
python attach_runtime_networks.py --deployment <部署标识>
python attach_runtime_networks.py --deployment <部署标识> --execute
```

脚本只连接带 `peixian.console.managed=true`、`peixian.deployment=<部署标识>`、合法运行时标签且名称为 `px-<runtime-id>-management` 的内部网络，不创建、删除或断开网络。每次创建新账号运行时后必须重跑；长期部署应把该动作纳入运维流程。

连接配置使用：

```text
Base URL: http://peixian-data-adapter:8091
认证: Authorization: Bearer <测试服务器秘密存储中的令牌>
允许方法: GET, POST
允许路径: /health, /v1/person/*, /v1/police/*, /v1/mobility/*, /v1/vehicle/*
```

部署后先从超级管理员的 Service Connection 测试调用 `/health`，再从授权用户执行插件测试。两处都成功才证明 Control 与目标账号 Gateway 均可访问适配服务。测试服务器的 Service Connection 必须使用适配服务地址，不能直连旧接口。

## 2 发布插件

超级管理员依次上传 `deploy/peixian/dist/plugins` 中的 5 个 ZIP。ZIP 根目录已经是 `manifest.json + entry.mjs`，不要再次套目录或手工修改。

上传后进入每个具体版本，将 `peixian_data` 绑定到统一适配 Service Connection。新版本不会继承旧版本绑定。

## 3 授权和启用

先只授权专用测试用户。用户在“我的插件”中选择 `1.0.0`，保留 `max_items=50`，保存并等待 Runtime Apply 完成，然后执行插件测试。

如新前端暂未暴露管理入口，可使用 `/api/console/v1`：

- `POST /admin/plugins`：multipart 字段名 `file`；
- `PUT /admin/plugins/{plugin_id}/{version}/connections`：保存 `peixian_data` 绑定；
- `PATCH /admin/users/{user_id}`：在保留原授权的同时加入插件 ID；
- `PUT /plugins/{plugin_id}`：用户选择版本、配置和启停；
- `POST /plugins/{plugin_id}/test`：从用户运行环境验证连接。

浏览器会话请求继续使用现有 CSRF 和幂等机制。不要通过复制文件到容器或数据卷绕过发布流程。

## 4 导入 Skill

插件目录中的 `SKILL.md` 是单数据域使用说明；`deploy/peixian/business-skills/*/SKILL.md` 是 5 个综合分析 Skill。通过“我的技能”导入，或由超级管理员创建模板后让测试用户复制。缺少正式数据依赖的综合 Skill 只能授权给 Mock 测试账号。

## 5 验收

验收必须同时看到实际工具调用、适配服务 trace ID 和与响应一致的结果。检查空数据、无效参数、超时、连接停用、版本升级、回退及未授权账号拒绝。模型仅声称“已经查询”不算通过。
