# 第一阶段复核收尾修复回执

## 范围与基线

- 依据：《沛县公安涉赌 Agent 第一阶段完成情况复核报告 V1.0》。
- 修复基线：`d3420bbc0bf6bdb3869c2c9194572b829629a7cb`。
- 分支：`codex/seven-data-plugins`。
- 本轮只修改后端事实计划、Gateway 内部协议、测试、CI 与交付资料；未修改前端、个人 Skill 正文、插件发布包或现有账号数据。
- 未构建或发布新运行镜像，未更新现有冻结 Run。源码修复不等同于线上已生效。后续上线需要匹配发布 Control/Gateway，并核对现有账号状态。
- 保持 schema v6；不增加 TaskSpec、实体解析、真实案件授权或新的任务系统。

## 复核问题与修改

### P0：官方总流程精确授权

`facts_skill_registry.py` 使用官方发布清单中的完整 `methods` 数组，按内容哈希识别身份；`facts_plan.py` 展平去重并校验当前场景的方法集合。

| 总流程 | 方法 | 本轮允许模块 | 明确不允许 |
|---|---|---|---|
| 涉赌 | night、companions、funds、relations | night、portrait、funds、lookup、composite | calls、vehicle |
| 盗窃 | night、companions、vehicles | night、portrait、vehicle | funds、calls、lookup、composite |

没有有效方法、选择的 Skill 不存在或内容哈希不匹配，均返回 HTTP 409 `facts_method_identity_unavailable`。跨场景方法返回 `facts_method_outside_scenario`。禁用/未发布方法沿用 `facts_method_not_published`。

个人 Skill 不因显示名或文本关键字获得官方资料方法身份。混选无法识别的个人 Skill 时也不会扩大查询范围；需使用匹配的官方副本，不能回退到全部插件。`plugin_ids` 保持使用偏好语义。

### P1：Gateway 单独重启恢复

operation 现在保存 `control_boot_id`、`gateway_boot_id` 和 `last_heartbeat`。Gateway 每次内部事实请求携带自身 gate 的启动 ID；Control 核对已注册 Runtime 中的启动 ID，不能由调用方任意宣布新的身份。

- 同 Control、同 Gateway 的未结束 operation 继续互斥。
- 已注册 Gateway 身份变化后，旧 operation 可以被新启动实例回收；旧 `pending` 模块转为 `unknown`。
- 原模块不能再次 reserve，不因回收锁重发资料查询；已完成模块继续使用同 Run 的持久结果。
- 旧实例迟到的 authorize、complete、finish 均被拒绝，不能清理或覆盖新 owner。
- 原有 authorize 轮询同时维护心跳。仅心跳过期不会释放 owner，因为超时不能证明外部请求已经停止。
- 保留 Runtime 的原有安全核对/排空屏障。Gateway 重启不会仅凭本补丁自动重新开放入口；必须先通过既有 Runtime 注册、权限和状态核对。
- 新 Gateway 经 prepare 路径可以生成部分事实及 evidence；直接重取未知模块仍明确拒绝。

内部 `/internal/runtime/facts` 新增必填 `gateway_boot_id`。旧 Gateway 缺少字段返回 422，旧启动身份返回 409 `facts_gateway_changed`。升级必须匹配 Control/Gateway，不声称旧组件可无缝混用。这个字段不会加入浏览器消息接口，也不允许模型提供 Run 或 Gateway 身份。

### 发布记录与检查器

从服务器原始合成验收账本提取八条请求的唯一标识，确认八条均已受理并产生不同 Run。历史清单改为 `69 + 8 = 77`，补充请求标识、Run 标识及统计时点，并重新计算原五份交付文件 SHA256。没有调用模型补造证据，没有修改旧 Run。

新增 `deploy/peixian/stage1-release-check.py`：

- 校验 Run 计数、模型预算、请求/Run 唯一性、停用能力验证前后数量。
- 校验发布源码及组件源码是当前提交祖先。
- 从源码重新生成七个 ZIP 并核对摘要；核对官方 Skill 文本、清单与发布哈希。
- 校验 SHA256SUMS 完整集合及实际文件摘要。
- 校验记录中的 A/B ready、applied=desired、无恢复标记，以及旧插件安装/授权/启用均为零。
- `--check-images` 通过 Docker 检查镜像摘要实际存在。
- `--runtime-evidence` 要求额外提供最近 60 秒内采集的脱敏 Runtime 观测，与清单一致；不能将旧观测当作当前在线验收。
- 仅验证成功后 `--output` 才生成新清单，已有输出拒绝覆盖。校验失败以非零退出，不能产生“assembled”成功清单。

原发布清单依然描述 2026-09-20 的部署：Control 源码 `30755c9b2`、Gateway 源码 `c6dea1584`；不将本次源码修复伪记成旧镜像包含的内容。

### GitHub 专用门禁

新增 `.github/workflows/peixian-stage1.yml`，对本分支 push、PR 和手动触发运行。使用 Python 3.12、Bun 1.3.14，执行固定 HTTP 契约、事实计划/持久化/Gateway 跨组件、迁移、运行模板、发布一致性及插件入口测试。

CI 使用合成服务，不需要模型/API 凭据，不访问现有站点。完整历史 checkout 支持源码祖先校验。GitHub 检查结果需以推送后的 Workflow 实际状态为准；加入 Workflow 不等同于已设置仓库分支保护的 required check。

## 本轮验证

| 验证 | 结果与边界 |
|---|---|
| 基线反例复现 | 隔离加载旧提交三个模块；总流程精确范围、修改正文拒绝、Gateway 独立重启恢复三项均按预期失败，确认测试能捕获旧问题 |
| 核心链路定向回归 | 49 passed，含真实本机 HTTP 合成资料服务、Bun 插件和事实编译器；不是模型验收 |
| Control 全量回归 | 514 passed；测试收集后新增的无参数恢复用例在下一组单独验证 |
| Gateway 全量及新增恢复用例 | 92 passed，初始四项因未显式指定 Bun 路径跳过，随后显式指定 Bun 补跑 7 passed，覆盖全部四项初始跳过 |
| 部署模板 | 23 passed、10 subtests passed |
| 发布检查器反例/一致性 | 13 passed，包括坏源码、坏 ZIP 摘要、坏 Skill 哈希、坏文件 SHA 时禁止生成输出 |
| 插件入口 | Bun 14 passed |
| 历史发布清单与镜像存在性 | `--check-images` 通过；只证明已有镜像存在，不证明当前正在运行 |

初始宿主 Python 3.11 不支持仓库使用的 SQLite API，改用已有 Python 3.12 测试镜像完成运行时回归，没有为通过测试降级数据库代码。测试镜像未安装 Git，发布验证改在有 Git 的宿主环境执行；CI runner 提供 Git。保留依赖库弃用警告，没有将其隐藏或记作依赖升级完成。

本轮未调用付费模型，未改变 29/40 的上轮记录；未执行真实用户操作、生产资料查询、并发测试、现有站点升级或浏览器验收。

## 使用与上线注意事项

在仓库中运行：

```bash
cd deploy/peixian
python stage1-release-check.py
python stage1-release-check.py --check-images
python stage1-release-check.py --output /safe/new-release.json
```

上线需备份、等待当前活动结束，匹配更新 Control/Gateway 并完成 Runtime 状态核对，再测试新建 Run 的精确范围。既有 Run 的加密计划不重新解释；若旧 Run 尚未结束，应按既有取消/排空流程处理，不覆盖其历史身份。恢复到旧源码会恢复旧 P0 问题，不能作为修复后正常运行方案。

保留前端同事未提交的源文件及产物。本轮仅提交明确列出的后端、测试、CI 和文档，并按用户授权推送同一 GitHub 分支。
