# 研判结果展示对齐与验收记录

日期：2026-09-18。工作区：frontend-alignment。基线：1bfd91f5b54d9a2f88877b5a9d35accae1b3dcc6。本次仅本地提交，不推送远端。

## 交付范围

继续集成工作区已有前端，不回退旧 Chat。为保留可构建的当前界面，本次同时保存原有 App/components/platform/types、FinalAdmin、CapabilityAdmin 集成改动；不把这些既有工作重复计为新增功能。结果区域采用浅蓝标题、五步过程、可点击核心结论、四张统计卡、右侧资料发现和详情抽屉。界面不展示风险等级，不引入截图的样例数量或结论。截图式目标画像、下一步建议不在本轮范围内。

证据接口保留原字段，新增 presentation。展示仅使用当前用户当前轮次已核对事实；模型自由文本及 analysis_result 不能成为可信卡片。合成属性、资料快照、场景快照及规则版本继续保留后台。未获取、失败、未知仍展示。

显示名称精确映射：涉赌案件资料整理（合成演示）／（代码核对演示）→涉赌案件资料整理；盗窃案件时空资料核对对应后缀→盗窃案件时空资料核对。只改显示，不修改 Skill 标识、原文、用户输入、会话存储。用户自己写的“合成”仍会出现在消息正文；非本轮历史结果不全局改写。

新插件 peixian-synthetic-records@1.3.0 增加真实执行时间轨迹，原事实编译规则不变。已按账号 A→B 顺序应用。旧版本结果没有时间时显示“—”。模板和原个人 Skill 未迁移；误复制的临时副本经内容核对后删除，原副本保留。

## 统计口径与实际读回

| 场景 | 夜间记录 | 明确同行人数 | 第三卡 | 第四卡 |
|---|---:|---:|---|---|
| 涉赌 | 2 条 | 1 人（2 条同行记录） | 3 条原始资金流水 | 4 条关系记录 |
| 盗窃 | 2 条 | 1 人 | 1 辆车辆（2 条记录） | 1 个有来源地点 |

同框不计入同行，车辆去重不表示同乘，资金不配对合并。地点采用带来源的结构化映射，缺失时显示无法核对。独行仅限明确观测片段，不能推导作案。记录范围采用资料实际窗口，不写近30天。

## 验收证据

- Control 针对性测试：45 passed（presentation、facts、evidence、OpenAPI）。运行于 Python 3.12 本地已有镜像，无网络。依赖有弃用提示及测试缓存权限提示，不影响断言。
- 打包器回归：8 passed / 2 subtests passed。
- 插件：13 passed / 82 assertions，覆盖原七工具、场景、事实编译和新增执行轨迹。
- 前端：58 passed / 2175 assertions；包内 typecheck、build 通过。
- 实际服务器页面：1366、1920、390 三宽度通过五步骤、四卡、标题文案、详情 Esc、焦点恢复、会话切换清理、中文草稿、可视元素边界及无页面异常检查。人工截图发现的右栏固定宽度溢出已修正并重新检查。
- 四个实际会话最终只读核验全部 complete / checked，五步均有实际时间，跨账号 evidence 请求均 404；两账号 runtime ready。

### 模型请求记录

本次新增4次用户级请求，之前10次，累计14/40，剩余26。失败/未知也计数；未自动重试。

| 账号与场景 | 首次自动验收 | 后续只读复核 |
|---|---|---|
| A 涉赌 | 失败：临时 Skill 复制导致名称追加后缀，严格名称断言不匹配 | 调用链、事实核对、五步实际时间、四卡及跨账号拒绝均通过；保留原失败记录 |
| A 盗窃 | 通过 | 通过 |
| B 涉赌 | 通过 | 通过 |
| B 盗窃 | 通过 | 通过 |

不将首次失败改写成首次通过。未重发 A 涉赌请求。报告区分自动断言和复核；后台原始验收文件不随源码导出。模型最终固定完成提示由结构化结果替代显示，不通过删词把自由文本变成可信事实。

## 发布与恢复

Control 镜像标签 agent-platform-control:presentation-final-20260918，实际 Docker 镜像 ID：sha256:5c79ed445f9daa8aae5f3891645b909aa4acbf5c239c33b6997225c20d54cbb4。它是本机镜像身份，不是 registry manifest 摘要。

复用本地固定依赖镜像离线构建；部署配置使用精确镜像 ID。Control 与前端匹配发布，Worker 短暂停止后恢复。Agent/Gateway 未重建内核。

修改前已保存 frontend.tar.gz、working.patch、部署配置副本至私密 presentation-backup-20260918。这个备份不是完整数据库/用户卷备份。回退恢复相应 Control 配置镜像，插件回到此前安装版本并经平台配置发布；保留新会话与用户数据。

## 复现入口与限制

- Control：从 services/peixian-control 运行 pytest tests/test_scenario_presentation.py tests/test_scenario_facts.py tests/test_scenario_evidence.py tests/test_openapi.py。
- 前端：从 packages/peixian-console 运行 bun test、bun typecheck、bun run build。
- 插件：从 deploy/peixian/examples/peixian_synthetic_records 运行 bun test。
- 浏览器：tests/presentation-browser.mjs 使用该独立部署已有私密凭据，读取已有会话，不发送模型请求。输出 screenshots/report 至 output/playwright/presentation。
- presentation_acceptance.py 为有费用的现场验收工具，持久文件锁和已尝试记录限制重试；不能在不核对预算的情况下重建报告。

本轮没有执行并发压测、真实业务数据验收、全仓全量回归或新一轮在途停止/网络故障注入。稳定性及实际业务能力不由界面改版证明。既有运行时停止修复、数据适配器和其他交付文件保留在工作区，不混入本次提交。
