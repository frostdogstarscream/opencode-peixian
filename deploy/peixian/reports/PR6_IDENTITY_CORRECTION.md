# N3-E 镜像身份更正（自动生成）

本次只读采集纠正旧字段分类，不覆盖旧报告，也不声称复原旧时刻现场。

更正来源：`deploy/peixian/reports/n3-local-evidence.json`。
采集批次：`8fde77fa8b28402b83e68fca1a33dbf8`。

| 对象 | 实际摘要 | 采集来源 |
|---|---|---|
| container_image_reference | `sha256:4d9d03022f03747df90bda78a203751ff224b5d8f68a68350638ac787b5a5b2f` | container_inspect |
| docker_image_inspect_id | `sha256:4d9d03022f03747df90bda78a203751ff224b5d8f68a68350638ac787b5a5b2f` | image_inspect |
| archive_config_digest | `sha256:77c12e51c3d9303782452662d6a2cdfa44c74ce6645e8138e8c070fb782fd442` | docker_save_config |
| archive_manifest_digest | `sha256:8fe115ab5227d0b07b21ec85399276ca4538ab53db503b351d43d601671dcb5e` | platform_manifest_descriptor |
| archive_index_digest | `sha256:4d9d03022f03747df90bda78a203751ff224b5d8f68a68350638ac787b5a5b2f` | selected_tag_descriptor |
| archive_catalog_digest | `sha256:c0323cf67d2e8d8f1a134cb1cb27ecf2373501988848a2f1fb4bcd389c5763f0` | index.json |

inspect 原始引用与 archive config 是不同对象。上述值依据归档描述符关系验证，不要求所有 SHA 相同。

Python 源码集合：预期和实际双向核对；不等同整个镜像验证。宿主磁盘源码不证明运行进程已加载版本。

回执归属计数：`{'batch': 0, 'historical': 169, 'other_batch': 0, 'unattributed': 0}`。只读批次不认领历史控制操作。

历史未确认记录：2；原操作结果及根因不能由当前状态反推。

**正式发布：blocked。** N4/N5、历史残余风险决定和完整运行身份仍需后续证据。

证据原始字节 SHA-256：`be9f8d8eae91c0d43737dbb9c4285e3a94fadfb1238dc68d76a47e3e2c2c2730`。
