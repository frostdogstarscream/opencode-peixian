# 前端 v6 契约专项修复回执

## 范围
保留 frontend-alignment 工作区既有未提交改动；仅修复重跑受理响应、历史证据展示兼容与资料缺口显示。未修改后端契约、数据库或 Agent/Gateway 源码。

## 修改
- 重跑按 accepted/run_id/message_id 接收，建立待查询状态，GET 补齐真实 Run；不从响应读取不存在的 id/status，不伪造受理时间。
- 重跑提交锁防止重复点击；会话/账号/选择代次检查阻止迟到响应覆盖当前会话；未知结果不自动重发。
- 旧 presentation 仅从本人会话证据接口适配；模型消息仍要求新版 schema/version。保留结论来源、条目、时间、缺口；不增加画像或事实。
- 恢复资料缺口与局限展示；新版结果只补入相同 Run 的缺口，避免不同执行串用。

## 验证
- Bun：63 passed，0 failed，含 5 项新增契约回归。
- bun run typecheck：通过。
- bun run build：通过。
- 未执行真实模型重跑，模型请求新增 0；未执行完整浏览器交互/多宽度视觉回归，不将单测记为页面端到端通过。

## 发布
候选镜像基于此前正在运行的 Control，仅 COPY 前端静态资源。
新镜像：sha256:7f9399e62dce02bca061e57ce9137e73f84afaa929c64e81fb8b11828b216614。
原镜像：sha256:557c567ed79a228a2f5e959cdd68fa4f02773b6acad21e3972561cbbf443e9f4。
使用 platform-manage.py up 完成兼容检查与管理网络恢复。Control 重建后 Worker 出现 worker_boot_unregistered，重新启动专属 Worker，并通过超管 pause/resume 恢复测试环境，未修改数据卷。

## 证据与回退
服务器备份及日志：/srv/peixian-alignment-20260917/frontend-contract-fix-20260920-084855。
包含原始前端文件、preexisting.diff、platform.before.json、测试/构建/发布日志和脱敏发布后检查。
回退可将 platform.json 的 control 镜像恢复为原镜像，再使用现有发布脚本检查并更新；重新核对 Worker 注册与账号环境。无需数据库回滚，不覆盖用户数据。
本轮未提交或推送 Git，原有前端工作区修改保持原状。
