# 沛县公安数据插件字段与接口对齐记录

## 统一约定

- 对外适配接口全部使用 POST JSON；健康检查使用 GET。
- 时间使用带时区 ISO 8601，旧接口格式只在适配器内部转换。
- 成功响应使用 `schema_version`、`trace_id`、`source`、`queried_at`、`returned_count`、`total_count`、`page`、`items` 和 `warnings`。
- 空数据是成功响应；技术失败使用安全错误码，不透传上游正文。
- 当前文档中的真实凭据必须轮换，以下只记录环境变量名称。
- `legacy` 模式必须同时配置 `PEIXIAN_ADAPTER_TOKEN` 和独立随机的 `PEIXIAN_AUDIT_HMAC_KEY`；后者仅用于生成不可逆审计摘要，不得与上游凭据复用。

## 真实接口配置

| 数据域 | 地址变量 | 凭据变量 | 当前状态 |
|---|---|---|---|
| 人员档案 | `PEIXIAN_PROFILE_BASE_URL` | `PEIXIAN_PROFILE_*` | 地址和鉴权待正式确认 |
| 家庭关系 | `PEIXIAN_FAMILY_URL` | `PEIXIAN_FAMILY_API_KEY`、`APP_ID`、`APP_SECRET` | 请求与响应样例已有，正式契约待确认 |
| 人员轨迹 | `PEIXIAN_TRACKS_URL` | `PEIXIAN_TRACKS_API_KEY`、`APP_ID`、`APP_SECRET` | 参数类型和地点字段待确认 |
| 涉案人员 | `PEIXIAN_CASES_URL` | `PEIXIAN_CASES_API_KEY`、`APP_ID`、`APP_SECRET` | 样例需转换为合法 JSON，分页待确认 |
| 涉警人员 | `PEIXIAN_INCIDENTS_URL` | `PEIXIAN_INCIDENTS_API_KEY`、`APP_ID`、`APP_SECRET` | 分页和错误契约待确认 |

## 字段归一化

适配器只输出各响应模型声明的字段。主要映射为：

- 户籍：姓名、证件号码、户籍地址、户籍性质、管理状态、与户主关系、父母信息、职业；
- 家庭关系：关联人、关联证件号码、关系、年龄、采集时间和来源；
- 案件：案件编号、名称、类别、状态、发生时间、地址、摘要、单位和人员角色；
- 警情：接警编号、类别、时间、地点、摘要、单位和人员角色；
- 轨迹：记录 ID、抓拍时间、轨迹类型、地点、设备和车牌；
- 住宿、铁路、网吧：记录 ID、场所或车次、起止时间；
- 车辆：记录 ID、号牌、类型、品牌、颜色、车辆识别代号、登记时间和状态。

未知上游字段不自动透传。字段新增或语义变化必须更新响应模型、OpenAPI、插件测试和本记录。

## 尚未具备正式接口的能力

在库人员、同住址人员、人像关系、资金、通话、车辆共同使用、夜间高频聚合和多标识反查仍为 `Mock only / contract missing`。对应插件不创建、不发布，综合 Skill 不得生成相关结论。
