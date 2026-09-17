# N3-E 归档对象更正（自动生成）

本次仅检查既有镜像归档。Docker 引擎不可达，未重新观察运行容器；不覆盖旧证据。

| 组件 | 对象类型 | 原始字节 SHA-256 |
|---|---|---|
| agent | archive_config_digest | `sha256:0824f257eab28263b48d2d192b7022493ff2a3f7b1b3da1662c792b90792097c` |
| agent | archive_manifest_digest | `sha256:cebfa3bde71c22a10f8db35a443020db8640f52f0d97b829ffce716bf24737c3` |
| agent | archive_index_digest | `sha256:c267a0ec9213ae7ac0ce38ffcb787e2d8c52554cc797a080ff19578b23ca62cd` |
| agent | archive_catalog_digest | `sha256:c0323cf67d2e8d8f1a134cb1cb27ecf2373501988848a2f1fb4bcd389c5763f0` |
| control | archive_config_digest | `sha256:77c12e51c3d9303782452662d6a2cdfa44c74ce6645e8138e8c070fb782fd442` |
| control | archive_manifest_digest | `sha256:8fe115ab5227d0b07b21ec85399276ca4538ab53db503b351d43d601671dcb5e` |
| control | archive_index_digest | `sha256:4d9d03022f03747df90bda78a203751ff224b5d8f68a68350638ac787b5a5b2f` |
| control | archive_catalog_digest | `sha256:c0323cf67d2e8d8f1a134cb1cb27ecf2373501988848a2f1fb4bcd389c5763f0` |
| gateway | archive_config_digest | `sha256:42a7aa9fe526518b5f8f38650eacbfc7676b86debd5f386fb0273e002c97b6bd` |
| gateway | archive_manifest_digest | `sha256:438b12d25a3ce43a197ef8d01e5386e08ff7b6987bdec22fccc1065f0c27c9f4` |
| gateway | archive_index_digest | `sha256:daf6e49d86433f8e85acb9ba9e11080f5d9b96d393f2141bdcfff67e963b2f7e` |
| gateway | archive_catalog_digest | `sha256:c0323cf67d2e8d8f1a134cb1cb27ecf2373501988848a2f1fb4bcd389c5763f0` |
| proxy | archive_config_digest | `sha256:c318e336065b17ff460aeac6d14bce5d0b13e35f25d5cb1843b635359fc00c9a` |
| proxy | archive_manifest_digest | `sha256:09ab424a8c788f8d0fe3a64429f6d19dfa526885c8609b748d0943a75dcb9f8c` |
| proxy | archive_index_digest | `sha256:30f1c0d78e0ad60901648be663a710bdadf19e4c10ac6782c235200619158284` |
| proxy | archive_catalog_digest | `sha256:c0323cf67d2e8d8f1a134cb1cb27ecf2373501988848a2f1fb4bcd389c5763f0` |

旧 JSON 的 image_config_id 取自 Docker inspect Id，不是从归档 config 字节计算。
本归档描述符链证明旧 Markdown 的 config 值有归档依据；旧 JSON 字段名称需要更正，不能据此断言部署了错误镜像。
当前运行引用和 Worker 加载版本仍未重新验证；历史现场不能完全复原。

归档原始字节 SHA-256：`2c49bcc413ad68e43a4d8f42f8ca02dc0d9037bc61ed226636cd842dcca8100c`。
源码归档提交：`1b3fff97ecc7a90f1620df1527117b5ab0daa5ea`。
**PR-6 发布状态：blocked。**
