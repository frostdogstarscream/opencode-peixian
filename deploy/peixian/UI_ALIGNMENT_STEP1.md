# 前后端接口与状态对齐：第一步验收记录

日期：2026-09-17。全部源码修改、构建和测试在用户指定服务器执行。

## 版本与范围

- 后端基础：`ea36aa8ec39bc319b66596f7774537891d8f0d97`，里程碑 `pr7c-review-fixes-milestone-20260917`。
- 界面来源：`zblds-a/opencode-peixian` 的 `peixian-ui-final`，固定 `b7cf3e2aaa9a430097a0b4cccac1b5f4d7e2338a`。
- 对接分支：`frontend-alignment`，服务器独立工作树 `/root/PeiXianDB/frontend-alignment`。
- 原服务器工作树 `/root/PeiXianDB/opencode` 保留，未升级既有业务容器、数据库或卷。
- 本步骤仅对齐接口与状态。生产后端逻辑、schema v5、配置 v4、内部协议 v2 均保持里程碑行为。

## 已完成

1. 引入新登录视觉、聊天布局、能力选择弹窗和响应式样式；保留原身份会话、首次改密门禁及三角色权限。登录/改密输入框补充明确可访问名称。
2. 沿用里程碑请求封装：Cookie 同源请求、CSRF、配置/生命周期写入的幂等键、401 退出处理。错误对象保存 Retry-After 和排查编号；响应正文读取中断按结果待确认处理。
3. 沿用 fetch SSE、资源分类刷新、单请求在途、隐藏页降频、重连补齐和退出清理，未恢复旧 EventSource/全量刷新实现。
4. 使用 can_observe / can_continue / can_submit_new，保留启动、取消启动、容量等待、排空、维护、安全阻断和恢复提示。排空期间允许停止、权限确认及问题回复。
5. 删除正式界面的 Mock 会话/模型/能力回退。不发起不存在的 /capabilities、Run、证据链、Skill 草稿 API 请求。当前能力弹窗只列真实已启用个人 Skill；后续统一插件目录另行接入。
6. 消息只提交 text、model_id、skill_ids、file_ids；点击时冻结选项。受理后只刷新真实会话历史，不将返回的 run_id 当成持久 Run。断网/5xx 等结果未知时保留草稿并阻止直接再次提交，用户核对后才能主动解除保护；429 不自动重试。
7. 管理导航按服务端权限显示，复用已验收管理表单和按页资源加载。没有使用依赖新部门/业务审计接口的 FinalAdmin，也未改变管理员插件授权边界。

## 验收证据分层

| 层级 | 结果 | 证据边界 |
|---|---|---|
| Control 回归 | 462 passed / 4 skipped / 2 warnings | Python 3.12.14 一次性容器，源码只读，network none，临时数据；跳过项不记通过 |
| 前端单元 | 55 passed / 0 failed | 保留事件、调度、权限和 Runtime 回归 |
| 类型与构建 | 通过 | 包目录 bun typecheck、bun test、bun run build |
| 新界面合同浏览器 | 8 组场景通过 | 真实构建 Solid 页面，HTTP 为明确合成接口；不证明真实模型生成 |
| 里程碑 UI 回归 | 10 个场景标记通过 | 排空确认/回复/停止、新提交拒绝、维护、迟到读取、草稿及三种宽度 |
| 真实 Control 浏览器 | 三角色认证及启停契约通过 | 无 HTTP 拦截，真实 SQLite、Cookie、CSRF、Origin、改密与退出撤销；无 Worker，不创建真实 Agent |
| 页面尺寸 | 1366 / 1920 / 390 通过 | 无横向溢出；中文截图保存在包内 output/playwright，1366 与 390 截图另经人工视觉核对 |

本人改密的现有正式契约是“保留本次登录、撤销其他会话与令牌”，测试分别验证其他会话撤销、当前会话可用，以及退出后当前 Cookie 失效。没有以复制同一 Cookie 模拟另一独立会话。

服务器系统 Python 3.11 的首次尝试因缺少 SQLite autocommit API 失败，随后使用受支持的 Python 3.12 容器通过，未修改生产代码迁就旧解释器。服务器缺少浏览器音频库和中文字体，依赖仅解包到项目 .tooling 目录，未替换系统库。

## 复现

前端在 `packages/peixian-console` 目录运行：

```sh
bun typecheck
bun test
bun run build
# 启动只监听回环的静态测试服务后，运行合成合同与旧回归。
python3 -m http.server 15178 --bind 127.0.0.1 --directory dist
node tests/alignment-browser.mjs
node tests/review-browser.mjs
```

真实认证测试使用 `services/peixian-control/tests/alignment_server.py`，必须在独立一次性容器启动，发布到 `127.0.0.1:15179`，挂载本分支源码和构建产物：

- Python >=3.12，加载项目 Control 依赖，PYTHONPATH 指向 services/peixian-control。
- CONSOLE_STATIC 指向本分支 packages/peixian-console/dist。
- CONSOLE_ORIGINS=`http://127.0.0.1:15179`。
- 每次完整运行 `node tests/alignment-auth-browser.mjs` 前，重新创建该临时容器；脚本会修改合成账号密码。
- 合成账号与密钥只保存在容器临时目录；不挂载生产数据、不启动 Worker、不公开测试入口。

本服务器测试工具：Bun 1.3.14、Node 22.14.0、Playwright 1.58.2，位于 `/root/PeiXianDB/.tooling`。Bun 注册表下载停滞后改用独立 npm 工具目录安装同版本直接依赖；完整工具依赖锁保存在该目录，不据此宣称本轮生成了正式离线包。Browser 需要以下测试环境变量：

```sh
export PLAYWRIGHT_BROWSERS_PATH=/root/PeiXianDB/.tooling/browsers
export LD_LIBRARY_PATH=/root/PeiXianDB/.tooling/browser-libs/usr/lib64
export FONTCONFIG_FILE=/root/PeiXianDB/.tooling/fonts.conf
```

后端回归从 `services/peixian-control` 运行 `python -m pytest -q -p no:cacheprovider`；本次使用已有镜像作为 Python/依赖载体，并只读挂载本分支全部源码，**不是使用旧镜像内的旧 Control 源码进行验收**。镜像身份和源码/构建摘要见 `evidence/ui-alignment-step1-20260917.json`。

## 尚未完成的下一阶段

- 未构建/切换新的完整 Agent/Gateway/Relay/Control/Worker 镜像集合。
- 未执行真实模型回答、工具调用、完整 Worker 开通及文件解析端到端验收。
- 未建设统一插件能力目录、部门、持久 Run、结构化业务结果、证据链和 AI Skill 草稿。
- 管理端暂用已验收的原管理表单；新的部门和调用审计页面不以 Mock 替代。
- 未开放公网入口、部署 HTTPS 或进行并发压测。
- 本次仅服务器 Git 检查点，不自动推送远端。

首次服务器正式安装仍需使用匹配的全套镜像和独立部署配置；不得将本次临时认证服务当成可供业务使用的正式部署。
