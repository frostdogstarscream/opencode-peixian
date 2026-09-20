# 1.5.1发布中间回执：恢复确认待完成

已发布Control镜像 sha256:35ee8f1e0925173d638aa5935b737b4fc636d0dceca7e5a60822a62577c1a7ad，源码8c887b80a。前端静态资源未改变。
独立资料服务发布目录 releases/1.5.1，新增30-version-1.5.1.conf覆盖项；原目录及旧文件保留。七模块真实HTTP与冻结JSON完全一致，共186条，未鉴权401。
插件1.5.1已发布并绑定原连接；A已保存安装配置，尚未恢复运行。B尚未安装1.5.1。
443项后端测试与六组多页浏览器测试通过。本轮尚无新模型请求；累计沿用19/40。

B修复证据：Gateway created、Agent与Relay running。停止B所有组件后，完整观测确认三个组件stopped，但宿主mutation.json仍记录旧任务ff4174d87af046c0ade92a5364d11dde为running；系统将其判定unknown。正常暂停任务因此拒绝完成，不直接修改控制库。
人工恢复方案为：暂停Worker、取得独占锁、检查没有相关Docker变更进程，备份旧记录并记录全停证据后，核销旧宿主变更，再经正常暂停/恢复闭环。但自动审批拒绝人工改状态，要求明确授权；该核销操作尚未执行，已向用户提出授权问题。

A在发布前正常暂停以保证资料服务切换无活动请求。安装1.5.1后恢复请求被runtime_capacity_unverified拒绝；不能将保存配置称为已生效，也不绕过容量保护直接启动容器。
当前发布不是完成验收：两个账号暂不可开展新的真实联调，需先完成上述恢复确认。历史会话、文件、卷及控制库保留。

当前状态：
{
  "accounts": {
    "alignment-a": {
      "status": "paused",
      "revision": 43,
      "desired": 44,
      "recovery_required": false,
      "gate_policy": "closed"
    },
    "alignment-b": {
      "status": "failed",
      "revision": 21,
      "desired": 22,
      "recovery_required": true,
      "gate_policy": "closed"
    }
  },
  "maintenance": {
    "mode": "normal",
    "state_version": 121,
    "capacity_healthy": false,
    "recovery_required": 1,
    "security_pending": 0,
    "safety_sync_failures": 0
  }
}
