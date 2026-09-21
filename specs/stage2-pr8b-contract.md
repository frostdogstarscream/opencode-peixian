# PR-8B 可信结果前端与报告契约

基线 b5910d279d9130ee53cc0d9c8cfb6078607636e8。Schema 保持 v9；只使用合成资料。本阶段不更新运行账号。

## 页面

双 Agent 共用 TrustedResultPanel。新会话从 /agents 选择助手；已有会话使用服务端任务上下文绑定。发送携带 agent_id 与已读取 context_version，不传 target_refs 或 TaskSpec。

可信结果只读取本人会话、指定 Run 的 /result；未知版本或归属不匹配不展示可信区。固定区分已核验事实、确定性计算、资料缺口、待核验来源记录、模型辅助说明、来源与执行过程。Legacy 不转换或补写 Claim。查询状态取 data_usage，不由 query_mode 推断。unknown 显示“请求可能已发出，但结果未确认，不会自动重试”。

## 对象确认

读取 task-context、冻结 task、clarifications。Resolve/Cancel 仅提交选项 ID、context_generation、context_version、client_request_id。确认后显示“对象已确认，尚未查询”；必须再次明确点击继续查询，通过标准 messages 请求执行。409 要刷新，不重发选择；刷新或会话切换不会自动查询。Reset 调用 DELETE task-context，保留历史。

## 报告

GET /api/console/v1/sessions/{sid}/runs/{rid}/report?format=md|html，默认 md；其他格式422，未结束409，跨账号404。HTML Content-Type 为 text/html; charset=utf-8；下载文件 run-ID.html。Result V2 报告读取同一不可变结果，保存全部 missing、Claim、Source、版本、数据性质及 narrative 状态。HTML 转义所有动态文字，CSP 禁止脚本和外部资源。Legacy Markdown 保持历史正文并标识旧结构。

PDF 采用下载 HTML 后在浏览器中“打印→另存为 PDF”；没有服务端 PDF 接口。导出不调用模型或资料接口。中文字体由打印浏览器决定，验收分别检查页面与文字层。

## 兼容与限制

保留同事已有图谱、样式和页面变更，未改写历史消息；新接口与旧 evidence/presentation 并存。浏览器组件夹具仅验证交互，不替代 A/B 真实执行。普通说明仍可出现在对话消息中，不因此成为核心可信 Claim。模型请求0次。无真实数据及并发压测。
