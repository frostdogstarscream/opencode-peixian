# 前后端对齐：独立服务器部署与小规模真实联调

日期：2026-09-17。服务器：36.134.45.38。部署标识：`peixian-alignment-20260917`。

## 已部署版本

产品源码基线为 `630a0929d037812d43e418ae5539471d5e5c755e`，分支 `frontend-alignment`。
Control、Gateway/Relay、Agent 已重新构建；不是把旧 R2 镜像直接换标签。
为避免不确定的依赖下载，使用已保存镜像作为依赖载体，核对 Control/Gateway 的依赖与当前锁文件一致，再替换全部应用代码及前端产物。
Agent 从当前源码重新编译，保留 1.18.30 版本号，启用当前托管及活动观测补丁；不内嵌原生网页，用户界面由独立控制台提供。
完整镜像 ID、编译后二进制摘要及 Worker 文件摘要见 `evidence/ui-alignment-live-20260917.json`。
本轮额外修改宿主 Worker 停止确认逻辑；该文件不在三个应用镜像内，不能仅用镜像标签概括 Worker 版本。

## 部署和入口

- HTTPS：`https://36.134.45.38:19460/`，临时自签名证书；正式使用应换可信证书。
- Control：`127.0.0.1:14099`，不直接对外暴露。
- 配置及私密运行目录：`/srv/peixian-alignment-20260917`；账号密码仅存放其中 `private.json`（0600），不得加入 Git。
- 超管账号 `admin`；管理员 `alignment-manager`；普通账号 `alignment-a`、`alignment-b`。
- 每普通账号真实 Agent/Gateway/Relay 三容器、独立网络和存储；运行名额 2。
- 宿主执行器：`peixian-alignment-worker.service`；合成资料接口：`peixian-alignment-records.service`。
- 合成接口只监听 Docker 宿主桥地址，不监听公网。
- 原 `pengcheng-platform-*` 服务及旧测试数据保留，没有升级或重启。

服务器内 HTTPS 健康、真实浏览器登录和 API 联调通过。服务器不能回环访问自身公网 NAT 地址，服务器 Chromium 使用仅进程内地址映射；页面 Origin 仍为配置公网地址。Python 使用回环 SAN 校验证书和配置的 Origin，未放宽后端 Origin 策略。
**当前 Windows 跨机 HTTPS 握手失败，公网可用性尚未验收通过。** 不将服务器内成功冒充公网成功；云侧安全组、链路和客户端网络仍需核对。没有擅自修改客户端代理或服务器原防火墙规则。

## 实测通过

1. 两个普通账号真实环境开通；管理员无个人运行容器。
2. 各自个人 Skill 实际加载；各自插件通过 Gateway/Relay 连接合成资料服务。
3. TXT 上传、解析、预览；跨账号文件和会话访问被拒绝。
4. 管理员不能访问平台插件、服务连接和模板治理接口。
5. 两次真实 `deepseek-flash` 请求：文件问答核对合成标记和数值；实际插件工具调用核对完成状态和输出版本 1.0.0。没有自动重发未知请求。
6. 插件 1.0.0 → 1.1.0 → 1.0.0，等待实际配置版本生效并执行连接测试；升级版本未另做付费模型调用。
7. 修复后的停止恢复两次通过，会话与文件保留；期间账号 B 持续可查询。
8. Python 令牌请求成功，撤销后 401；已有真实 SSE 在 5 秒内关闭，实测秒数见 JSON。
9. 真实 API 浏览器登录覆盖三角色、四账号，1920/1366/390 宽度；Cookie Secure/HttpOnly/SameSite=Strict；无页面 JS 异常。此项是登录及首页冒烟，不等于所有页面全面人工验收。
10. 部署工具在 Python 3.12、Git、ACL 工具齐备、无网络、无 Docker socket、只读源码的测试容器中：266 passed / 163 subtests passed。

## 首次失败与修复记录

首次停止 A 时，Compose stop 返回后立即查询仍报告运行，Worker 返回 `runtime_stop_unconfirmed`；随后三个容器已退出，但执行记录为未知，恢复未自动完成。
增加最多 5 秒、间隔 200ms 的有界复查；仍须实际查询不到运行容器，超时仍失败关闭。新增“延迟可见”和“始终未停止”正反测试。
无法仅根据事后容器退出证明最初瞬间的 Docker 内部原因，因此将其描述为停止确认窗口问题，而非已完整证明 Docker 根因。
对该合成实例：停止独立 Worker、核对三容器实际退出、备份控制库和宿主执行记录，人工核对遗留执行记录后重排同一恢复任务。容量由原协议完整观察及回执释放，没有直接清除容量标记。备份在部署目录 `recovery-20260917`，含私密数据，不交付 Git。
后续原恢复任务完成，正式用户入口恢复成功，修复后的完整生命周期复测通过。**人工核对恢复不计为全自动故障恢复通过。**

首次全量测试误用宿主 Python 3.11，15 个数据库用例因缺少 Python 3.12 sqlite API 失败；随后测试容器缺少 Git/ACL 工具导致 3 项失败。补齐只读测试工具后完整通过。运行中 Control 始终使用 Python 3.12，未修改其数据库 API 兼容策略。

## 操作与复现

仓库：`/root/PeiXianDB/frontend-alignment`。验收工具：`deploy/peixian/alignment-live-acceptance.py`，阶段 `prepare/basic/model/lifecycle/token`。先阅读脚本部署标识保护。模型阶段记录已尝试标记，防止重复付费请求；不要清除此标记来盲目重试。
浏览器脚本：`packages/peixian-console/tests/alignment-live-browser.mjs`；使用服务器已安装的 Node/Playwright、浏览器及字体环境。它从部署私密目录取登录信息，不模拟 API，也不把凭据写入报告。

```sh
systemctl status peixian-alignment-worker peixian-alignment-records
# 正常查看健康（验证当前自签名证书）
curl --cacert /srv/peixian-alignment-20260917/tls/certificate.pem https://127.0.0.1:19460/health
# 示例：复验 Python 令牌及事件撤销
/root/PeiXianDB/frontend-alignment/services/peixian-control/.venv/bin/python deploy/peixian/alignment-live-acceptance.py --root /srv/peixian-alignment-20260917 --phase token
```

## 未执行与边界

本次是两账号小规模真实部署联调。没有 50 并发、持续负载、真实内网 vLLM、真实业务接口或全量灾难恢复验收；实际系统为 BigCloud Enterprise Linux V25，不冒称 Ubuntu 24.04 验收。没有更新原有业务服务；本轮改动及报告尚未自动推送 GitHub。公网 HTTPS 与可信证书解决前不宣称正式上线完成。
