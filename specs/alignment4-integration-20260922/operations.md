# 第四轮联调部署维护说明

## 固定版本与工作区

- 业务入口：`https://36.134.45.38:19460/`。
- 生效源码：`40cb937a4cdc891aac1fabb10ada31c251ba1d49`。
- 正确开发及管理脚本根目录：`/root/PeiXianDB/stage2-task-spec-v1`。
- 原前端工作区 `/root/PeiXianDB/frontend-alignment` 的同事改动保留；不要再从该旧工作区直接调用旧版本部署管理脚本。
- 生效镜像：`agent-platform-control:alignment4-40cb937a4cdc`。
- 摘要：`sha256:d5318fc4e201e83318997a5da0c5306e91f0c56603f267c5d6a0f80647d51aee`。
- schema 9；此次不迁移数据库。Gateway、Relay、Agent 镜像不变，A/B applied 配置仍为 54/27。

## 根因与恢复

Control 重建后，账号动态管理网在 Worker 首次恢复探测时尚未接通，导致网关启动身份未知，旧任务以 `worker_boot_unregistered` 结束并保留恢复责任。仅首页和 Docker health 健康不足以判定账号可用。

本轮让 Worker 在恢复探测前验证并重接所属管理网；新增受保护的恢复重试接口，复用原冻结责任。实测还发现修复期间完成任务只会保持入口关闭，旧逻辑退出维护模式后没有重核队列；已补齐重新观测后再开放的路径。没有手写数据库状态、删除卷或盲目重放用户请求。

## 发布流程

以后发布前先协调前后端停止并行部署，备份源码差异、配置和控制库，确认没有活动 Run/宿主变更。通过正式 API 进入 `repair_only`，停 Worker，使用以下匹配脚本：

```bash
PY=/root/PeiXianDB/frontend-alignment/services/peixian-control/.venv/bin/python
ROOT=/root/PeiXianDB/stage2-task-spec-v1
CFG=/srv/peixian-alignment-20260917/platform.json
systemctl stop peixian-alignment-worker.service
$PY $ROOT/deploy/peixian/platform-manage.py up --config "$CFG"
systemctl start peixian-alignment-worker.service
```

`up` 执行镜像/schema 检查、控制卷升级备份、Compose 替换及管理网恢复。不要仅用 `docker compose up` 绕开这些步骤。恢复责任清零后退出修复模式；退出后还会短暂进行新的核对，等到两账号真实 `ready/open`、`recovery_required=0`、无安全阻断后再通知前端可用。

如果任务已经失败，需要超级管理员在修复模式调用 `/admin/recovery/{uid}`，传读取到的 `state_version` 与唯一 `Idempotency-Key`。不把旧回执当作重新开放依据，不循环自动重试不确定失败。

## 持久功能开关

平台配置新增可选字段，键只允许以下三项，值只允许去重后的32位小写十六进制账号ID列表：

```json
{
  "feature_scopes": {
    "task_spec_v1": ["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"],
    "multi_agent_v1": ["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"],
    "trusted_result_v2": ["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"]
  }
}
```

正式配置已写入原有 A/B 范围，渲染到 `PX_TASKSPEC_V1_UIDS`、`PX_MULTI_AGENT_V1_UIDS`、`PX_TRUSTED_RESULT_V2_UIDS`。不存在该字段时保持空授权默认值；升级时应先从当前已核实环境迁入原范围，不能只换镜像后让渲染清掉原功能开关。Control Dockerfile 的 schema 上限同步为9。

## 备份与回退

受限服务器目录：`/root/peixian-source-backups/alignment4-20260922-155512`，含原源码差异、前端归档、运行身份、部署配置与一致性控制库备份。私密配置没有放进 Git 和本次下载包。

本轮没有数据库结构变更。优先回退到兼容 schema9 的匹配镜像，并保留新增会话与文件。不要恢复旧数据库覆盖新增数据，也不要直接运行旧 schema6 脚本。原 frontend-alignment4 镜像存在恢复遗漏；若必须使用它恢复界面，应保留已修复的 Worker/管理流程并重新核对兼容性，不把它当成已经验证的整套回退版本。

验证依据包括代码回归、最终线上 A/B ready/open、管理网重接，以及候选后两次 Control 替换后恢复。未执行全量备份恢复演练或生产故障注入。
