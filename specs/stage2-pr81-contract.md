# PR-8.1 结果层与前端联合审查

基线：`f0e8009b9f909a3798b7c1fb83ee9282402f714f`，分支 `codex/stage2-result-integration-review-v1`。schema 保持 v9；Result V2 与现有接口路径兼容；不修改历史已保存结果，不迁移用户数据。

## 修复与信任边界

1. 新结果构建再次校验冻结 Agent、TaskSpec、目标与方法链。对象不一致拒绝生成事实和计算，只保留缺口；不能把页面任务对象与事实对象分开使用。
2. 已保存结果读取除摘要外检查固定合成环境。错误环境即使摘要正确仍拒绝读取。未来真实环境必须另建来源契约，本轮不兼容为真实资料。
3. 历史复用说明不再无条件属于白名单，必须与 Data Usage 历史执行记录匹配。其余自由文字继续保持保守冲突检查，不声称完整语义验证。
4. 前端 Result V2 与当前 Run 的冻结 Agent 匹配；unknown/not_started/in_flight 不接受已核验事实卡。partial 保留实际已取得模块，并显示分项状态。
5. 旧侧栏只能在当前 Run 明确为 Legacy 且原结果 Run 一致时展示；V2、待确认和读取失败不以其他旧 Run 的侧栏替代。未绑定持久 Run 的旧会话继续历史阅读。
6. HTML/Markdown 报告保留 Missing、unknown、模型冲突与版本。来源按文字渲染；澄清确认零查询、显式继续与 CAS 行为保持。

## 依赖修复

锁定 Solid 1.9.15、DOMPurify 3.4.15、Mermaid 11.17.2、Vite 7.3.6，保留其余直接依赖。独立安装，未执行强制升级；npm audit 从 11 项变为 0 项。此为本次依赖库扫描结果，不等同于系统绝无漏洞。

DOMPurify/Mermaid 在浏览器 Markdown/SVG 路径实际使用，完成渲染和导出回归；Vite 只用于构建/隔离开发服务，线上静态资源不运行 Vite 服务。Seroval 由 Solid 引入，当前未使用服务端 fromJSON/fromCrossJSON 反序列化，未将该库告警宣称为已证实线上 RCE。

上游参考：[DOMPurify](https://github.com/cure53/DOMPurify/releases/tag/3.4.15)、[Mermaid](https://github.com/mermaid-js/mermaid/releases/tag/mermaid@11.17.2)、[Vite](https://github.com/vitejs/vite/releases/tag/v7.3.6)、[Seroval 公告](https://github.com/advisories/GHSA-3rxj-6cgf-8cfw)。

## 兼容与回退

历史 PR-8B/8A 交付回执和 v4-v9 迁移脚本保持原样，在固定工作树验证。回退只使用兼容 v9 的成套版本；不降低 schema，不覆盖已有数据。源码候选未部署，运行服务未改变。
