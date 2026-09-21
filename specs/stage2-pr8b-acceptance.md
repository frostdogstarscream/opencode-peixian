# PR-8B 候选验收记录

状态：实现候选，尚未部署；等待当前实现提交的 GitHub CI。

## 已执行

- 同事前端改动独立检查点：ec7bf7a7450c118f9d9aad07232dc8fdb7dbc6fd。运行树和原有服务未改动。
- 真实 SQLite 支撑的报告、Result V2、Clarification 联合回归：61 passed。
- 本地后端全量首轮：925 passed / 16 failed。16 项均因 PEIXIAN_TEST_JS_COMMAND 经跨 Shell 转义变为无效 JSON 而失败；保留原日志，不改记为全量通过。
- 修正为 Python subprocess 参数列表后，七插件 HTTP、报告和 OpenAPI：30 passed，其中原失败七插件用例全部通过。统一环境全量结果等待 CI。
- 部署与发布检查：宿主 Python 3.11 下56 passed / 10 subtests，1个恢复用例不兼容Python3.12 SQLite API；使用隔离Python3.12复验该用例1 passed。CI统一使用3.12。
- 前端从锁文件独立安装后类型检查、生产构建通过；原74项单测通过，随后新增跨Agent拒绝用例，专项7项通过（完整集合75项待CI再跑）。
- 隔离 Chromium 浏览器15项通过：确认零查询、显式继续、组件刷新、过期确认拒绝、会话切换迟到响应清理、来源详情、焦点恢复、1366/1920/390无横向溢出。
- Windows Edge实际导出PDF两页，中文缺口、unknown、conflicted、Source与合成性质文字层检查通过；两页实际渲染已查看。
- Linux字体样例视觉完整，但个别中文复制为兼容字形；此项文字层不记通过。PDF首版交付方式为客户端HTML打印，不提供服务端PDF接口。

## 保留事项

- 浏览器测试为合成响应的组件验收，不代替真实A/B账号全流程；后者归PR-9C。
- npm audit记录现有依赖告警，PR-8.1联合审查应评估并修复；未执行强制自动升级。
- 现有较大构建分块告警保留，未通过提高阈值隐藏。
- 本轮模型请求0次，未访问真实资料，未开展并发压测。
- PR-8.1、PR-9A/B/C尚未开始，不能用本页结果宣称产品版完成。
