# N3：Worker 操作回执诊断与本机回归

日期：2026-09-17。分支：`codex/stability-followup-r4`。
开发基线：`db55ee9569c5bcc578c352e7ce8c8a254ab2c54e`。

## 结论与边界

本轮实现受保护 Worker 接口的固定诊断码、关联日志及明确拒绝与结果未知的区分，并修复回执校验前就写入 recorded 的问题。没有改变 schema v4、内部协议 2、租约或观测有效期，没有增加宿主变更重试。

R3 曾记录的两次完成回报 unknown 缺少对应请求、回执与版本证据，**历史根因仍未定位**。本轮确定性复现证明旧代码存在错误归类及无效回执错误落盘，不能据此断言两次历史事件由这两个问题导致。

本机测试使用真实 SQLite、FastAPI 及合成 HTTP/宿主操作。阶段退出使用租约时间推进模拟，不是实际杀死 Worker/Docker 进程。本轮不升级原 14090 或独立 19444 运行环境，不调用付费模型，不运行 Linux、远程主机及大规模压力测试。前端未变更。

## 实现

- `X-Peixian-Worker-Code` 仅用于 `/internal/worker/` 的受保护错误响应。固定白名单区分 lease/attempt、phase、state/gate、观测过期/替代/不完整、回执冲突及维护/安全阻断；旧接口没有此头时使用保守的通用拒绝分类，不再把全部 409 归为租约丢失。
- 每次操作关联 job、attempt、operation、阶段、版本、观测年龄、HTTP 状态和回执是否命中；日志不记录租约、密钥、配置快照、原始响应和业务正文。
- 明确拒绝且查询无回执时记录 rejected，不盲目重发过期内容。传输失败仍先查询同一操作，最多原有两次同内容提交。查询失败保留最初错误和查询错误，记为 unknown。
- 首次提交结果未知、随后提交明确拒绝时仍保持 unknown；后一个拒绝不能证明前一个请求未提交。查无回执不能证明宿主操作未执行。
- 回执身份、可选 request_hash、版本类型和阶段全部验证后才写 recorded、更新本地状态。回执冲突即使查询命中，也不能当成本次成功。
- 新增共享诊断模块进入离线打包白名单；OpenAPI 已重新导出。旧候选镜像和交付包不包含本轮修改，不能用旧 N2 结果代替新候选验收。

## 确定性证据

| 场景 | 证据及预期 |
|---|---|
| 明确拒绝 | 六类 409 保留真实类别，只提交一次，再查询原回执；不错误标记为租约失效 |
| 提交后丢响应 | draining、closing、applying、boot、complete 五处在真实数据库提交后注入 ReadError；查询命中原回执，模拟 mutation 总计一次 |
| 回执查询不可用 | 原传输错误与查询过载同时留存，不被第二个异常覆盖 |
| 先未知后拒绝/过载 | 两次 POST 的 operation_id 和完整内容一致，最终 unknown，不增加宿主操作 |
| 无效/冲突回执 | 错误版本类型、错误摘要及冲突查询命中均不更新本地版本、不落 recorded |
| 完成证据失效 | 观测过期、被替代、state/gate 改变均拒绝完成；容量保留、入口关闭、applied 不提前更新 |
| 各阶段失联 | claimed、draining、closing、applying 租约过期；新 attempt 接管，后两者先 reconciling，不释放名额或开放入口 |
| 接口保护与脱敏 | 未认证无诊断头，协议不匹配有固定码；任意错误字符串及合成租约不进入日志 |

新增最初八个反例在旧实现上失败，修改后通过。Control 完整回归为 **310 passed**（98.19 秒，两个依赖弃用警告）；Windows 部署套件为 **195 passed / 2 skipped**（10.43 秒），另有 **163 subtests passed**。两个跳过不是通过项。OpenAPI 离线导出及 Git 差异空白检查通过。

## 复现命令

在 `services/peixian-control` 目录：

```powershell
.venv/Scripts/python.exe -m pytest tests -q --tb=short --basetemp=.pytest-n3-full
.venv/Scripts/python.exe export_openapi.py
```

在 `deploy/peixian` 目录：

```powershell
../../services/peixian-control/.venv/Scripts/python.exe -m pytest tests -q --tb=short --basetemp=.pytest-r4-n3-full
```

## 现场排查与下一步

1. 以相同 job_id / attempt / operation_id 关联 worker_operation 记录及受保护回执查询，不根据单个 unknown 推断根因。
2. recorded 仅证明当时提交结果，不能作为当前开放入口的许可。rejected 也只针对控制操作，不证明宿主动作未发生。
3. unknown 保留现场与恢复责任，等待真实状态核对；不更换操作标识重做原宿主动作、不手工释放容量、不跳过门控。
4. 后续冻结包含 N3 的源码候选，重建匹配 Control 与宿主 Worker，补做本机真实容器集成；再生成匹配交付包。此次源码回归不替代这一步。
5. N4 空目标完整恢复、N5 目标环境负载、真实进程崩溃及历史 unknown 根因定位仍未执行/未完成，不据此宣称 PR-6 整体退出。
