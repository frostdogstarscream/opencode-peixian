# 沛县 Agent 七项合成资料服务

此 Artifact 专供 `peixian-synthetic-records@1.0.0` 通过平台固定服务连接读取合成原始记录。它不使用控制台 `/api/console/v1` Mock，不连接真实公安业务接口，也不保存请求结果。

## 服务边界

- 仅支持带 Bearer 鉴权的 `GET /health` 和 `POST /v1/demo/records/query`。
- 查询请求仅接受 `{"module":"funds|calls|portrait|composite|night|vehicle|lookup"}`；筛选、分页、时间范围、条数和 `scenario` 一律拒绝。
- 返回记录均为 `DEMO-` 合成标识，且每个响应都包含 `synthetic: true`、`data_status: complete` 与来源快照标识。
- 默认仅监听 `127.0.0.1:19462`。部署到 Docker 宿主桥地址时，必须设置非公网的 `PEIXIAN_RECORDS_BIND_HOST`；服务拒绝 `0.0.0.0` 和 `::`。

## 私密运行配置

部署目录中的 `peixian-synthetic-records.env` 必须由运维创建并设为 `0600`，内容只包含以下运行参数。Bearer 值放在 `PEIXIAN_RECORDS_KEY_FILE` 指向的独立 `0600` 文件中，不写入此仓库、插件包或日志。

```text
PEIXIAN_RECORDS_KEY_FILE=/srv/peixian-alignment-20260917/peixian-synthetic-records.key
PEIXIAN_RECORDS_BIND_HOST=172.17.0.1
PEIXIAN_RECORDS_PORT=19462
```

平台服务连接仅配置这两个批准请求：`GET /health` 和 `POST /v1/demo/records/query`。连接测试只请求健康接口；七个插件工具各自固定提交一个模块名。不得将该服务直接发布到公网或把共享连接凭据当作真实业务数据授权。

## 本地验证与打包

```powershell
python .\test_records_service.py
python .\package_plugin.py --output .\dist\peixian-synthetic-records-1.0.0.zip
```

生成 ZIP 仅含 `manifest.json` 和 `entry.mjs`；`SKILL.md` 作为普通用户可复制的个人 Skill 模板，单独交付，不自动覆盖用户已有 Skill。


## 2026-09-18 验收规则版本适配

严格模型验收使用 `accept_registered_tools.py`，必须显式传入
`--fixture-profile enhanced`（50 条，DEMO-SNAPSHOT-20260918-01，demo-v1.1）
或 `--fixture-profile legacy`（30 条，DEMO-SNAPSHOT-001，demo-v1）。
未选择版本时在解析参数阶段拒绝执行。期望值来自指定的本地固定夹具，
不从待验收 HTTP 响应学习；报告记录夹具及底座源码 SHA256。

增强版执行命令（会调用付费模型；本次规则适配未执行）：
```sh
services/peixian-control/.venv/bin/python deploy/peixian/examples/peixian_synthetic_records/accept_registered_tools.py --deployment-root /srv/peixian-alignment-20260917 --fixture-profile enhanced --report /srv/peixian-alignment-20260917/seven-tools-enhanced-new-run.json
```
报告文件必须不存在。预检两名用户实际工具目录后才允许生成请求；
七请求不自动重试，首个失败停止后续请求，结束清理本轮复制的临时 Skill。

检查当前用户轮次的完整 assistant 消息链，要求先加载所选 Skill，随后完成
唯一对应的无参数资料工具。工具输出的 module、synthetic、snapshot_id、
data_status、计数、has_more、rule_version、rule_status 和完整 items 必须一致。
最终回答必须引用该模块全部 record_id；允许引用本模块结果中实际出现的
source_record_ids 等 DEMO 标识，拒绝未知或编造编号。source_type 使用既有
模块枚举，不要求 demo_ 前缀。旧夹具含重复记录，完整 items 比较保留重复项。

原七工具验收报告属于旧快照历史证据，不覆盖、不作为增强快照模型验收证据。
`verify_remote_synthetic.py` 是增强服务黑盒检查；`test_simulated_fixtures.py`
现已同时支持 pytest 收集与独立执行。两个旧模型驱动仅保留兼容性，正式七工具
判定以 `accept_registered_tools.py` 完整链检查为准。
