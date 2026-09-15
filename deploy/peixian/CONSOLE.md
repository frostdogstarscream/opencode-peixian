# 沛县 OpenCode 控制台

## 三角色版本说明

本分支 `codex/peixian-p0-hardening` 使用 `super_admin/admin/user`。超级管理员管理普通用户和管理员，并独占平台插件、插件授权、现有模板及独立空间维护；管理员管理全部普通用户、模型和只读脱敏管理记录，不能操作插件授权、部门组织或独立环境维护。两个管理角色均无业务 runtime；普通用户保留个人 Skill 和已授权插件配置、启停及允许版本切换。

普通用户从停用变为启用（active: false → true）时，服务端在同一事务内检查并预留容量、排入 resume，随后由执行器恢复原环境；管理员可通过“启用账号”完成这一业务动作，无需独立 runtime 权限。若停用引发的 pause 尚未完成，或没有可用名额，返回 409 并回滚本次启用，账号继续保持停用；待暂停完成或释放名额后再试。已经 active、只是被超级管理员手动暂停空间的用户，不会因修改其他设置或重复启用而自动恢复，仍须超级管理员“恢复空间”。

旧 admin 的一次性迁移、旧认证撤销、schema 2 兼容检查与控制库备份见 [三角色说明](ROLES.md)。本次只调整现有模板权限，正式部门公共 Skill 的唯一审核主体已定为超级管理员，完整审核发布流程仍在正式方案批次 D。文档更新不证明运行迁移、部署或审核发布已验收。

> 详细操作步骤见 [使用手册](USER_GUIDE.md)，或打开 [离线阅读版](USER_GUIDE.html)。涵盖超级管理员、管理员、普通用户、Python 调用、日常维护和常见问题。

## 范围

本分支以 `c5632f795b4efefdaf6d31c24c120a1761ff6b98` 为部署检查点，保留 OpenCode `v1.18.30` 的模型推理和会话格式，新增账号控制层、中文界面、每账号运行环境、托管插件/技能配置与办公文件解析。

本机统一入口为 **http://127.0.0.1:14090**。初始化账号名为 `admin`，三角色版中角色为 `super_admin`，初始密码由初始化脚本生成，保存到本目录 `.secrets/console-admin.password`。首次登录强制改密。验收过程中使用的最终管理员密码保存在 `.secrets/console-admin-current.password`，不会显示在报告、镜像或 Git 中。

用户通过账号登录；同一账号更换设备仍访问同一私有环境。持有密码或该账号有效令牌的人能够访问该账号数据，本期没有物理设备绑定。

## 结构与职责

| 组件 | 代码位置 | 职责 |
| --- | --- | --- |
| 中文前端 | `packages/peixian-console` | 对话、文件、技能、插件、个人设置与管理员页面 |
| 控制 API | `services/peixian-control/control` | 认证、授权、SQLite 元数据、配置版本、任务与审计 |
| 宿主执行器 | `deploy/peixian/console-worker.py` | 受保护任务领取、心跳、固定模板开通和生命周期管理 |
| 运行模板 | `deploy/peixian/console-runtime.py` | 独立网络/卷、不可变发布目录、配置应用、健康检查与回退 |
| 账号网关 | `services/peixian-control/gateway` | 明确 OpenCode 路由、私有文件、解析、结果下载、插件探针 |
| 模型出口 | `gateway/model_relay.py` | 限定授权平台模型标识、映射实际模型、注入服务端凭据 |
| 托管核心 | `packages/opencode/src/config/peixian.ts` 等 | 拒绝非托管配置、运行时安装和可写目录中的插件/工具加载 |

控制容器不挂 Docker socket，也不挂用户工作区。宿主执行器只接受平台生成的实例 ID、预置镜像和确定的操作类型。每个普通用户账号拥有 Agent、网关、模型出口、HOME/workspace/files 卷和独立网络；新账号没有宿主公开端口。模型凭据只挂给该账号的模型出口，插件运行参数只发布给该账号。

托管文件工具只允许账号工作区和只读上传区；路径先检查真实位置，不能通过链接读取 HOME、托管配置、实例凭据或其他系统目录。授权顺序按发布配置保留，默认允许本账号文件读写、技能和业务追问，拒绝 Shell、任意外网及原生配置写入。

账号 Agent 的网络没有公网出口。其网关只提供白名单 API，不提供任意 HTTP 代理。模型出口拥有联网路径，但应用只转发到管理员配置的固定模型 URL，禁止调用方修改上游或重定向。Linux 宿主或 Docker 管理员仍属于可信运维边界。

## 操作

首次旧库升级与普通重启不同：先 build，再 worker-stop、stop、backup、up、worker-start；每步成功后才继续。up/start 会调用 schema 兼容检查，并使用该次校验返回的不可变 image_id 设置 PEIXIAN_CONTROL_IMAGE 后启动，避免可变标签竞态；backup 要求停写。备份只含 control-data，不含用户卷与独立密钥，完整顺序和 Linux 对应方式见 [ROLES.md](ROLES.md)。以下初始化步骤用于全新环境，不要用 init 覆盖已有账号。

Windows PowerShell 从仓库根目录执行：

```powershell
# Python 3.12、Bun 1.3.14、Docker Desktop Linux 引擎应已可用。
# Python 环境只安装到本项目，勿使用其它项目或全局生产环境。
py -3.12 -m venv services/peixian-control/.venv
& '.\services\peixian-control\.venv\Scripts\python.exe' -m pip install -r services/peixian-control/requirements.lock
bun install --frozen-lockfile --ignore-scripts
deploy/peixian/console.ps1 init
deploy/peixian/console.ps1 build
deploy/peixian/console.ps1 up
deploy/peixian/console.ps1 worker-start
deploy/peixian/console.ps1 status
```

`console.ps1` 固定使用仓库下 `services/peixian-control/.venv/Scripts/python.exe`，不会回退到系统 Python，也不使用旧一期 `deploy/peixian/.venv`。以上创建环境命令使用 Windows Python Launcher 选择 3.12；若未安装 Launcher，应使用已安装的 Python 3.12 解释器完整路径创建同一目录。

`worker` 在前台运行，适合诊断；`worker-start` 隐藏启动受跟踪的宿主进程，`worker-stop` 只停止脚本记录且命令行匹配的执行器，若有运行任务则拒绝停止。Windows 重启后确认 Docker 引擎就绪，再执行 `up` 和 `worker-start`。Linux 可按 [运行与迁移说明](CONSOLE_OPERATIONS.md) 配置 systemd 常驻。

Windows 的 `worker-start` 是隐藏的受跟踪进程，不注册系统服务或开机任务，也不提供进程崩溃后的自动拉起。必须保持同一 `state-root` 只有一个执行器；前台 `worker`、后台执行器和迁移脚本使用同一个宿主锁，不应通过更换状态目录绕过该约束。控制 API 也保持单 uvicorn worker，不能将宿主执行器与 Web 进程的数量混为一谈。

`stop` 只停止控制台容器，不删除数据、不自动停止各账号。账号空间的独立暂停和恢复仅由超级管理员在“用户管理”执行；停用账号还会立即撤销登录和访问令牌。暂停不等同于停用。不要执行 `docker compose down -v`；本项目脚本不提供默认清空数据。

第一次普通用户开通期间显示准备状态。已登录用户直接进入自己的对话首页，不需要添加项目。默认最多运行 4 个普通账号，实例资源预算如下：

| 组件 | CPU 上限 | 内存上限 |
| --- | ---: | ---: |
| OpenCode Agent | 2 | 2 GiB |
| 文件网关 | 0.5 | 512 MiB |
| 模型出口 | 0.5 | 128 MiB |
| 每账号合计 | 3 | 2.625 GiB |
| 公共控制台 | 1 | 512 MiB |

这些是容器限制，不表示空闲时固定占用。1 GiB 只限制原始上传文件，HOME 和成果工作区暂未设置整卷磁盘配额。宿主执行器在开通前校验 Docker 引擎总预算。默认还预留 1 GiB 系统余量；其他项目实际资源消耗需运维单独纳入容量规划。

## 插件与技能

超级管理员上传包含 `manifest.json` 和预打包 `.mjs` 的 ZIP。版本不可覆盖。首版不在服务器运行 npm 安装、构建脚本或原生扩展。下面为合成插件结构，真实业务插件不在本期范围。

```json
{
  "id": "sample",
  "version": "1.0.0",
  "name": "示例能力",
  "description": "用途说明",
  "opencode_version": "1.18.30",
  "entry": "entry.mjs",
  "tools": ["sample_lookup"],
  "display": {
    "input_fields": ["query"],
    "output_fields": ["count", "summary"]
  },
  "config_schema": {
    "type": "object",
    "properties": {
      "label": { "type": "string", "title": "显示名称" },
      "credential": { "type": "string", "title": "访问凭据", "writeOnly": true, "format": "password" }
    },
    "required": ["label", "credential"],
    "additionalProperties": false
  }
}
```

插件默认导出为 `async (context, options) => hooks`，沿用 OpenCode Plugin hooks；`options` 是用户自己的配置。可选导出 `async test(options)` 返回 `{ok:boolean,message:string}`。没有 `test` 的插件不会伪报“连接成功”。探针运行已发布代码，10 秒超时；返回页面的文字根据结果生成，插件原始日志不会发给用户。

配置表单支持嵌套对象、普通标量和标量数组；对象必须关闭额外字段，凭据使用独立密码字段，不支持任意 JSON 或包含凭据的数组。已安装版本使用该版本的 Schema 脱敏，缺失版本定义时隐藏配置。

工具详情只显示超级管理员发布清单明确列出的输入/输出业务字段，并额外屏蔽疑似凭据、地址、路径与命令字段。普通用户不能上传任意插件代码，插件在该账号容器内运行；超级管理员发布包需要承担代码审核责任。

个人技能使用“名称、用途、指令内容”表单和文本导入。公共模板复制成个人副本，后续模板修改不覆盖副本。技能测试验证是否实际加载；具体分析效果仍需通过真实对话评估。插件和技能保存后有“待生效”状态，不能把保存成功等同于运行环境已更新。

配置应用顺序：生成完整版本 → 停止接受新消息 → 等待当前会话空闲 → 替换该账号服务 → 验证网关版本、原生健康和技能加载 → 提交成功；失败尝试恢复上一发布。忙碌超过 5 分钟保留待生效，不强行中断。其他账号继续运行。

## 文件与模型

支持 TXT、MD、CSV、XLSX、文字 PDF 和 DOCX。XLSX 只读取已有缓存值，DOCX 读取正文及表格，PDF 只提取文字层。扫描 PDF 明确为“无文字/需要 OCR”，不会当成功解析。没有宏、公式计算、OCR、旧 DOC/XLS 或办公程序执行。

单文件 20 MiB、原始上传总额每账号 1 GiB、解析并发 1、60 秒超时、ZIP 展开 200 MiB。解析子进程限制为 384 MiB 地址空间，受网关 512 MiB 总内存限制；超大或复杂文档可能返回资源超限。文件 ID 对应不可变的原始上传版本，重名上传是不同文件。预览保留页码/表名/行位置；对话引用也携带来源。

每次最多 5 个文件及 5 个技能。首版使用保守上下文预算：问题、选中技能内容及带来源的文件引用合计不超过 18,000 UTF-8 字节，超出时要求用户拆分资料，不静默截断。文件解析输出本身最多一百万字符，截断明确标为部分成功。部分解析或截断的文件可以预览已提取范围，但首版不能直接送入对话，须拆分重传。

超级管理员或管理员配置 OpenAI 兼容 `/v1` 地址及实际模型 ID，并分配用户授权。浏览器只发送平台模型 ID，实际地址和密钥由后端处理；辅助模型也从授权集合选择。当前本机验证使用 DeepSeek 官方 `deepseek-flash`；实际内网 vLLM 地址未提供，不能视为真实内网联调通过。

## API、验证与交付

所有业务接口位于 `/api/console/v1`，不会透传任意 OpenCode 路径。浏览器使用 HttpOnly Cookie、SameSite 和写入 CSRF 验证；Python 使用个人可撤销令牌或账号登录得到的内存会话。令牌只创建时返回明文。密码 Argon2id 哈希，模型/插件秘密使用主密钥加密保存。

[OpenAPI 静态文档](../../services/peixian-control/docs/openapi.json) 可离线查看；运行时契约位于 `/openapi.json`，不依赖外网 Swagger 资源。

[Python 客户端示例](../../services/peixian-control/examples/console_client.py) 覆盖登录、改密、令牌、上传、解析、会话、消息、SSE 和停止。SSE 只发送刷新通知；控制层按账号暂存当前原生文字增量，客户端回读经过筛选的消息，并按消息 ID 合并。每账号只有一个事件连接更新缓存；原生持久化全文优先。缓存上限为每段 256 KiB、每账号 1 MiB、全部账号 4 MiB，文字保留最多 5 分钟；断线接管时丢弃有缺口的临时部分，最终历史会补齐，不提供事件重播。退出、停用或令牌撤销后，连接在下一轮身份检查时关闭。

验收命令和结果记录在 [验收报告](CONSOLE_ACCEPTANCE.md)。构建与单元测试不等同于真实模型或浏览器验收；报告分别列出已执行、兼容测试与未执行项。

`deploy/peixian/console.ps1 export` 导出三个镜像及 SHA-256 文件到 `deploy/peixian/dist/console`。完成本地提交后，运行项目 Python 执行 `deploy/peixian/console-release.py`，生成关联源码提交、镜像 ID 和前端资源的 `release-manifest.json`。源码、部署脚本与文档可提交；`.secrets`、`.runtime`、数据卷、快照、浏览器认证状态、镜像包均不提交。原始部署镜像和历史导出包保留。远程推送和真实内网部署需另行安排。
