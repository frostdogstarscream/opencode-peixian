# 第五轮发布、版本与回退记录

## 匹配版本

- 服务器源码：/root/PeiXianDB/stage2-task-spec-v1
- 分支：codex/frontend-contracts
- 代码提交：a7f639ce2e3e9e219a517a3b1f1efffa20d10a8f
- 镜像：agent-platform-control:alignment5-a7f639ce2e3e
- 镜像身份：sha256:a09b4fb00afc11635f42cd8a7400367c32fa747343dad0d01edde203999ed7c9
- 数据库 schema：9，本轮无迁移。
- 镜像中 Control/shared 源码89文件与该提交工作区逐一一致；revision标签与代码提交一致。
- 运行版本 OpenAPI SHA256：5854af116eb3a94415ea7f1c6ca49728dbd0a3f8fa82adafc0bab3b93b00b23e
- CSS：index-DI4D4ule.css；SHA256 6939df9f518d754748bf99bb3b524f66b3aa47cd4d957630c4d8ed3da5eadd1b，与发布前一致。
- 文档在后续独立提交保存；镜像标签指向实现提交，不将文档提交冒充镜像构建源码。

## 发布过程

备份位于服务器受限目录 /root/peixian-source-backups/alignment5-20260922；包含发布前控制库、配置、代码与版本材料。私密配置及数据库不纳入Git或用户交付压缩包。

候选镜像使用已运行 alignment4 镜像作为固定摘要父镜像，复制当前提交的 control/shared 与本次构建的前端静态资源；没有临时下载依赖。构建配方及身份已留存。没有重新构建或替换 Agent、Gateway、Relay。

发布前核对当前运行镜像未被他人替换、无活动Run，备份控制库；进入 repair_only，停止Worker，通过 platform-manage.py up 执行受保护部署，恢复Worker，核对恢复责任清零后normal并确认A/B ready/open。没有覆盖同事 frontend-alignment 工作区未提交改动。

A配置 applied/desired=54，B=27，本轮不变；没有删除或重建账号持久卷。最终核对见 verification.json。

## 回退

原镜像仍保留：agent-platform-control:alignment4-40cb937a4cdc。
原镜像身份：sha256:d5318fc4e201e83318997a5da0c5306e91f0c56603f267c5d6a0f80647d51aee。

若需回退，应先核对没有并行发布及活动执行，保存当前配置和控制库，沿用平台维护/升级保护流程，将 images.control 恢复为原镜像，再运行受保护的 platform-manage.py up 并恢复Worker，检查运行环境与历史结果。旧版本与本轮均为schema9；不要通过降低schema、覆盖数据库或删除卷回退。新增会话、文件和结果需保留。

本轮未实际回退演练。旧前端忽略 outcome；旧执行规则不会给新请求生成本轮新增车辆证明，不能把回退后的能力视为仍启用。

## 交付范围

同目录包含接口说明、验收记录、OpenAPI、镜像身份、最终核对、HTTP及浏览器摘要、模型预算及SHA256。截图另存本地交付目录。源码和文档保存服务器本地提交，本轮不自动推送GitHub。

保存的是可追溯源码、已部署本地Docker镜像、构建配方与文档；本轮没有新建完整离线镜像导出包。
