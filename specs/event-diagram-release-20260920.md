# 事件脉络图发布回执与验收缺口

日期：2026-09-20。用户最终选择：保留当前发布，交付验收缺口。停止继续改插件、配置或进行模型请求。

## 已发布
入口：https://36.134.45.38:19460/
Control镜像：agent-platform-control:event-diagram-20260920
镜像身份：sha256:51fe4c81f5ab3b3b64b319aba985ef37fba700456084d3fb21e3ec7a47f11ab3
源码：d639950f8（功能提交928afac87；同事前端检查点abe2ca8ed）。
上一镜像：sha256:84b4453148e769c8f5b8d803dbc421a658ced467e25e3d1408dece6e839c8519，frontend-turn-trace-20260920。
schema仍为6，无数据库迁移。未修改个人Skill、未推送GitHub。第三方插件和执行器未提交修改保留。

## 本轮已验证
- 后端全套441 passed；两条既有依赖弃用警告。
- 前端68 passed；typecheck、生产构建通过。
- 两场景×1366/1920/390六组隔离浏览器测试通过：实际构建资源、中文SVG、浅深色、放大、Escape、来源抽屉、PNG/SVG导出；外部资源阻断。
- 数据回归包括旧/1.4.0精确事实表、快照混用拒绝、部分资料、同刻不连顺序边、未知时间、41节点分页、原始流水金额和明确观测。
- 使用测试夹具的页面验证不是现场模型行为验收。
- 发布后Control健康，管理网络2/2重新连接，Worker运行。

## 未通过的真实验收
本轮新增模型请求1次，账号A涉赌场景，Run完成但证据为unavailable，无图形，Markdown不含Mermaid。不自动重试；B未发起模型请求。
累计账本由18增加到19/40，本轮最多4次的额度使用1次。生成图形本身不调用模型。

原因：发布检查时A/B已生效插件均为1.4.0；随后外部配置继续变动，A实际升级到1.5.0。本轮受信投影仅兼容1.1.0–1.4.0，所以拒绝1.5.0，不把未经适配结果包装成可信图。
B配置更新失败并进入recovery_required；未擅自清除恢复标记、强制改库或再次更新。最终状态见文末。
目前不能宣称两个普通账号的真实场景图、真实报告与页面整体联调已通过。

## 新发现：快照标识复用
1.5.0相对1.4.0修改了观察窗口及各模块记录内容，场景规则由demo-scenarios-v2变为demo-scenarios-v3，但仍使用scenario_snapshot_id=demo1003、records_snapshot_id=demo1001。
本轮没有将1.5.0加入白名单，也没有替换已经冻结的1.4.0资料。
下一轮必须先分配新的不可变快照，明确部署清单，再建立新版本固定事实表与图投影；不能仅增加版本白名单，也不能让旧Run从最新资料补值。

## 下一轮最小工作
1. 固定插件、资料服务、窗口与新快照；保留旧快照不可变。
2. 适配新的精确事实表、来源映射与展示；回归旧/新/mixed版本。
3. 核对B失败任务与真实组件状态，经正常恢复流程恢复，不能清标志绕过。
4. 环境就绪后执行独立的新验收请求（失败不自动重发）：A涉赌、B盗窃；核对真实工具结果、Run持久投影、页面和报告。
5. 完成跨账号真实图/报告访问、会话切换和重连检查。现有通用鉴权回归不替代此部署验证。

## 回退与证据
备份目录：/srv/peixian-alignment-20260917/diagram-release-20260920。
包括control.before.sqlite3、platform.before.json、release-identity.json、测试记录、模型账本和脱敏结果。私密证据不提交Git、不复制凭据。
按用户要求目前不回退。需要回退时使用上一镜像并保留当前数据库和新增会话；不覆盖恢复数据库。插件1.5.0不受上一版本可信白名单支持，单独回退页面不能解决此适配缺口。

## 最终只读状态
- alignment-a：{"status": "ready", "revision": 43, "desired": 43, "error": null, "recovery_required": false, "gate_policy": "open"}
- alignment-b：{"status": "failed", "revision": 21, "desired": 22, "error": "runtime_operation_failed", "recovery_required": true, "gate_policy": "closed"}
- image："sha256:51fe4c81f5ab3b3b64b319aba985ef37fba700456084d3fb21e3ec7a47f11ab3"
- worker："active"
