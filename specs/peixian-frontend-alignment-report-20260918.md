# 沛警智枢前端迁移与接口接入清单（2026-09-18）

## 1. 基线与结论

- 目标源码：`/root/PeiXianDB/frontend-alignment`，分支 `frontend-alignment`。
- UI 基线：`ui/peixian-ui-final` / GitHub `peixian-ui-final`，前端目录 `packages/peixian-console/src`。
- 后端契约基线：PR7C 文档包 `ea36aa8ec39bc319b66596f7774537891d8f0d97`，统一前缀 `/api/console/v1`。
- 部署方式：前后端代码分离、同源交付。SolidJS/Vite 静态资源由 Control 服务/反向代理同源提供，浏览器不直连账号 Runtime。
- 结论：保持当前同源分离方式。改成跨域独立站点会扩大 Cookie、CSRF、CORS、SSE 与 Secure 配置改动，没有必要。

## 2. 页面迁移结果

| 界面 | 处理 | 结果 |
| --- | --- | --- |
| 登录/首次改密 | 保留服务器鉴权、首次改密、会话失效处理；恢复 GitHub 品牌与界面 | 已接入，成功 |
| 智能研判 | 以 GitHub Chat、结构化研判、线索抽屉和能力选择为主；保留服务器 Runtime、SSE、幂等保护与证据接口 | 已接入，成功 |
| 我的文件 | 服务器新增页面原样保留 | 已接入，成功 |
| 个人设置 | 服务器新增页面原样保留 | 已接入，成功 |
| 模型管理 | 使用 GitHub `FinalAdmin` 页面；请求体裁剪为服务器 Schema | 已接入，成功 |
| 用户与部门 | 使用 GitHub 页面；账号、授权、启停、重置密码接真实接口 | 部分接入 |
| 调用审计 | 使用 GitHub 页面；列表适配服务器 `/admin/audit` | 部分接入 |
| 服务连接、插件发布、技能模板、环境任务、维护诊断 | 保留服务器新增管理页面及权限导航 | 已接入，成功 |
| 隐藏能力配置 | 恢复 `CapabilityAdmin.tsx` 源码，但按产品约定不加入导航 | 未启用（预期） |

## 3. 接口接入清单

| 所属界面 | 功能/接口 | 状态 | 验证/说明 |
| --- | --- | --- | --- |
| 全局 | `GET /platform` | 已接入 | 正式品牌优先；泛化默认值不会覆盖“沛警智枢” |
| 登录 | `POST /auth/login`、`GET /me`、`POST /auth/logout` | 已接入 | Cookie、CSRF、401 清理、账号代际保护 |
| 首次改密/设置 | `POST /me/password` | 已接入 | 首次改密阻断业务读取 |
| 全局事件 | `GET /events` | 已接入 | fetch SSE、401 终止、429/503 退避、资源失效合并；不重放写请求 |
| Runtime | `GET /me/runtime`、`POST /me/runtime/start|stop` | 已接入 | 保留服务器门禁、维护态和 allowed_actions |
| 智能研判 | `GET /models` | 已接入 | 仅展示真实数据，无 Mock 回退 |
| 智能研判 | 会话列表、新建、重命名、删除 | 已接入 | `/sessions`、`/sessions/{sid}` |
| 智能研判 | 消息读取、提交、中止 | 已接入 | `/messages`、`/abort`；消息体严格为 `text/model_id/skill_ids/file_ids` |
| 智能研判 | 消息提交幂等 | 已接入 | 使用服务器现有 `Idempotency-Key`；网络/5xx 后锁定重发，保留草稿 |
| 能力选择 | `/capabilities` | 已适配 | 后端无此路由；前端由 `/skills` + `/plugins` 合成统一目录 |
| 能力选择 | 随消息提交 `plugin_ids` | 未接入 | 当前 MessageBody 禁止该字段；插件配置后由助手按需调用，前端不伪造提交 |
| 结构化研判 | `analysis_result` 渲染 | 前端已接入 | 已恢复正式组件；是否出现取决于后端消息 Part 实际产出 |
| 证据依据 | `GET /sessions/{sid}/evidence` | 已接入 | 服务器源码已实现的扩展接口；保留“已核对摘要”与来源验证 |
| Run 恢复/步骤/证据/重跑/报告 | `/sessions/{sid}/runs/{run_id}/*` | 未接入 | PR7C 当前无这些路由；前端不会查询不存在的 Run API，不会伪造导出 |
| 文件 | 列表、上传、预览、下载、删除 | 已接入 | `/files` 全链路；保留解析状态与 Runtime 门禁 |
| 结果文件 | 列表、下载 | 已接入 | `/results`、`/results/{fid}/download` |
| Skill | 列表、新建、编辑、启停、测试、回滚、删除 | 已接入 | `/skills` 系列；请求体裁剪为当前 Schema |
| Skill 模板 | 列表、复制 | 已接入 | `/templates`、`/templates/{tid}/copy` |
| Skill 草稿 | `/skill-drafts/*` | 未接入 | 后端无路由；界面明确提示待提供，不发送 404 请求 |
| 插件 | 列表、配置、测试、回滚 | 已接入 | `/plugins` 系列；直接随消息选择暂不可用 |
| 确认闭环 | questions/permissions 列表与回复/拒绝 | 已接入 | 保留服务器实际确认流程 |
| 模型管理 | 列表、新增、编辑、启停、已保存模型测试 | 已接入 | `/admin/models`、`/{mid}/test` |
| 模型管理 | 保存前测试 `/admin/models/test` | 未接入 | 后端无路由；按钮明确提示，不再假成功 |
| 模型管理 | provider/context/access_mode/supports_tools | 未接入 | 当前 Model Schema 不接受；保留 UI 展示但不提交额外字段 |
| 用户管理 | 列表、新增、授权、启停、重置密码 | 已接入 | `/admin/users` 系列；重置后的初始密码仅在一次性弹窗显示 |
| 用户管理 | 姓名、警号、部门、警务职务 | 未接入 | 当前 UserCreate/UserUpdate Schema 不接受；保存时明确提示部分未落库 |
| 部门管理 | tree/summary/CRUD | 未接入 | PR7C 当前无接口；保留页面并显示待接入，不展示演示部门 |
| 调用审计 | `/admin/audit` 列表 | 已接入 | 适配到 GitHub 调用审计表格，无 Mock 回退 |
| 调用审计 | `/admin/invocations/{id}`、export | 未接入 | 当前后端无路由；详情/导出明确显示待接入 |
| 超级管理 | connections/plugins/templates/jobs/recovery/maintenance/diagnostics | 已接入 | 服务器新增页面与接口保持不变 |

## 4. 验证结果

- `git diff --check -- packages/peixian-console`：通过。
- `bun typecheck`（包目录）：通过。
- 前端单元测试：57 通过，0 失败。
- 生产构建：通过；输出到 `/tmp/peixian-console-ui-final-dist-20260918`，未修改实际 `dist`。
- 合成浏览器验收：8 个场景通过，包括无 Mock 回退、消息成功/网络/5xx/429、不自动重放、不访问 Run API、管理员权限菜单、首次改密阻断。
- 响应式截图：1366、1920、390 像素均生成，无页面级横向溢出。

## 5. 未执行事项

- 未重启或重建 Docker 容器。
- 未替换实际部署 `dist`，当前线上页面不会因本次源码修改自动变化。
- 未使用真实账号、真实模型或真实公安数据做端到端调用。
