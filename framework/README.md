# AI 应用框架 · 0.1 初始化版

这个分支把已经验收的账号隔离、模型授权、插件、技能、文件和聊天能力作为基础，供不同业务项目重复使用。技术栈为 SolidJS + FastAPI + OpenCode + Docker。

当前是框架初始化版：已经有项目生成工具、统一品牌配置、独立部署入口和命名空间；业务模块注册、通用 RBAC、菜单管理和 CRUD 生成器仍在后续计划中。现有普通用户/管理员两类角色不等于完整 RBAC。

## 当前入口

- [project.json](project.json)：项目标识、中文名称、副标题、端口与实例上限，不放密钥。
- [project.schema.json](project.schema.json)：配置格式；Python 启动器执行同等校验。
- [new_project.py](new_project.py)：只从当前已提交模板生成干净的新项目。
- [manage.py](manage.py)：开发检查、首次初始化、镜像构建、启停与宿主执行器。
- [架构与扩展约定](ARCHITECTURE.md)：区分业务模块、插件和技能。
- [后续实施顺序](ROADMAP.md)：按快速开发的实际收益安排。
- 原控制层协议：[服务说明](../services/peixian-control/README.md)。

源码仍保留 `packages/peixian-console`、`services/peixian-control` 和 `deploy/peixian` 等兼容路径。用户界面的产品名称和新部署标识由本配置提供；不通过全局字符串替换改动已验证的底层协议。框架项目仅使用本目录启动器，旧部署命令及 A/B 迁移入口不属于新项目快速开始。

## 生成业务项目

在框架源码目录执行，目标父目录必须已存在，目标目录必须不存在：

```powershell
py -3.12 framework/new_project.py D:/Code/MyAssistant --project-id my-assistant --name "业务助手" --port 14200 --git-init
```

生成器要求模板工作区干净，导出 HEAD 中允许的源码和构建材料，保留 MIT 许可证与模板提交来源。不会复制 Git 历史、远程配置、账号、密钥、会话、数据卷、缓存、旧验收截图或 A/B 迁移脚本。`--git-init` 只初始化本地 Git，不提交、不创建远程仓库、不推送。

模板里被 Git 跟踪的安全符号链接会解析为同一导出集合中的普通文件，避免 Windows 需要额外创建符号链接权限；外部链接或循环会拒绝导出。生成目录出现写入错误时保留已生成内容供核查，不递归删除用户目录。

## 开发依赖

需要 Python 3.12、Git、Node/npm、Bun 1.3.14，以及 Docker Linux Engine。首次安装依赖、构建基础镜像需要可访问软件包源；离线交付需要预先准备镜像和依赖，本初始化版没有自动制作离线仓库。

在新业务项目根目录执行：

```powershell
py -3.12 -m venv services/peixian-control/.venv
services/peixian-control/.venv/Scripts/python.exe -m pip install -r services/peixian-control/requirements.lock
Set-Location packages/peixian-console
npm ci --workspaces=false --ignore-scripts --no-audit --no-fund
Set-Location ../..
```

控制层依赖是隔离虚拟环境，不使用其他业务项目的密钥、运行目录或 Python 包目录。Bun 不在 PATH 时可给 build 传 `--bun <实际路径>`。

## 首次部署

```powershell
services/peixian-control/.venv/Scripts/python.exe framework/manage.py doctor
services/peixian-control/.venv/Scripts/python.exe framework/manage.py init
services/peixian-control/.venv/Scripts/python.exe framework/manage.py build
services/peixian-control/.venv/Scripts/python.exe framework/manage.py up
```

doctor 只检查配置和工具是否存在，不宣称已经构建成功或 Docker 可用。init 首次生成独立管理员密码、加密主密钥和执行器凭据，后续运行保留它们。管理员账号为 `admin`，密码文件是 `framework/.secrets/console-admin.password`，首次登录必须修改。模型连接默认没有真实凭据，需管理员在控制台配置。

在第二个终端使用同一虚拟环境启动前台宿主执行器：

```powershell
services/peixian-control/.venv/Scripts/python.exe framework/manage.py worker
```

worker 负责自动开通和配置生效，需持续运行；本入口不注册 Windows 服务或开机任务。开发时可以用 `worker --once` 只处理一项任务。生产环境交给宿主服务管理器维护进程，不把 Docker socket 挂到控制台。

默认入口为 `http://127.0.0.1:14100`，实际以项目配置为准。端口已被占用时 up 拒绝，不停止其他进程；已经运行的部署请用 status 查看。stop 仅停止当前控制容器，保留账号容器及全部数据；要暂停普通用户环境，应先在管理界面逐个暂停并等待任务结束。

```powershell
services/peixian-control/.venv/Scripts/python.exe framework/manage.py status
services/peixian-control/.venv/Scripts/python.exe framework/manage.py stop
```

## 部署边界

- project_id 使用 1–16 个小写字母、数字或连字符，以字母开头。首次 init 后不能通过修改 project_id 复用已有状态；新项目必须用新目录。
- 每个项目有独立控制容器、镜像标签、数据卷、Cookie 名、执行器状态和账号资源前缀。同名控制容器或数据卷若属于另一源码目录，启动器在构建/启停/执行器操作前拒绝接管；已部署项目移动目录前需要明确设计迁移，不直接复用旧状态。框架模式关闭旧 A/B 导入/重试接口，也拒绝发布旧卷映射。
- **0.1 版同一 Docker Engine 只支持一个活跃项目的账号环境。** 发现其他项目或旧模式 Agent 运行时，执行器拒绝开通；当前操作系统用户的框架 worker 还共用宿主预算锁。该锁不是跨操作系统用户、远程 Engine 或集群调度方案。不宣称能在同一 Engine 并行运营多个项目。
- 每项目最多 4 个普通用户环境；当前沿用原来的 CPU/内存预算，容量不是根据空闲内存随意超售。
- 不同 Cookie 名避免同主机不同端口相互覆盖登录。浏览器 Cookie 不按端口保密；互不信任的应用使用不同主机名和独立 HTTPS Origin。
- 普通业务项目入口仅绑定回环，正式内网域名/TLS/Origin 应由部署配置明确提供。本版不自动扩大为公网监听。
- 前端品牌和开发代理在构建时读取 project.json；改名或端口后重新 build，init 更新部署定义。Vite 仅用于开发，5179 端口冲突时拒绝自动换端口。

Windows init 会收紧本项目私密目录权限。Linux 还需给控制容器 UID 10001 的三个绑定文件添加读取 ACL；在确认该 UID 归属后执行：

```sh
chmod 700 framework/.secrets
chmod 600 framework/.secrets/console-control.key framework/.secrets/console-worker.key framework/.secrets/console-admin.password
setfacl -m u:10001:r,m::r framework/.secrets/console-control.key framework/.secrets/console-worker.key framework/.secrets/console-admin.password
```

## 检查

```powershell
services/peixian-control/.venv/Scripts/python.exe -B -m pytest framework/tests -q
```

控制层和前端分别在各自包目录按 README 运行测试、类型检查与构建。原沛县验收报告只证明检查点版本；框架修改的验证范围见 [VALIDATION.md](VALIDATION.md)，不能直接沿用旧镜像摘要作为新框架验收。
