# 七插件拆分：基础实现检查点

日期：2026-09-20。分支：codex/seven-data-plugins。基线：421f14b937c19e40eca1717e6ec566e955d86665。

## 已完成

七个独立查询插件源码与1.0.0可复现ZIP；每包一个工具。提供各模块固定连接规则样例，不包含服务地址或密钥。

服务连接新增可选request_rules：精确匹配method/path及完整JSON正文，拒绝额外查询参数。字段省略兼容原有连接；字段出现时必须为1至20个规则。规则变更触发受影响账号安全阻断和配置更新。执行器下发规则至Relay，复用共享校验代码；线上组件尚未升级。

平台事实处理协调模块候选实现：需要宿主注入Run级持久存储、真实插件调用、授权及审计适配器。独立测试确认同Run成功响应复用、未知结果不重发、check不取数、撤权检查及并发拒绝。未接入生产Agent，不应将模块独立测试当作持久执行链路验收。

四个专项Skill候选：night、companions、funds、relations，版本3.0.0。未发布或覆盖用户Skill。

## 测试

Control全量464 passed，2项既有依赖弃用警告；七插件入口14 passed；协调模块4 passed。七个ZIP检查通过，包内仅manifest.json与entry.mjs，工具名唯一。

模型请求0次。没有执行A/B迁移或线上新插件工具调用。没有发布本轮Control、Relay、Agent或Worker修改。

## 必须完成的后续集成

1. Agent可信执行身份与Run绑定，真实持久缓存/审计/取消适配；不能使用临时内存Map作为最终恢复保证。
2. 明确关系方法需增加场景允许模块映射。目前历史场景required_modules未包含composite，不能简单调用候选relations后声称可用。
3. 替换旧插件ID授权检查、固定完整表校验，使分模块事实与来源、冻结插件版本、平台处理版本共同验证；不能仅放宽为接受任意工具JSON。
4. 历史Run/非Run会话证据兼容与原结果保留；账号原子迁移及回退工具。
5. 更新Agent与官方场景Skill，接入专项方法；候选包发布、A后B切换、旧插件目录归档和实际模型验收。
6. 更新离线打包白名单，形成匹配镜像集合和正式接口文档。

## 现场保护

工作区备份：/root/peixian-code-backups/seven-plugins-20260920T123314Z。包含排除Git元数据、node_modules和.venv后的工作区归档，以及原始差异与未跟踪清单；不是完整运行数据备份。此前完整源码备份继续保留。

本轮没有退出用户登录、没有更改账号安装或运行配置、没有停用旧七合一插件。旧插件依赖尚未迁移完成，提前移除会中断事实核对。前端同事修改保留未提交。本检查点不表示计划完成，不是可发布版本。

## 文件位置

- deploy/peixian/examples/seven_data_plugins：七包源码、规则、打包器和四项Skill。
- deploy/peixian/platform-facts：待接入的受控处理模块及测试。
- services/peixian-control：固定请求策略、连接/API/执行器下发及回归。

候选ZIP和测试日志位于服务器私有目录/srv/peixian-alignment-20260917/seven-data-plugins-candidate。未推送GitHub。
