# PR-9A 双 Agent 冻结评测契约

基线：`d3e4ea55db61bdbe9a9847a86548b32b9c5c9f6d`。数据库保持 schema v9；没有新增网络接口、表或模型调用。此阶段不修改运行站点。

## 评测集与层次

300 条固定合成用例：开发集180、固定集75、挑战集45。用例预期、分组和文件 SHA256 在执行前冻结，结果不得改写预期。分组按行为类别分层，再以稳定哈希分配。Agent 变体及同义句存在相关性，不能当作300种独立真实业务分布。

类别：路由140、Narrative40、DataUsage20、Claim40、计划安全30、上下文30。通过真实 Store/SQLite、TaskSpec、FactsState、受控 Bun 事实模块及 Result 投影执行；不调用公网模型或真实数据。历史上下文部分使用受控持久夹具构造，非真实取数端到端证明。

路由分别报告候选解析与最终 TaskSpec。正式 Query Mode、Intent、Method 门槛以最终 TaskSpec 为准；无 TaskSpec 的普通聊天视为无资料方法。Method 使用方法集合的精确一致判定，比仅检查部分命中更严格。

## 指标

Query Mode≥97%，Intent≥95%，Method精确一致≥95%。Agent隔离、历史/澄清不取数、计划外阻断、Claim来源对应、保护字段一致、unknown不写零、同行类型保持、已覆盖Narrative冲突规则均要求100%。同时检查整体和各分组；没有测量分母不构成通过。

指标分母是对应测试情形数，不能解释为真实用户准确率。Claim指标验证每个用例内所有生成Claim的来源和保护字段；拒绝情形也包含零有效Claim，因而必须结合正向完整事实用例及既有完整回归，不以该数字推断生产数据覆盖率。Narrative仅覆盖已声明规则，不能证明任意自由文本语义正确。

报告输入必须包含所有选定ID、正确分组、完整指标和严格布尔值；缺失、重复、伪造身份、非零pytest退出码及错误用例均拒绝。输出文件已存在则拒绝覆盖。保留首次失败与修复后结果，明确区分首次固定/挑战验证和整改回归。

## 本轮整改

1. 目标范围解析补充有限业务阅读用语，避免“查看同框资料”等被误认为未知对象。保留未知姓名、日期范围、账户和不支持输入的拒绝；不删除任意汉字，不扩展实际资料范围。
2. 在共享执行边界核对冻结场景的`records_snapshot_id`与全部冻结模块合同。模块名、集合与快照不一致时，尚未发起调用即拒绝。只比较本轮冻结资料，不访问当前最新夹具，历史旧版本不被重算。

## 复现

从`services/peixian-control`运行：

```sh
python -m pytest evaluation/test_cases.py --evaluation-split all --evaluation-output /tmp/evaluation-observations.json -q
```

从仓库根运行：

```sh
python deploy/peixian/evaluate-stage2.py /tmp/evaluation-observations.json --output /tmp/evaluation-report.json
```

需要Python3.12、锁定测试依赖及Bun1.3.14，`PX_BACKEND_V6=0`，`PEIXIAN_TEST_JS_COMMAND='["bun"]'`。测试自身建立隔离合成数据库；禁止指向运行控制库。评价CI独立上传观察记录和报告，仍执行Control/Gateway、前端与历史关账检查。

## 兼容及尚未覆盖

沿用PR-8.1 OpenAPI，无接口字段变更。当前开发集和固定集曾发现缺陷，修复后复跑不再称为首次盲测。挑战集第一次运行的结果单独记录。真实模型语言质量、线上A/B、备份恢复、独立人工PR审阅和真实业务资料不属于本阶段测试证明。
