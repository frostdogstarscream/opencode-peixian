# PR7C-CR-FIX-01 本机源码与组件修复记录

日期：2026-09-17。分支：`codex/pr7c-review-fixes`。

基线：`5875a6eab0f1d9e16d71bd22c0b44b52b725d89a`。

修复源码／宿主 Worker 候选：`e87b8d1c9ca6008deabfd10f265f596ef6bfb2f6`。

依据：用户提供的《沛县公安智能体_PR7C_CodeReview专项修复实施方案_V1.0_5875a6e.md》。本记录不替换旧 PR7C_REPORT，也不覆盖原审阅证据。

## 结论及边界

CR-01、CR-02、CR-03 已落实源码修改，本机状态机、HTTP、前端组件流程及受影响回归通过。**真实容器专项验收尚未执行，因此不声明完整关闭或生产通过。**

本轮没有操作原 14090/A/B、真实数据库、账号授权、原用户自动休眠开关，也没有进行 Linux、大规模并发、付费模型测试或远端推送。浏览器测试使用独立的 `127.0.0.1:15178` 静态预览与合成 HTTP，不是实际 Agent/Gateway/Relay 端到端验证。

未构建或部署本候选 Docker 镜像。上一轮镜像不能作为本候选运行证据。正式复验时需构建包含本候选后端与前端的 Control，并使用同一候选 Worker；未变更的 Agent、Gateway/Relay、Proxy 需核验兼容身份。

## 修复对应

| 编号 | 修改 | 本轮证据 |
|---|---|---|
| CR-01 | 恢复判断按动作区分。pause 全停才可直接完成；仍运行时须确认阶段后停止；mixed/unknown 保留责任。apply/provision/resume 仅运行且冻结版本、摘要匹配才跳过宿主变更 | 真正 Store/SQLite/Orchestration/Worker，宿主与传输替身；通过状态机推进 closing 后让租约过期，再实际 claim 接管 |
| CR-01 联动 | 保存恢复来源，进入 closing 后不获得 cancel-idle 资格；已停空闲暂停不要求不存在的 Gateway 出具 idle proof；变化或未知时保留责任 | 普通暂停、已停、mixed、unknown、apply 运行匹配、idle 已停／运行／活动变化／closing 后变化，共 9 个接管场景 |
| CR-01 回执 | 保留同 operation 的查询与重试；未知控制结果不另发失败结果。心跳收尾覆盖最终观测与 complete | 既有丢响应、冲突、拒绝与未知回执回归；新增 unknown defer 不提交第二份 outcome |
| CR-01 Control 联动 | 恢复任务从 reconciling 进入 closing 后失败，也按恢复来源保留待人工处理，不按普通失败盲目补排 | `idle_closing_changed` 组合测试实际暴露并验证此分支；全停、租约及观测 TTL 限制未放宽 |
| CR-02 | 增加非持久 interaction 视图，统一 /me 与 /me/runtime；发送、观察、继续操作分开 | 后端状态矩阵和完整认证 HTTP；OpenAPI 增量字段由现有 exporter 生成 |
| CR-02 页面 | 普通 draining 保留 question、permission 和 abort；新消息／上传／插件测试仍禁用；暂不可读不清成 idle；晚到读取校验代次与身份 | Edge 中运行真实生产构建，合成请求验证提交答案、once、abort、新发送禁止、草稿及晚到响应 |
| CR-03 | frozen/repair_only 不声明本人 start/stop；维护提示不再承诺能取消等待 | 已预留与 waiting_capacity 两类状态，normal/frozen/repair_only 完整 Token HTTP 路径；拒绝后 jobs 未改变 |

安全权限仍由 Control/Gateway 最终判定。`can_observe` 不代表任意 GET、新下载或任意文件访问获准。维护期不扩展原认证、幂等或 continuation 白名单。当前 EventHub 仅接受 normal 维护模式，所以 frozen 中前端不建立 SSE，使用既有有界 GET 校准；普通 normal/draining 仍可观察。

## 旧源码对照

将 Git 固定基线的 Worker 源码加载到隔离 Python 测试进程，复用当前真实状态机测试夹具，未替换工作树或部署脚本。8 个接管场景在旧 Worker 上 **5 failed / 3 passed**：running、stopped、mixed、idle_stopped、idle_running 失败。失败分别涉及虚假成功被 Control 拒绝、重复宿主操作或不合法的 idle 取消。

随后增加的 `idle_closing_changed` 是本轮联动测试，不把它计入上述旧源码对照的 8 项。纯 helper 在新增前因函数不存在而失败的结果，也不算缺陷复现证据。

## 最终本机检查

| 检查 | 结果 |
|---|---|
| Control tests | 373 passed；2 条依赖弃用警告 |
| Windows deploy tests | 262 passed，2 skipped，163 subtests passed |
| Gateway/Relay tests | 85 passed，8 skipped；2 条依赖弃用警告 |
| 前端 Bun tests | 55 passed，0 fail |
| 前端 typecheck / production build | 通过 |
| Edge 真实组件、合成 HTTP | 通过：question、permission once、abort、禁新消息、维护动作、晚到读取、草稿保留 |
| 1366 / 1920 / 390 宽度 | 页面与输入框可用、草稿保留；不是完整视觉／无障碍审计 |
| OpenAPI | 实际 exporter 已更新 Runtime/SelfRuntime 三个能力字段及 maintenance_mode |
| 历史迁移／配置／协议 | 迁移文件无改动；Schema 5／配置 4／协议 2／已有 policy 3 保持原约束 |
| Git diff whitespace 检查 | 通过 |

上述计数为分别执行的测试套件，不相加为端到端场景数。Windows 跳过项不计为通过。Python 3.12.14、Bun 1.3.14；浏览器使用本机 Edge，经本机 Playwright 驱动。未更改生产依赖。

测试可复现入口（在各包目录执行，选择唯一的新 basetemp，避免覆盖历史结果）：

```powershell
# services/peixian-control
.venv/Scripts/python.exe -X utf8 -m pytest tests -q --basetemp=.pytest-review-rerun
.venv/Scripts/python.exe -X utf8 export_openapi.py

# deploy/peixian
../../services/peixian-control/.venv/Scripts/python.exe -X utf8 -m pytest tests -q --basetemp=.pytest-review-rerun

# services/peixian-control/gateway
../.venv/Scripts/python.exe -X utf8 -m pytest tests -q --basetemp=.pytest-review-rerun

# packages/peixian-console，Bun 使用已安装的 1.3.14
bun test
bun run typecheck
bun run build
bun run preview --port 15178
# 另一终端：NODE_PATH 指向本机已安装 playwright 的 node_modules
node tests/review-browser.mjs
```

浏览器脚本默认使用已安装的 Edge，可通过 `PLAYWRIGHT_CHANNEL` 指定兼容浏览器。脚本覆盖所有 `/api/console/v1/**` 请求，不连接原运行实例。不要将此替身测试标为完整认证或真实模型验收；完整认证在独立 Python HTTP 测试层执行。

## 未执行及下一道验收

- 本候选匹配镜像构建与隔离真实容器部署：not_run。
- 真实容器普通 pause 接管、待确认→draining→确认／中止→配置实际应用：not_run。
- 本候选 A 空闲停→B 晋升→A 重启且文件／会话保留的实机复验：not_run。源码级原容量、数据保留回归已执行，但不能代替这个场景。
- 本轮新增的浏览器多宽度检查没有覆盖完整键盘、无障碍和长文本视觉矩阵。
- 实际物理备份恢复、Linux、目标容量／持续负载、真实模型及内网业务接口：not_run。
- PR-6/PR-7 其余发布门槛继续保留；本报告不签发生产批准。

因此，本次交付状态为 **源码／HTTP／组件修复通过，实机专项验收未完成**。部署时必须配套 Worker、Control 与前端，不能只更新页面或只替换宿主脚本。
