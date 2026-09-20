# 沛县公安统一数据适配服务

本服务位于业务插件与现有公安数据接口之间，统一鉴权、请求格式、字段、分页、错误、审计标识和脱敏规则。默认使用脱敏合成数据，只有显式设置 `PEIXIAN_ADAPTER_MODE=legacy` 后才会访问已配置的旧接口。

## 本地启动

```powershell
cd services\peixian-data-adapter
python -m pip install -r requirements-dev.lock
$env:PEIXIAN_ADAPTER_MODE = 'mock'
python -m uvicorn app:app --host 127.0.0.1 --port 8091
```

访问 `http://127.0.0.1:8091/docs` 查看接口；`GET /health` 用于 Service Connection 和插件连通测试。

此 Compose 文件默认仅将端口发布到宿主机回环地址，适用于本地开发。PR7C 的插件请求由账号 Gateway 发出，Gateway 没有普通公网出口，只能访问该账号的隔离管理网络。测试服务器启动容器后，先预览、再显式接入已有运行时网络：

```powershell
python attach_runtime_networks.py --deployment <部署标识>
python attach_runtime_networks.py --deployment <部署标识> --execute
```

Service Connection 的 Base URL 使用 `http://peixian-data-adapter:8091`。每当平台创建新的账号运行时，都要重新执行预览和接入；脚本只选择带平台托管标签、内部属性和合法运行时标识的 `px-*-management` 网络，不创建、删除或断开网络。正式环境也可由运维将同一动作纳入运行时创建流程。

测试服务器使用 `compose.server.yaml`，它不发布宿主机端口，以只读文件挂载密钥，并启用只读根文件系统、能力清空和 `no-new-privileges`。启动示例：

```bash
PEIXIAN_DEPLOYMENT_ROOT=/srv/peixian-alignment-20260917 \
  docker compose -f compose.server.yaml up -d
python attach_runtime_networks.py --deployment peixian-alignment-20260917 --execute
```

## 真实接口模式

生产或测试服务器必须配置 `PEIXIAN_ADAPTER_TOKEN_FILE` 和独立随机的 `PEIXIAN_AUDIT_HMAC_KEY_FILE`，将权限为 `0600` 的宿主机密钥文件只读挂载到容器，并由平台 Service Connection 以 Bearer 方式调用。所有敏感配置都支持同名 `_FILE` 变量（例如 `PEIXIAN_FAMILY_APP_SECRET_FILE`）；仅在本地开发时才使用不带 `_FILE` 的环境变量。审计日志仅记录数据域、结果、耗时、条数、错误码、trace ID 和 HMAC 人员摘要，不记录证件号或请求体。支持的变量见 `../../specs/peixian-data-plugin-field-mapping.md`。内部 HTTPS 使用私有 CA 时，通过部署覆盖文件将 CA 挂载到容器，并将 `PEIXIAN_UPSTREAM_CA_FILE` 指向容器内路径。

未配置正式 URL 的接口返回 `CONTRACT_NOT_READY`，不会退回 Mock 数据。不要将真实凭据写入 `.env` 后提交，也不要开启会记录请求体的访问日志。
