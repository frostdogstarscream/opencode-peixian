# 涉赌 Agent V3 发布回执

用户确认允许后于2026-09-20发布。源码提交：7d97b37b66cc7ec54bf341bc5ba81a35c3bcf069。此回执更新此前开发回执中的“尚未发布”状态。

## 实际发布

入口：https://36.134.45.38:19460/

Control 镜像：sha256:66f5bbddf4ae8037122bc9bb53ec04d1f636875ee6e243a77c6a0b2024b984ea

Worker active，Control healthy；管理环境注册2个、重连2个、缺失0个。A ready revision46，B ready revision25。账号仍各有5个个人技能，未清理或覆盖。会话数量A43/B17保持不变。

125个前端静态文件哈希与发布前一致，未覆盖同事前端。只更新Control，未变更Agent/Gateway镜像和资料插件。Agent策略由Control向新受理Run提供，旧Run仍使用原冻结快照。

## 验证

- 发布前后端全量448 passed，2项依赖弃用警告。
- 发布前60个会话未发现活动Run，两账号均ready。
- 发布后两账号身份、技能、会话接口可访问，环境ready。
- 线上OpenAPI包含可选agent_id，枚举为gambling-assistant。
- 未知agent_id返回422，前后Run列表一致，无新增执行。
- 运行镜像中策略版本3.0.0，提示词摘要：d38d724f087fe1d6a0a47229f6f0a1baf4d7f30db9116b35e1d5726890de3b40。
- 本轮真实模型调用0次；没有重跑工具选择、回答质量、浏览器交互或并发验收。源码和部署通过不代表全部模型行为已验证。

## 备份与回退

控制卷备份：/srv/peixian-alignment-20260917/runtime/upgrade-backups/20260920T095342Z-1141be59

备份SHA256：2435eeea37f6d162cfdb8e0aed0fb1272272ec3ea1ddba37245fa653fa8e666d

数据库保持schema v6。本次为控制卷升级备份，不是全部用户持久卷完整备份；此前大改前完整代码归档仍保留。

上版配置存放在服务器私有发布目录的platform.before.json。回退时重新检查活动任务，停止写入并使用正式platform-manage工具恢复旧Control配置，保留新增数据。不得用旧数据库静默覆盖新增Run。前版不支持显式agent_id时客户端应省略该字段。

## 使用及剩余事项

现有页面选择涉赌技能，或在新执行中输入“整理涉赌资料”；无需新网址或新账号。没有新增独立Agent按钮。按接口拆插件、专项Skill拆分和强制代码调度仍是下一阶段。没有推送GitHub。
