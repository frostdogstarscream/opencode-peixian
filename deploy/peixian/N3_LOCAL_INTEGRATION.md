# N3 匹配候选的 Windows 本机集成记录

日期：2026-09-17。运行代码候选：`95896a843f2bd83dc0ee695713cf5dccbebbaad1`。

本记录补充 N3 源码回归之后的实际容器验证，不改写上一报告中当时未部署的事实。后续证据提交仅增加验证工具、报告和打包白名单，不改变运行代码。

## 范围与版本

- 只更新 `synthetic-r2-local`，入口 `https://127.0.0.1:19444`。原 14090 及原 A/B 未升级。
- 配置更新前已保存私密 `profile-before-n3.json`，通过原脚本确认 Worker 空闲后停止，再重建 Control、恢复管理网络、重新启动匹配源码 Worker。
- Control 标签：`agent-platform-control:worker-n3-95896a843`。
- Docker 运行镜像身份：`sha256:4d9d03022f03747df90bda78a203751ff224b5d8f68a68350638ac787b5a5b2f`。
- 镜像配置摘要：`sha256:77c12e51c3d9303782452662d6a2cdfa44c74ce6645e8138e8c070fb782fd442`。这是不同对象的摘要，不与镜像索引身份混用。
- Gateway/Relay、Agent、HTTPS Proxy 沿用已核验的原镜像；schema 4、配置 3、协议 2 不变。

## 本次实测

| 检查 | 结果与证据 |
|---|---|
| Control 重建与管理网恢复 | 2 个已登记 Runtime，2 个管理网重新连接；两个账号最终 ready/open |
| 实际运行文件 | 26 个 control/shared Python 文件逐一与候选 Git blob 比较（换行归一化），全部一致；Worker 源文件和共享诊断模块也一致。见 `reports/n3-local-evidence.json` |
| 保护内部诊断 | 未认证查询 403 且无内部诊断头；使用可信工作密钥提交错误协议的只读查询返回 409 / worker_protocol_mismatch |
| 三角色、原生回答、文件与隔离 | 两个真实 Agent 各完成合成回答；管理员无 Agent 且维护接口被拒绝；文本解析、跨账号文件与会话拒绝通过。见 `reports/n3-local-smoke.json` |
| 忙时配置发布 | A 回答期间保存个人 Skill，持久 defer=1；保持旧 applied，回答完成后才发布新版本。A 从 7/7 变为 8/8；B 保持 2/2；历史和文件保留 |
| N3 回执 | 本次具有 N3 阶段/版本字段的 13 份回执均 recorded，包括延期、阶段、启动登记和完成；没有把旧记录或单元测试统计当作此次实机回执 |
| 事件与撤销 | 两账号、三订阅共用各自上游；账号隔离、单令牌撤销、最后订阅回收和重入后历史补齐通过。单次撤销观测 0.328 秒，不是分位数或容量指标。见 `reports/n3-local-events.json` |
| 最终状态 | A ready/open 8/8，B ready/open 2/2；维护 normal，recovery_required=0 |

两份旧 journal 仍为未确认，本次保留并单列 `historical_unconfirmed_journals_not_resolved=2`，没有重新提交、删除或把它们标记为完成。历史 unknown 的具体原因仍未定位。

初版证据脚本把所有历史 journal 纳入本轮断言，因此触发 `unconfirmed_n3_receipt`；检查确认两份旧 pending 缺少 N3 阶段/版本字段。修正脚本为分别统计新旧记录后验证通过。这是证据范围修正，不是清理旧责任，也不是线上回执失败。

## 复现与交付

在仓库根目录使用本机虚拟环境；Docker CLI 必须在 PATH 中。所有输出文件必须是新文件。

```powershell
services/peixian-control/.venv/Scripts/python.exe deploy/peixian/r2-local-smoke.py --manifest deploy/peixian/.runtime/r2-local/manifest.json --output deploy/peixian/reports/n3-local-smoke.json
services/peixian-control/.venv/Scripts/python.exe deploy/peixian/r3-local-check.py --manifest deploy/peixian/.runtime/r2-local/manifest.json --output deploy/peixian/reports/n3-local-events.json
services/peixian-control/.venv/Scripts/python.exe deploy/peixian/n3-local-evidence.py --config deploy/peixian/.runtime/r2-local/profile.json --source-commit 95896a843f2bd83dc0ee695713cf5dccbebbaad1 --output deploy/peixian/reports/n3-local-evidence.json
```

源码测试沿用该候选已执行的 Control 310 passed；本轮新增脚本已实际执行。打包白名单变更后的部署全量回归重新执行：195 passed / 2 skipped，163 subtests passed，9.99 秒。没有改前端源码，不搬用旧候选测试充当新源码重跑结果。

交付包应从本轮证据提交归档源码，匹配上述运行镜像。必须核对 `source_matches_commit=true`、四镜像身份、SHA256SUMS；assembled 本身不是完整验收。包不含私密 profile、账号数据或凭据。

## 仍未执行

本轮没有实际进程强杀、网络丢响应注入、空引擎恢复、Linux 主机、大规模并发、持续负载或付费模型验证。丢响应和租约阶段失联证据仍来自 N3 确定性源码测试。本机两个账号验证不代表 50 并发通过；N4/N5 和 PR-6 完整退出条件仍保留。
