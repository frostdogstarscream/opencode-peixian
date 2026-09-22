# PR-9B 发布治理与候选制品

基线 `e6db3296537d2d201e64b2c7f9ec4a99fda524f7`。只增加治理、隔离构建及严格打包工具，运行数据和数据库结构不变。

## 分支与审阅

开发分支为`codex/stage2-release-governance-v1`。发布基准分支为`codex/stage2-release`：首次以通过CI的实现提交建立，随即启用保护。之后禁止直接更新、强推和删除，要求至少一位审阅者、代码所有者审阅、末次推送由他人批准、旧批准失效、解决全部对话及全部必需检查。没有管理员绕过名单。不改变官方上游基线分支。

CODEOWNERS覆盖平台关键目录，保留上游app/desktop原配置。当前登记维护者为仓库所有者，新增同事须先具备仓库权限再更新CODEOWNERS。开启“至少一次审阅”与“本次已经由独立同事审阅”是两种证据；本轮不会自批PR或伪造人工审阅记录。

## 必需检查

14个名字与用户计划一致，绑定实际GitHub Actions应用。Registry、TaskSpec、Context、Clarification、Claim、Result、Migration、SevenPlugin及Historical检查覆盖在完整core套件内；前端和Evaluation分别依赖各自完整套件。独立必需状态使用`always()`检查对应套件，失败、取消、跳过均不能变为成功。它们是覆盖套件的发布门禁，不宣称14套相互独立测试。

GitHub规则由`stage2-governance.py --render-rules`生成；API写入后必须使用`--verify-rules`检查实际读回结果。源码模板不是保护生效证据。

## 匹配构建

`stage2-build.py`要求干净Git提交，在新私密目录归档源码。Agent根锁文件及各复用工作区package.json必须与依赖提供目录一致；依赖复制到新目录，不能经链接加载旧工作区源码。前端package.json/package-lock必须匹配独立锁定依赖目录。编译、原生依赖修复及测试只在新目录运行，并使用独立HOME/XDG目录。

构建Control、Gateway、Agent三个镜像，基础镜像固定为本机已有不可变镜像ID；镜像标签不能覆盖。先执行Agent持久回执测试和前端类型/构建，再生成镜像。镜像记录实际SOURCE_REVISION；Control声明schema最大版本9。构建不启动容器，也不修改站点。

## 严格制品

`stage2-artifact.py`生成候选`stage2-dual-agent-v1.0.0-rc1`的私密离线目录。源码使用git archive；前端使用同提交构建戳和实际文件树摘要。三个镜像须经Docker inspect确认提交及协议，导出实际镜像tar。独立七插件从归档源码打包，官方Skill与注册表同时固定摘要，旧七合一包不作为可安装制品重新发布。

制品包含源码、镜像、前端、OpenAPI、七插件、官方Skill、注册表、Release Manifest、源代码及三个镜像的CycloneDX SBOM、Rollback Manifest。SBOM固定使用官方Syft1.52.0，下载包校验SHA256。SBOM是组成清单，不是漏洞清零证明；不透明编译依赖还需结合源锁文件审查。

目标目录已存在、源码不干净、源码或镜像混版、源材料变更、目录穿越、符号链接、额外文件、摘要不符、无效SBOM均拒绝。失败保留现场，不覆盖已有包。正式验包必须提供从已信任回执取得的manifest SHA256，不能只信任包内自行声明的清单。

## 回退

回退清单固定上一套三镜像ID，列明完整控制库、账号卷、发布配置、宿主执行状态、匹配密钥、部署配置和镜像清单。旧v6/v8镜像不能直接连接v9控制库；恢复旧版本必须将升级前成套备份恢复到空目标。9B提供工具与材料身份，实际迁移/恢复演练在9C执行，未演练不称为已验证回退。

候选离线包及镜像先保留服务器私密目录，GitHub只提交无凭据源码、测试、脱敏清单与验收证据。不把运行卷、账号配置或匹配密钥打进候选包。Tag与历史Release不覆盖。分支保护、实际镜像/包验证、CI和人工审阅分别记录。
