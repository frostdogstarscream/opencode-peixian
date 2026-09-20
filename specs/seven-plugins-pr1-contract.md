# PR-1 七插件契约

来源编号 source_record_id 可以重复；source_row_id 在响应内唯一，缺省沿用唯一 record_id。record_id 保持旧协议唯一标识，不静默重写。重复业务流水保留，不依据哈希去重。evidence_id 为模块、快照、来源行标识的 SHA256，不是业务去重键。provenance 是与 items 一一对应的新增字段，原始记录不修改。历史协议仍可读取。

测试使用实际 records_service.Handler、1.5.1 夹具、共享 connection_policy.exchange 与真实 JS 入口，经两段本机 HTTP。16 项通过；不是已部署 Relay、Run、页面或模型验收。测试运行时可用 PEIXIAN_TEST_JS_COMMAND JSON 数组指定 Node/Bun 命令。未配置时使用 Node。

当前宿主无 Node，复用现有 Gateway 镜像内 Bun 在独立只读容器运行，未修改用户环境。源码摘要见 seven-plugins-pr1-manifest.json；最终发布须另外生成 ZIP 和镜像摘要。
