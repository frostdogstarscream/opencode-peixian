# Agent 工作台：插件与 Skill 开发手册

本文对应通用平台 V1，沿用 OpenCode `1.18.30` 与三角色控制台。开发者负责打包工具，超级管理员负责发布、平台连接和授权，普通用户负责自己的参数及启停。

本文描述已实现的“打包插件 + 表单 + 固定服务连接”方式。平台当前提供个人 Skill 与模板复制；没有部门审核发布流程，也没有无代码 HTTP 工具设计器。

## 1. 先理解四个对象

| 对象 | 作用 | 谁维护 | 是否传给插件 |
|---|---|---|---|
| 插件发布包 | 工具代码、版本、个人配置表单、所需连接别名 | 超级管理员发布经过审核的开发成果 | 代码在账号环境加载 |
| 个人插件配置 | 查询关键词、数量、输出偏好等个人参数 | 获授权的普通用户 | 作为 `options` 参数 |
| 平台服务连接 | 固定服务地址、鉴权、允许的方法与路径、请求限制 | 超级管理员 | 只提供调用能力，不提供公共服务密钥 |
| Skill | 何时调用哪个工具、如何理解结果、如何处理空结果与失败 | 用户管理自己的内容；超级管理员维护模板 | 作为助手可选择的指令 |

Skill 不负责保存服务密码，不替代服务端业务权限。插件能够在该账号环境执行代码，因此只接受超级管理员审核后发布的包。平台角色不会自动获得查看其他用户会话、文件正文的权限。

服务连接使用平台公共凭据时，底层业务服务看到的是这套服务身份。若将来需要案件、组织或更细的数据权限，应由业务接口根据可信业务身份校验；不能仅依靠 Skill 中一句“只查看本人数据”。

## 2. 随附的最小样例

```text
examples/
├── records-plugin/
│   ├── manifest.json       # 插件声明和个人配置表单
│   ├── entry.mjs           # 工具与连接测试入口
│   └── SKILL.md            # 配套指令示例，独立于插件安装
├── records-api.py          # 仅返回合成记录的 HTTP 测试服务
├── package-plugin.py       # 生成样例 ZIP，不下载或执行依赖
└── platform-python.py     # 通过控制台入口访问的 httpx 示例
```

样例插件 ID 是 `sample-records`，工具名是 `platform_sample_records`，连接别名是 `records`。它从个人配置中读取 `query` 和 `limit`，使用固定连接请求 `GET /records`，将真实返回的记录交给助手整理。

`records-api.py` 只有 `/health` 和 `/records` 两个读取接口，需要 Bearer 鉴权。其密钥通过 `SAMPLE_KEY_FILE` 指向的文件读取；监听端口由 `PORT` 指定，默认 `8090`。它是独立合成测试服务，不是生产业务数据库，不应放入真实资料。实际部署测试时由部署脚本将它接到指定测试网络，勿将示例服务当成平台公共入口。

## 3. 编写 manifest.json

最小声明可以参考：

```json
{
  "id": "sample-records",
  "version": "1.0.0",
  "name": "示例资料查询",
  "description": "查询已绑定服务中的合成资料。",
  "opencode_version": "1.18.30",
  "entry": "entry.mjs",
  "tools": ["platform_sample_records"],
  "connections": {
    "records": { "description": "只读资料查询服务" }
  },
  "display": {
    "input_fields": [],
    "output_fields": ["version", "source"]
  },
  "config_schema": {
    "type": "object",
    "properties": {
      "query": { "type": "string", "title": "查询关键词", "maxLength": 100, "default": "" },
      "limit": { "type": "integer", "title": "最多返回条数", "minimum": 1, "maximum": 20, "default": 5 }
    },
    "required": ["limit"],
    "additionalProperties": false
  }
}
```

关键约束如下：

- `id` 以小写字母开头，只使用小写字母、数字和横线，最长 64 字符。同一个能力升级时保持 ID 不变。
- `version` 使用三段数字，例如 `1.0.0`。已经发布的 ID 与版本组合不可覆盖；修改代码、表单或连接声明应发布新版本。
- `entry` 指向包内已打包 `.mjs` 入口，建议统一命名为 `entry.mjs`。兼容版本为 `1.18.30`。
- `tools` 列出实际导出的工具名称。使用与其他插件不同的前缀；禁止通过声明覆盖 Shell、PTY 或任意外网工具权限。
- `connections` 是别名对象，最多 20 个。别名以小写字母开头，使用小写字母、数字、下划线和横线，最长 40 字符。声明只含用途说明，不含服务地址和密码。
- 当前声明的连接均视为必需。任意连接未绑定或已停用，插件显示“平台连接待配置”，不会在新运行配置中加载。

### 3.1 个人配置表单

`config_schema` 采用受限 JSON Schema，后端和前端同时校验。

| 字段类型 | 用法与限制 |
|---|---|
| `string` | 文本；可设长度、枚举；用 `title` 写用户看得懂的名称 |
| `integer` / `number` | 数值；用 `minimum`、`maximum` 设置有效范围 |
| `boolean` | 开关 |
| `object` | 必须显式列出 `properties`，并设置 `additionalProperties: false`；每层最多 64 个字段 |
| `array` | 元素仅限非凭据的文字、数字或布尔值；不支持任意对象数组 |

嵌套深度最多 5 层，枚举最多 100 项，不支持 `$ref`、递归结构或自由 JSON 对象。服务端使用 schema 的 `required` 校验必填项。`default` 用于表单初始化，不应假定服务器会替调用者补齐必填字段；工具代码也应合理处理可选值。

如果确实需要用户自己的私密参数，可使用 `writeOnly: true` 或 `format: "password"`。平台只向用户返回“已配置”状态；保存时留空或省略可以保留原值。这类个人参数会下发给该用户的插件代码。**平台公共服务鉴权应配置在“服务连接”中，不放在个人表单里。**

### 3.2 对话中的业务详情

`display.input_fields` 和 `display.output_fields` 控制工具进度展开后允许显示的字段。当前只展示经过过滤的标量字段，如名称、条数、来源和短摘要；对象、数组、长文本、地址、凭据和内部错误不应放进业务详情。

样例的 `items` 是给助手读取的结构化结果。即使将 `items` 写入 `output_fields`，当前详情过滤器也不会将数组原样展示。建议另返回 `count` 这样的标量，并将其列入 `output_fields`。此过滤控制界面展示；完整工具结果仍可能进入该账号的模型上下文，开发者应主动缩减与本次问题无关的数据。

## 4. 编写工具入口与使用平台客户端

入口默认导出签名是：

```javascript
export default async function plugin(context, options, platform) {
  return {
    tool: {
      platform_sample_records: {
        description: "查询示例资料，使用用户配置的关键词与最多条数。",
        args: {},
        async execute() {
          const result = await platform.connections.request("records", {
            method: "GET",
            path: "/records",
            query: { q: options.query || "", limit: options.limit || 5 }
          });
          if (result.status !== 200 || !Array.isArray(result.data?.items)) {
            throw new Error("资料服务未返回可用结果，请稍后重试。");
          }
          return JSON.stringify({
            items: result.data.items,
            count: result.data.items.length,
            version: "1.0.0",
            source: "示例资料服务"
          });
        }
      }
    }
  };
}

export async function test(options, platform) {
  const result = await platform.connections.request("records", {
    method: "GET", path: "/health"
  });
  return { ok: result.status === 200 && result.data?.ok === true };
}
```

样例使用空 `args`，工具参数来自个人表单，便于在无需额外运行时依赖的情况下完成最小闭环。扩展模型填写的工具参数时，需要遵循本仓库固定版本的工具 schema；依赖在开发机预打包，不能让服务器运行时安装 npm 包。

平台注入 `platform`，插件不需要导入内部客户端文件，也不需要读取调用令牌。请求形式为：

```javascript
const result = await platform.connections.request("连接别名", {
  method: "POST",
  path: "/approved-query",
  query: { page: 1 },
  json: { keyword: "合成示例" }
});
// result: { status: 200, data: 上游 JSON 数据 }
```

请求约束：

- `method` 支持 `GET`、`POST`、`PUT`、`PATCH`、`DELETE`，仍须属于超级管理员为该连接允许的方法；省略时默认为 GET。
- `path` 必须在允许范围，不能是完整 URL、`//host`、含百分号转义、目录跳转、反斜线、查询字符串或片段的路径。查询参数放在 `query`。
- `query` 是最多 100 个键的标量对象；不支持嵌套对象、数组和 `null` 值。需要结构化参数时使用获批准的 POST JSON 接口。
- GET 不接受 `json` 正文。整个请求最多 1 MiB。
- 不接受调用方自定义 HTTP 头、API Key、目标主机或重定向选项。
- 连接超时可配置为 1～60 秒；响应大小可配置为 1 KiB～10 MiB，默认 1 MiB。
- 上游须返回未压缩的 JSON；出口发送 `Accept-Encoding: identity`。重定向、非 JSON、超时、超限、服务错误及回显服务鉴权的响应会被拒绝。
- 出口不会把上游错误正文、响应头和公共密钥传给插件。SDK 将调用失败转换为统一业务错误；不要依赖原始上游错误堆栈判断业务状态。

一个账号的调用令牌不能用于另一个账号的出口；配置变更后调用令牌随版本更新。不要把平台客户端或令牌保存进 Skill、工作区文件、业务结果或日志。

## 5. 超级管理员配置服务连接和发布

### 5.1 配置固定服务连接

进入“管理中心 → 服务连接”，设置连接名称、服务根地址及以下内容：

| 配置项 | 样例值 | 说明 |
|---|---|---|
| 根地址 | 测试网络中合成资料服务的 HTTP 地址 | 必须能从控制服务的测试入口及账号出口到达；`localhost` 指当前容器，不是宿主机 |
| 鉴权 | Bearer | 只在私密表单填写实际测试密钥；查询接口不回显 |
| 允许的方法 | GET | 本例只查询，不需要授予写方法 |
| 允许的路径 | `/health`、`/records` | 精确路径；要允许子路径时才使用末尾 `/*` |
| 超时 | 15 秒 | 请求总超时，不仅是连接超时 |
| 响应大小 | 1024 KiB（1048576 字节） | 表单单位为 KiB，按实际 JSON 大小限制 |

根地址若包含 `/api`，插件请求 `/records` 会到达 `/api/records`。`/records/*` 匹配它的后代路径，不包含 `/records` 本身；两者都需要时分开添加。

支持 `none`、`bearer`、`api_key` 三类鉴权。API Key 请求头默认 `X-API-Key`，不能替换 Host 等传输控制头。更新时鉴权类型和头名不变，空密码保留旧值；修改类型或头名须重新填写凭据，切换 `none` 会清除旧凭据。

页面连接测试使用允许的明确 GET 路径。它验证控制服务到固定服务的连通性并使用与出口相同的限制，不返回业务正文。**用户侧的“测试连接”还要运行一次，以验证真实账号出口和插件代码路径。** 两者通过后，才进入实际工具调用验收。

### 5.2 打包与上传

在 `deploy/peixian` 目录运行：

```powershell
python examples/package-plugin.py --version 1.0.0 --output dist/plugins/sample-records-1.0.0.zip
```

输出文件已存在时脚本拒绝覆盖。此脚本专门打包随附 `records-plugin` 的 `manifest.json` 和 `entry.mjs`；新项目可以以这两个文件为模板制作自己的 ZIP。不要把整个开发目录、依赖缓存、凭据、测试数据和 Git 历史打包。

ZIP 根目录必须直接包含 manifest 与入口。上传上限 20 MiB，最多 1000 项，展开合计最多 100 MiB；绝对路径、目录跳转、符号链接、重复路径等会被拒绝。所有 JS 依赖须在开发阶段预打包，不在服务器执行依赖安装或原生扩展构建。

超级管理员在“插件发布”上传 ZIP，然后进入该插件**具体版本**的连接绑定，将 `records` 绑定到刚创建的服务连接。新版本不会自动继承旧版本的连接绑定；发布后需要逐版本核对。声明不可覆盖，版本绑定的修改会生成新的账号配置应用任务。

再为目标普通用户授予该插件。普通管理员没有发布、绑定或授权平台插件的权限。

### 5.3 用户安装与 Skill 配合

普通用户在“我的插件”选择“示例资料查询”，填写关键词和最多条数，保存并等待生效，再执行“测试连接”。用户只能选择已授权、启用的发布版本，不能输入服务地址或变更公共鉴权。

将配套 `SKILL.md` 的名称、用途和正文填入“我的技能”，或由超级管理员将它建立为技能模板后让用户复制。示例打包脚本不会自动安装 Skill；Skill 与插件有各自的生命周期。

开启新会话，选择获授权的模型和该 Skill，明确要求查询示例资料。成功标准是实际出现 `platform_sample_records` 工具调用，结果与合成服务返回一致；不能只以助手说“已经连接成功”判断验收通过。

## 6. 配置应用、升级与回退

平台保存配置后，只为受影响且正在使用该插件的账号排队应用。界面区分已保存、待生效、已生效和失败；暂停的环境保留待应用配置，恢复时再加载。运行中的任务会先等待，不通过强行中断让配置立即生效。

升级示例：

```powershell
python examples/package-plugin.py --version 1.1.0 --output dist/plugins/sample-records-1.1.0.zip
```

发布 `1.1.0`，核对其连接声明，单独保存新版本连接绑定，然后让测试用户选择该版本、保存并等待生效。确认查询结果中的版本标识变化及工具结果正确，再授权或指导更多用户升级。

用户“回退”恢复上一份个人插件安装配置，包括版本、启停状态和个人参数；目标版本仍须启用且获授权。它不会回退平台服务连接的公共配置，也不是无限版本历史。平台配置应用失败时的运行环境回滚和用户主动回退属于不同操作。

停用连接或清除必需别名绑定后，受影响插件变为“平台连接待配置”，新运行配置不会加载该插件。正在等待应用的旧环境可能尚在使用上一个版本；如需立即停止访问，可由超级管理员暂停相关账号环境，再核验上游服务凭据。被插件版本引用的连接不能直接删除，可先停用或解除绑定。

## 7. 测试清单与常见问题

开发与合成验收至少覆盖：

1. 正常结果、空列表、无效输入、返回结构改变、服务不可用。
2. 超级管理员发布和绑定；普通管理员与普通用户直接调用管理 API 被拒绝。
3. 用户只能安装被授权版本；个人参数互不影响；跨账号调用令牌不能使用。
4. 缺少连接、连接停用、新版本漏绑时明确显示待配置，不给出虚假的测试成功。
5. 未允许方法和路径、URL 替换、编码路径跳转、重定向、超大请求和响应都被拒绝。
6. 公共密钥不进入发布包、Agent 配置、工具结果和日志；上游错误或回显密钥时不向用户返回原文。
7. 发布新版本、单账号更新、实际工具调用、恢复上一版，以及其他账号持续可用。

| 现象 | 排查方向 |
|---|---|
| 目录看不到插件 | 核对用户授权，以及至少有一个启用的发布版本 |
| “平台连接待配置” | 核对**当前安装版本**的所有别名绑定及连接启用状态 |
| 管理端测试成功，用户测试失败 | 核对账号出口能否到达服务、该账号配置是否已应用、插件 test 逻辑 |
| 保存后仍提示待生效 | 查看用户环境状态及配置应用任务；不要重复上传相同版本 |
| 测试成功，聊天没有调用工具 | 核对工具名称、Skill 正文、模型工具调用能力及问题是否明确；连接测试不等于模型验收 |
| 工具返回了记录，业务详情没显示数组 | 当前详情只展示声明的安全标量；给详情增加 count/source，完整资料由助手按需整理 |
| 上传版本冲突 | 已发布版本不可覆盖，使用新的版本号 |
| HTTPS 服务证书失败 | 安装合适的受信任 CA；不要以关闭 TLS 验证作为部署方案 |

## 8. Python 访问示例

`examples/platform-python.py` 使用 `httpx`，访问统一平台入口。安装依赖可使用交付包中的离线依赖，开发机也可按项目依赖安装 `httpx`。Python 客户端不连接各账号容器，也不传 Docker ID、工作区路径或上游模型地址。

服务器访问使用 HTTPS，始终验证证书和主机名。内部 CA 可通过 `PLATFORM_CA_FILE` 或 `--ca-file` 指定 PEM 文件。回环地址的 HTTP 仅用于本机测试；没有 `--insecure` 参数。

PowerShell 7 配置示例：

```powershell
$env:PLATFORM_URL = 'https://agent.example.internal'
$env:PLATFORM_CA_FILE = 'C:\Certificates\internal-ca.pem'
$env:PLATFORM_TOKEN = Read-Host '个人设置中生成的访问令牌' -MaskInput
python examples/platform-python.py health
python examples/platform-python.py me
python examples/platform-python.py models
```

令牌读取环境变量，不放在命令参数里。也可以不设置令牌，通过隐藏密码输入临时登录：

```powershell
python examples/platform-python.py --login --username client-a models
```

临时 Cookie 登录使用 Origin 与 CSRF 校验，命令结束时注销本次登录；个人令牌方式不会注销或撤销令牌。初始密码账号要先在网页修改密码。普通业务命令使用普通用户身份，管理角色没有默认访问私人对话的权限。

上传、查看解析状态并建立空会话：

```powershell
python examples/platform-python.py upload .\synthetic-notes.txt
python examples/platform-python.py files
python examples/platform-python.py create-session --title 'Python 合成测试'
python examples/platform-python.py skills
```

记下返回的文件 ID、会话 ID、技能 ID 和平台模型 ID。等待文件 `status` 为 `ready` 且未截断后，才作为模型引用；`partial`、`truncated` 或解析失败需要先处理文件。创建空会话和上传本身不会调用模型。

只有显式执行 `send` 子命令才会提交模型问题：

```powershell
python examples/platform-python.py send --session SESSION_ID --model PLATFORM_MODEL_ID --text-file .\question.txt --file-id FILE_ID --skill-id SKILL_ID
python examples/platform-python.py events --session SESSION_ID --seconds 60
python examples/platform-python.py messages --session SESSION_ID
python examples/platform-python.py stop --session SESSION_ID
```

上例占位 ID 应替换为本账号接口返回的真实资源 ID。`--model`、`--file-id` 和 `--skill-id` 都可省略；每次最多五个文件和五个技能。`--text-file` 从 UTF-8 文件读取问题，避免问题正文进入命令历史。提交返回 `202/accepted` 表示接收成功，不表示回答完成；`run_id` 不是独立结果查询地址。

事件流发送的是 `change` 通知，不是直接逐 token 文本。示例在通知及重连后查询消息历史，内容未变化时不重复打印；重连不会重新发送问题。`stop` 只取消给定会话的生成，不删除会话。查看消息和 events 历史会向终端输出本账号业务内容，按实际数据管理要求决定是否保存终端记录。

使用完令牌后可清理当前 PowerShell 进程环境；需要彻底撤销时到“个人设置 → Python 访问令牌”操作：

```powershell
Remove-Item Env:PLATFORM_TOKEN
```

## 9. 接口参考与交付边界

主要管理接口如下，均使用已有的 `/api/console/v1` 前缀：

| 接口 | 用途 |
|---|---|
| `GET/POST /admin/connections` | 查询／创建固定服务连接 |
| `PATCH/DELETE /admin/connections/{id}` | 修改／删除未绑定连接 |
| `POST /admin/connections/{id}/test` | 验证方法、路径及 JSON 服务响应，返回安全状态 |
| `GET/PUT /admin/plugins/{id}/{version}/connections` | 查询／完整保存指定版本的别名绑定 |
| `GET /plugins` | 查询本人获授权插件及配置状态 |
| `PUT /plugins/{id}` | 保存本人安装版本、配置和启停状态 |
| `POST /plugins/{id}/test` | 从本人环境执行发布包的 test 函数 |
| `POST /plugins/{id}/rollback` | 恢复上一份个人安装配置 |

完整请求与响应以 `services/peixian-control/docs/openapi.json` 为准。发布包、平台连接和私有参数应分开交付；离线包不包含任何现有账号数据、服务凭据或业务资料。

本手册中的合成服务与样例证明扩展机制可用，不能替代真实业务接口的权限检查、数据正确性测试，以及实际内网模型的工具调用验收。
