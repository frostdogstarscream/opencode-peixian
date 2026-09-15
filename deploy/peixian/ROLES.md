# 三角色权限与升级说明

> 适用分支：`codex/peixian-p0-hardening`；控制镜像：`peixian-control:console-r2-roles`；OpenCode 核心仍为 1.18.30。
>
> 本文记录本轮已确定的权限和迁移合同，以及已写入脚本的操作方式。文档更新本身不证明实际迁移、部署或正式 Skill 审核发布已验收。使用前核对对应版本的测试与运行记录。

## 角色与导航

| 角色 | 主导航 | 管理中心页签 | 业务 runtime |
| --- | --- | --- | --- |
| 超级管理员 super_admin | 管理中心、个人设置 | 用户管理、模型管理、插件发布、技能模板、操作记录；用户页内另有空间任务 | 无 |
| 管理员 admin | 管理中心、个人设置 | 用户管理、模型管理、操作记录 | 无 |
| 普通用户 user | 智能对话、我的文件、分析技能、业务插件、个人设置 | 无 | 按账号分配 |

管理员管理全部普通用户，不按创建者缩小范围。两种管理角色不能通过普通业务 API 访问用户对话、文件或模型调用，也没有自己的 Agent/Gateway/Relay、业务卷或普通用户运行名额。

用户继续使用自己的个人 Skill 和已授权插件：个人 Skill 创建、导入、编辑、启停与回退保留；插件个人配置、测试、启停及允许版本切换保留。平台插件授权只能由超级管理员管理，用户不能自己上传任意插件包。

## 操作权限矩阵

| 操作 | super_admin | admin | user |
| --- | --- | --- | --- |
| 创建普通用户、管理其启停和重置 | 允许 | 允许，目标只能 user | 拒绝 |
| 创建、启停或重置管理员 | 允许 | 拒绝 | 拒绝 |
| 创建或通过普通管理接口编辑超级管理员 | 拒绝 | 拒绝 | 拒绝 |
| 编辑既有账号 role | 拒绝，不提供升降级 | 拒绝 | 拒绝 |
| 管理模型连接、测试、默认、启停和普通用户模型授权 | 允许 | 允许 | 只能选择本人已授权模型 |
| 平台插件发布、版本状态、用户插件授权 | 允许 | 拒绝 | 仅个人安装配置 |
| 现有公共技能模板管理 | 允许 | 拒绝 | 可复制成个人 Skill |
| 独立暂停/恢复/重试/应用用户空间、环境任务列表 | 允许 | 拒绝 | 拒绝 |
| 只读脱敏管理审计 | 允许 | 允许 | 拒绝 |
| 部门、组织和归属编辑 | 本次不新增该功能 | 不授权 | 不授权 |
| 本人改密、本人程序令牌 | 允许 | 允许 | 允许 |

“模型管理”以当前已有接口为限：创建、编辑、测试、默认与停用继续保留；不要由 CRUD 字样推断已有 DELETE 模型接口。账号永久删除、管理员代登录、角色升降级也不在本次范围。

管理员创建普通用户会自动排入 provision；停用普通用户会自动撤销登录并排入 pause；模型或授权修改可以自动产生 apply。这些是已授权业务操作的必要后台动作，不授予管理员手动调用运行环境接口的权限。普通用户从停用变为启用（active: false → true）时，服务端在同一事务内检查并预留容量、排入 resume，随后由执行器恢复原环境；管理员可通过“启用账号”完成这一业务动作，无需独立 runtime 权限。若停用引发的 pause 尚未完成，或没有可用名额，返回 409 并回滚本次启用，账号继续保持停用；待暂停完成或释放名额后再试。已经 active、只是被超级管理员手动暂停空间的用户，不会因修改其他设置或重复启用而自动恢复，仍须超级管理员“恢复空间”。

超级管理员可以创建 admin 或 user。表单“账号角色”选择管理员时，只填写账号和初始密码，提交按钮为“创建管理员”；不会出现模型/插件授权或开通空间。管理列表中的超级管理员没有普通管理操作，其本人改密使用个人设置。

## API 合同

路径继续沿用 /api/console/v1，角色变化不重命名全部接口：

- POST /admin/users 默认 role=user；仅超级管理员可指定 role=admin。禁止 role=super_admin。
- 创建 admin 仅接收 username、可选 password、role，不接受 model_ids/plugin_ids，不产生 runtime 或环境 job。
- 管理员创建或编辑 user 只能发送 model_ids，必须省略 plugin_ids；即使 plugin_ids=[] 也拒绝，避免无权请求清空旧授权。
- PATCH /admin/users/{uid} 不接受 role；管理员目标只能是 user，超级管理员可管理 user/admin，目标 super_admin 拒绝。
- 用户重置密码遵循同样目标角色限制，修改部门/组织/归属不在允许字段中。
- /admin/plugins、/admin/templates、/admin/jobs、/admin/users/{uid}/runtime/* 仅超级管理员使用。
- /admin/models 与 /admin/audit 分别允许两种管理角色；审计只读、按受控字段脱敏，支持 actor（精确账号 ID）、action（允许动作）、result（success/denied/failed）筛选，最多返回 500 条匹配记录。
- login/me 返回服务端生成的 capabilities。它用于导航与请求构造，不取代各接口重新鉴权。
- 本人业务 /skills、/plugins、会话和文件入口仍只给 user；管理令牌不会变成用户业务访问凭据。

审计应能区分 success、denied、failed，保留稳定动作、操作者和可核对目标，不把原始内部审计负载、凭据、路径或业务全文直接返回。当前精确请求/响应字段以本分支生成的 [OpenAPI](../../services/peixian-control/docs/openapi.json) 为准。

## 部门公共 Skill：职责已定，正式流程待批次 D

部门公共 Skill 的审核、发布、授权与下架只属于超级管理员。“唯一审核主体”指角色唯一，不引入额外审核员角色，也不把 admin 变成部门管理员。

本次只调整现有模板管理的权限。正式公共 Skill 仍需实现提交、审核意见、退回、不可变版本、依赖与输入输出合同、授权生效及撤回流程，不能将模板保存或复制称作正式审核通过。普通用户个人 Skill 保留，不受公共 Skill 管理角色调整影响。

[正式方案 v1.1](FORMAL_PLAN_v1.1.md) §6、§14、§16、§17 记录本次角色合同与验收；TBD09 中角色归属已决定，剩余发布流程按批次 D 实现。

## 旧账号迁移规则

控制库以 PRAGMA user_version 标记 schema，三角色目标版本为 2：

1. 旧 schema=0 中旧 role=admin 一次性迁为 super_admin。
2. 保留 UID、用户名和密码哈希；增加 auth_version 并撤销旧认证记录。
3. 完成后写入新 schema 版本。再次启动不能把后来新建的 admin 再提权。
4. 全新安装保持初始账号名 admin，角色为 super_admin，不分配业务 runtime。
5. 不因角色迁移重建或删除普通用户 HOME/workspace/files，不迁移其会话正文。

账号名 admin 与角色 admin 是不同概念。升级后的原账号可能仍叫 admin，却拥有 super_admin 角色；新建的 admin 角色账号只是受限管理员。被迁移旧管理员的 Cookie/Bearer 会失效，需要重新登录，按需要重新创建个人程序令牌。

迁移不能代替密码恢复；不要重跑初始化覆盖未知账号，也不要手工改角色或降低 schema 值来绕过兼容检查。

## 兼容检查与升级备份

console-guard.py 提供 check 和 backup；默认使用同目录 compose.console.yaml，备份放在 Git 忽略的 .runtime/role-backups。

- check 核对控制数据 schema 与目标镜像声明的兼容范围。新镜像声明 schema min=0/max=2；旧未声明兼容标签的历史镜像只按 schema 0 处理。
- 现有旧库升级到 schema 2 前，需要控制卷停写且存在与当前状态匹配的已校验备份。
- backup 要求控制卷没有运行消费者，归档后核对文件摘要与状态；部分失败记录保留。
- console.ps1 的 up/start 会先执行兼容检查，并验证结果 status=passed、image_id 为完整 sha256；随后临时设置 PEIXIAN_CONTROL_IMAGE 为该不可变镜像 ID，执行 compose up --no-build --pull never --wait，完成后恢复原环境变量，防止校验后的标签被重建替换。
- backup action 还要求受跟踪宿主 Worker 已停。
- guard 只能保护这些脚本入口，不能阻止拥有宿主 Docker 权限的人手工绕过。不要直接启动旧镜像连接新库。

备份范围只有 control-data：控制数据库和该卷内发布包等文件。它不是全平台一致性备份，不包含普通用户卷、独立模型密钥、宿主全部发布目录或其他外部数据。对应控制加密密钥需要独立保护，否则加密配置无法恢复。新备份不会取代已有用户数据备份制度。

### Windows 升级顺序

以下从仓库根目录执行，先确认当前任务可安全结束、已有用户卷与旧镜像已按运维制度保护。build 构建本分支镜像，不需要重复初始化；如只变更控制镜像，可由运维按实际构建范围缩小，本文不额外发明构建选项。

~~~powershell
Set-Location -LiteralPath 'D:\Code\PeiXianDB\opencode'
.\deploy\peixian\console.ps1 -Action build
.\deploy\peixian\console.ps1 -Action worker-stop
.\deploy\peixian\console.ps1 -Action stop
.\deploy\peixian\console.ps1 -Action backup
.\deploy\peixian\console.ps1 -Action up
.\deploy\peixian\console.ps1 -Action worker-start
.\deploy\peixian\console.ps1 -Action status
~~~

必须逐步检查退出结果。Worker 忙、控制卷仍被使用、备份失败或兼容检查拒绝时，先处理原因，不能跳过失败直接 up。控制台暂时停止不自动停止普通用户实例；这次 control-data 备份不声称冻结所有用户数据。

启动后分开核对控制健康、schema/角色迁移、旧认证失效、三角色界面与直接 API 权限，以及既有普通用户数据。本文提供流程，不声称上述步骤已经在本轮运行成功。

### Linux 对应方式

先停止并确认实际部署的宿主 Worker systemd 服务；服务名由部署单元决定，不能把示例名称当作已安装事实。进入仓库根目录，用本项目 Python：

~~~bash
# 执行前：实际宿主 Worker 已安全停止，项目 Python 和本地目标镜像已准备。
docker compose -f deploy/peixian/compose.console.yaml stop
services/peixian-control/.venv/bin/python deploy/peixian/console-guard.py backup || exit 1
peixian_guard_json="$(services/peixian-control/.venv/bin/python deploy/peixian/console-guard.py check)" || exit 1
peixian_checked_image="$(printf '%s' "$peixian_guard_json" | services/peixian-control/.venv/bin/python -c 'import json,re,sys; value=json.load(sys.stdin); image=value.get("image_id",""); assert value.get("status")=="passed" and re.fullmatch(r"sha256:[0-9a-f]{64}", image), "Invalid guard result"; print(image)')" || exit 1
PEIXIAN_CONTROL_IMAGE="$peixian_checked_image" docker compose -f deploy/peixian/compose.console.yaml up -d --no-build --pull never --wait
~~~

每一步成功后再继续；最后按实际 systemd 服务名启动宿主 Worker 并核对状态。Linux 直接 compose up 不会自动调用 PowerShell 中的 guard，因此不能省略 check，也不能在校验后重新按可变标签启动。上例读取同一次校验返回的 image_id，限定为 sha256 格式后传给 Compose；失败即停止，不回退到默认标签。此处为 Linux 操作示例，本轮未执行 Linux 部署测试。

### 核查旧镜像与回退边界

可单独检查某个已保留旧镜像的兼容性，不启动它：

~~~powershell
& '.\services\peixian-control\.venv\Scripts\python.exe' '.\deploy\peixian\console-guard.py' check --image peixian-control:console-r1
~~~

新 schema 与旧 r1 不兼容时，应得到拒绝，不能把“旧镜像仍在”理解为可直接回退。需要恢复时，保留当前库、升级备份和新增数据，在独立位置验证匹配的旧控制库、发布包、密钥与镜像；不得直接用旧备份覆盖唯一正在使用的控制库。恢复属于独立运维程序，本次没有提供自动降级或通用 restore 命令。

## 验证要求与未验证项

应分别记录以下证据：

- 新库初始化角色；旧库一次性迁移；重复启动；被迁移旧管理员的 Cookie/Bearer 失效；UID/密码保持。
- admin 对插件/模板/插件授权/环境维护/jobs/其他管理账号/角色字段的直接拒绝。
- 停用用户重新启用时原子预留并恢复；pause 未完成/容量不足时 409 且账号仍停用；对 active 但手动暂停的用户重复编辑不越权恢复。
- super 创建 admin 不产生 runtime/jobs，创建 user 仍按原流程开通。
- 两管理角色只读脱敏审计，不能冒用普通用户业务接口。
- 用户个人 Skill、插件配置与允许版本切换回归；普通用户既有会话和文件保持。
- 备份摘要、兼容拦截、迁移中断与独立恢复检查；实际部署状态和目标网络验证。

原控制台已有合成和模型验收仅覆盖原功能，不能直接算作本次三角色迁移验收。正式公共 Skill 审核发布仍待批次 D；文档、单元测试、镜像构建和运行部署应分别说明。
