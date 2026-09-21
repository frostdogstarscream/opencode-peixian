# PR-5.6 开发者能力与规则契约

基线：`8d33ec3d5ae61143164803ce3406e9b72a1819ba`。数据库保持 v6，Router v2、TaskSpec v2 和既有账号灰度开关不变。仅源码开发；不部署、不访问真实业务数据、不调用付费模型。

## 注册与发布

`control/developer_registry/data` 的三个固定 JSON 是开发者发布配置；没有在线编辑、目录扫描、任意代码或动态表达式。启动验证闭合字段、重复 ID、显式插件/工具/Schema 身份、Agent/Method 对应关系。七项能力登记为 published；这不赋予 Agent 新方法，也不替代账号安装、授权和 applied 配置检查。

能力和规则仅 published 可执行。其他五种状态均生成 completed 本地 Run，分别返回 capability_not_ready/rule_not_ready，没有投递记录或资料调用。首版只支持 required_rules，不提供隐式降级。

版本比较按三个非负整数，禁止前导零、前缀、预发布及构建后缀；只接受 =X.Y.Z 或 >=X.Y.Z <A.B.C。兼容范围不代表输出自动可信；仍核对冻结模块、数据快照、完整结构与记录，并要求实际安装版本与 applied 版本一致。

## 冻结与执行

新计划保存 capability-registry-v1、rule-registry-v1、method-dependency-v1；冻结完整能力与规则身份、插件版本、输出 Schema 和摘要。Control 在每次操作前重新核对当前发布状态与实际 applied 身份；Gateway 在执行插件前独立检查冻结摘要、模块、工具与规则绑定。

引擎按固定 implementation 白名单分派统计函数，保存 rule_executions。Control 核对实际完成模块与规则执行回执，缺失或错配不能成为事实表。统计算法仍使用原记录归属、北京时间、夜间窗口、原始流水和明确观测，不新增推断规则。历史持久结果只读，不因当前状态变化重算。

## API 兼容

无新增浏览器路由。原消息受理与 Run 返回结构兼容；非 published 的 task_response.code 有稳定错误码。证据增加可选 registry_provenance。内部冻结元数据不得由客户端指定。普通历史读取不重新查询注册表或资料服务。

## 维护边界

规则 implementation 的新版本必须作为受控源码发布，更新执行白名单与回归；不能仅改 JSON 字符串。现有七插件仍使用同一只读资料服务，不增加数据源。后续 PR-6/7 只能从本阶段关账提交继续。
