# 事件脉络图接入与发布说明

## 范围
两个现有场景自动增加事件图。数据来自经过固定事实表精确校验的工具结果，不从模型文字或截图取事实。不改变数据库 schema v6、插件授权或个人 Skill。

## 接口
会话及 Run 的 evidence.presentation.diagram 为可选字段；Run 的服务端 analysis_result 同步携带 diagram。version=1.0，status 为 ready/partial/empty/unavailable。包括 run_id、scenario_id、Asia/Shanghai 时区、观察窗口、两套快照、规则版本、pages、total_nodes、missing、aliases 与图例。每页至多20个原始事件，包含 groups、nodes、edges、mermaid；节点 source_ids 与 message_id 用于现有详情和消息定位。未知版本不渲染，旧结果不自动取数补图。

## 时间和来源
按日期、凌晨/日间/晚间/夜间分组。跨日明确日期，同一时刻不建立顺序边；未明确时间单独分组。虚线只表示时间先后。整数分经 Decimal 格式化为元；不合并流水、不生成资金链。独行只引用显式 observation。地点只使用版本化来源映射，不解析自由文字推测位置。

## 资料兼容
保留原 scenario_data.json 与固定事实表。另增加1.4.0不可变资料登记，场景快照 demo1003 与资料快照 demo1001 必须精确匹配。两个版本均为完全虚构资料；中文显示名不代表真实人员。混合快照和修改后的事实表均拒绝。1.4.0插件由其他部署工作预先发布，本轮只适配它的受信展示，不覆盖插件或个人技能。
scenario_data_v14.json 来源为本轮已部署插件 fixtures.json；重新生成固定表使用 build_facts_projection_v14.mjs，仅写新版本表，不能覆盖旧表。

## 前端
Mermaid 固定11.12.0，随静态资源离线发布；console 独立 package-lock.json 固定依赖。strict、关闭 HTML 标签及图内交互；输出 SVG 经 DOMPurify 白名单清理。安全依据：https://mermaid.js.org/config/schema-docs/config-properties-securitylevel.html
资料列表负责来源交互，图内不接受任意点击代码。缩放、大图、Escape和焦点恢复；切换结果使迟到渲染失效。每页单独PNG/SVG导出，页码写入文件名；Markdown报告包含全部图页。导出保留来源、两套快照与数据性质，页面不增加常驻演示提示。

## 验证命令
在 services/peixian-control 运行 PX_BACKEND_V6=0 python -m pytest tests -q。
在 packages/peixian-console 运行 bun test、bun run typecheck、bun run build。
浏览器运行 node tests/event-diagram-browser.mjs；使用本包 tests/fixtures/event-diagrams.json，无真实账号和模型。合成样例可从后端 tests/export_diagram_fixtures.py 生成。Playwright浏览器与Linux中文字体须预装；浏览器测试阻断外部资源。
本轮已有：后端441项通过；前端68项通过；1366/1920/390两场景6个浏览器用例通过。真实发布和模型结果另见发布回执，不以合成页面测试代替真实调用。

## 发布与回退
沿用现有Control依赖镜像，叠加匹配后端和前端。发布前保存SQLite在线备份、平台配置、运行镜像和代码差异；确认无活动Run，重启Worker完成新Control身份注册。回退恢复上一Control镜像及配置，不覆盖数据库和用户数据；旧版忽略图形新增字段。
仅服务器本地提交，不自动推送GitHub。第三方未提交工作保持原状。
