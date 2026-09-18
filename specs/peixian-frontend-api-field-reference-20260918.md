# 前端接口字段索引（代码生成）

完整类型以同目录 OpenAPI JSON 为准。只展示业务公开接口，内部 Worker 路由不向前端开放。

## GET /api/console/v1/platform

获取公开产品信息

权限：`anonymous`。 仅产品名称、简称与介绍，不包含部署标识、内部地址或任何凭据。

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/Platform"
          }
        }
      }
    }
  }
}
```

## POST /api/console/v1/auth/login

登录并获取 Cookie 与 CSRF

权限：`anonymous`。 校验允许的 Origin，成功设置 HttpOnly 的 px_session Cookie。初始密码用户只能查询自己、改密或退出。

请求与成功响应：
```json
{
  "request": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/LoginBody"
      }
    }
  },
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/Identity"
          }
        }
      },
      "headers": {
        "Set-Cookie": {
          "schema": {
            "type": "string"
          },
          "description": "px_session 的 HttpOnly/SameSite=Strict Cookie，最长 8 小时；部署启用 TLS 时配置 Secure。"
        }
      }
    }
  }
}
```

## GET /api/console/v1/me

获取当前身份及环境状态

权限：`authenticated`。 账号由有效认证绑定；Bearer 身份的 csrf_token 为 null。

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/Identity"
          }
        }
      }
    }
  }
}
```

## POST /api/console/v1/auth/logout

撤销当前认证

权限：`authenticated`。 删除当前 Cookie 或 Bearer 认证记录；已建立的本身份事件连接也会关闭。

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/Ok"
          }
        }
      }
    }
  }
}
```

## POST /api/console/v1/me/password

修改自己的密码

权限：`authenticated`。 撤销其他登录与令牌，保留本次认证。

请求与成功响应：
```json
{
  "request": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/PasswordBody"
      }
    }
  },
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/Ok"
          }
        }
      }
    }
  }
}
```

## GET /api/console/v1/tokens

列出自己的访问令牌

权限：`authenticated`。 只返回元数据，不返回原始令牌。

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "properties": {
              "items": {
                "type": "array",
                "items": {
                  "$ref": "#/components/schemas/Token"
                }
              }
            },
            "additionalProperties": true,
            "required": [
              "items"
            ]
          }
        }
      }
    }
  }
}
```

## POST /api/console/v1/tokens

创建访问令牌

权限：`authenticated`。 令牌有效期 30 天，原始值仅本次返回；权限与账号身份一致。

请求与成功响应：
```json
{
  "request": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/TokenBody"
      }
    }
  },
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/TokenCreated"
          }
        }
      }
    }
  }
}
```

## DELETE /api/console/v1/tokens/{tid}

撤销自己的访问令牌

权限：`authenticated`。 撤销后新请求被拒绝，使用该令牌的事件流关闭。

参数：
```json
[
  {
    "name": "tid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  }
]
```

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/Ok"
          }
        }
      }
    }
  }
}
```

## GET /api/console/v1/models

列出本账号获授权模型

权限：`user`。 不公开上游地址或模型密钥。

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "properties": {
              "items": {
                "type": "array",
                "items": {
                  "$ref": "#/components/schemas/Model"
                }
              }
            },
            "additionalProperties": true,
            "required": [
              "items"
            ]
          }
        }
      }
    }
  }
}
```

## GET /api/console/v1/sessions

列出自己的会话

权限：`user`。 仅固定工作区内的会话；同时返回 idle/busy 等状态。

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "properties": {
              "items": {
                "type": "array",
                "items": {
                  "$ref": "#/components/schemas/Session"
                }
              }
            },
            "additionalProperties": true,
            "required": [
              "items"
            ]
          }
        }
      }
    }
  }
}
```

## POST /api/console/v1/sessions

创建空会话

权限：`user`。 创建空会话本身不发起模型生成。

请求与成功响应：
```json
{
  "request": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/SessionBody"
      }
    }
  },
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/Session"
          }
        }
      }
    }
  }
}
```

## PATCH /api/console/v1/sessions/{sid}

重命名自己的会话

权限：`user`。

参数：
```json
[
  {
    "name": "sid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  }
]
```

请求与成功响应：
```json
{
  "request": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/SessionBody"
      }
    }
  },
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/Session"
          }
        }
      }
    }
  }
}
```

## DELETE /api/console/v1/sessions/{sid}

删除自己的会话

权限：`user`。

参数：
```json
[
  {
    "name": "sid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  }
]
```

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/Ok"
          }
        }
      }
    }
  }
}
```

## GET /api/console/v1/sessions/{sid}/messages

读取会话的已保存消息

权限：`user`。 工具展示经过过滤，不返回原始内部配置或工具秘密。

参数：
```json
[
  {
    "name": "sid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  }
]
```

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "properties": {
              "items": {
                "type": "array",
                "items": {
                  "$ref": "#/components/schemas/Message"
                }
              }
            },
            "additionalProperties": true,
            "required": [
              "items"
            ]
          }
        }
      }
    }
  }
}
```

## POST /api/console/v1/sessions/{sid}/messages

提交消息并受理持久执行

权限：`user`。 HTTP 202返回持久run_id和固定message_id；plugin_ids 是偏好；同 client_request_id 同内容返回首次受理，不自动重发未知执行。

参数：
```json
[
  {
    "name": "sid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  }
]
```

请求与成功响应：
```json
{
  "request": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/MessageBody"
      }
    }
  },
  "responses": {
    "202": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/RunAccepted"
          }
        }
      }
    }
  }
}
```

## GET /api/console/v1/sessions/{sid}/evidence

读取本人会话的合成资料依据

权限：`user`。 仅投影当前请求已完成且版本匹配的受信插件结果，重新校验插件授权；不解析模型自由文本，不返回内部配置。

参数：
```json
[
  {
    "name": "sid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  }
]
```

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ScenarioEvidence"
          }
        }
      }
    }
  }
}
```

## POST /api/console/v1/sessions/{sid}/abort

终止自己的会话生成

权限：`user`。

参数：
```json
[
  {
    "name": "sid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  }
]
```

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/Ok"
          }
        }
      }
    }
  }
}
```

## GET /api/console/v1/events

订阅本账号变更事件

权限：`user`。 SSE 保留 event: change、type=connected/updated，可附 resources 资源类别数组与 session_id。单 Control 进程内同账号共享一个上游，每个订阅独立认证；慢消费者或上游不连续时发送 type=resync_required，客户端合并刷新持久历史和资源列表，不拼接跨断线正文。只发送失效通知，正文通过 messages 补齐；旧 updated 无类别时刷新消息/会话。认证与名额在响应头之前检查，超额返回429/503及Retry-After。默认15秒心跳、2秒身份复核，撤销后5秒内关闭。客户端仅重连读取，不自动重放生成请求。

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "持续的 SSE 变更通知流",
      "content": {
        "text/event-stream": {
          "schema": {
            "type": "string"
          }
        }
      }
    }
  }
}
```

## GET /api/console/v1/capabilities

查询当前可用能力

权限：`user`。 当前账号资源；不属于本人返回404。

参数：
```json
[
  {
    "name": "page",
    "in": "query",
    "required": false,
    "schema": {
      "type": "integer",
      "default": 1,
      "title": "Page"
    }
  },
  {
    "name": "page_size",
    "in": "query",
    "required": false,
    "schema": {
      "type": "integer",
      "default": 100,
      "title": "Page Size"
    }
  }
]
```

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/CapabilityPage"
          }
        }
      }
    }
  }
}
```

## POST /api/console/v1/skill-drafts/from-requirement

受理模型辅助草稿

权限：`user`。 新客户端提供请求标识；生成不调用工具，不发布技能。

请求与成功响应：
```json
{
  "request": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/DraftGenerateBody"
      }
    }
  },
  "responses": {
    "202": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/SkillDraft"
          }
        }
      }
    }
  }
}
```

## POST /api/console/v1/skill-drafts/from-session

受理模型辅助草稿

权限：`user`。 新客户端提供请求标识；生成不调用工具，不发布技能。

请求与成功响应：
```json
{
  "request": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/DraftGenerateBody"
      }
    }
  },
  "responses": {
    "202": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/SkillDraft"
          }
        }
      }
    }
  }
}
```

## GET /api/console/v1/skill-drafts/{did}

查询本人草稿

权限：`user`。 当前账号资源；不属于本人返回404。

参数：
```json
[
  {
    "name": "did",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  }
]
```

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/SkillDraft"
          }
        }
      }
    }
  }
}
```

## PATCH /api/console/v1/skill-drafts/{did}

编辑本人草稿

权限：`user`。 当前账号资源；不属于本人返回404。

参数：
```json
[
  {
    "name": "did",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  },
  {
    "name": "Idempotency-Key",
    "in": "header",
    "required": true,
    "schema": {
      "type": "string",
      "pattern": "^[A-Za-z0-9_-]{8,100}$"
    },
    "description": "同账号、同接口、同键与同内容返回首次提交结果；内容冲突返回409。已闭合记录保留至少7天。消息生成与外部工具执行不属于自动重试保证。"
  }
]
```

请求与成功响应：
```json
{
  "request": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/SkillDraftBody"
      }
    }
  },
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/SkillDraft"
          }
        }
      }
    }
  }
}
```

## POST /api/console/v1/skill-drafts/{did}/test

检查或试运行草稿

权限：`user`。 validation不调用模型；model需要客户端请求标识并创建独立会话。

参数：
```json
[
  {
    "name": "did",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  }
]
```

请求与成功响应：
```json
{
  "request": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/DraftTestBody"
      }
    }
  },
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/DraftTestResult"
          }
        }
      }
    }
  }
}
```

## POST /api/console/v1/skill-drafts/{did}/save

明确保存为个人技能

权限：`user`。 默认停用，等待用户启用及配置生效；保存不能获得公共发布权限。

参数：
```json
[
  {
    "name": "did",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  },
  {
    "name": "Idempotency-Key",
    "in": "header",
    "required": true,
    "schema": {
      "type": "string",
      "pattern": "^[A-Za-z0-9_-]{8,100}$"
    },
    "description": "同账号、同接口、同键与同内容返回首次提交结果；内容冲突返回409。已闭合记录保留至少7天。消息生成与外部工具执行不属于自动重试保证。"
  }
]
```

请求与成功响应：
```json
{
  "request": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/EmptyBody"
      }
    }
  },
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/DraftSaveResult"
          }
        }
      }
    }
  }
}
```

## GET /api/console/v1/sessions/{sid}/runs

查询会话执行记录

权限：`user`。 当前账号资源；不属于本人返回404。

参数：
```json
[
  {
    "name": "sid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  },
  {
    "name": "page",
    "in": "query",
    "required": false,
    "schema": {
      "type": "integer",
      "default": 1,
      "title": "Page"
    }
  },
  {
    "name": "page_size",
    "in": "query",
    "required": false,
    "schema": {
      "type": "integer",
      "default": 20,
      "title": "Page Size"
    }
  }
]
```

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/RunPage"
          }
        }
      }
    }
  }
}
```

## GET /api/console/v1/sessions/{sid}/runs/{rid}

查询执行状态

权限：`user`。 当前账号资源；不属于本人返回404。

参数：
```json
[
  {
    "name": "sid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  },
  {
    "name": "rid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  }
]
```

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/Run"
          }
        }
      }
    }
  }
}
```

## GET /api/console/v1/sessions/{sid}/runs/{rid}/events

增量查询持久步骤

权限：`user`。 当前账号资源；不属于本人返回404。

参数：
```json
[
  {
    "name": "sid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  },
  {
    "name": "rid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  },
  {
    "name": "page",
    "in": "query",
    "required": false,
    "schema": {
      "type": "integer",
      "default": 1,
      "title": "Page"
    }
  },
  {
    "name": "page_size",
    "in": "query",
    "required": false,
    "schema": {
      "type": "integer",
      "default": 100,
      "title": "Page Size"
    }
  },
  {
    "name": "after",
    "in": "query",
    "required": false,
    "schema": {
      "type": "integer",
      "default": 0,
      "title": "After"
    }
  }
]
```

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/RunEventPage"
          }
        }
      }
    }
  }
}
```

## GET /api/console/v1/sessions/{sid}/runs/{rid}/evidence

查询固定执行证据

权限：`user`。 当前账号资源；不属于本人返回404。

参数：
```json
[
  {
    "name": "sid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  },
  {
    "name": "rid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  }
]
```

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/RunEvidence"
          }
        }
      }
    }
  }
}
```

## POST /api/console/v1/sessions/{sid}/runs/{rid}/abort

请求停止执行

权限：`user`。 当前账号资源；不属于本人返回404。

参数：
```json
[
  {
    "name": "sid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  },
  {
    "name": "rid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  }
]
```

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "202": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/Run"
          }
        }
      }
    }
  }
}
```

## POST /api/console/v1/sessions/{sid}/runs/{rid}/rerun

明确创建关联重跑

权限：`user`。 当前账号资源；不属于本人返回404。

参数：
```json
[
  {
    "name": "sid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  },
  {
    "name": "rid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  }
]
```

请求与成功响应：
```json
{
  "request": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/RerunBody"
      }
    }
  },
  "responses": {
    "202": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/RunAccepted"
          }
        }
      }
    }
  }
}
```

## GET /api/console/v1/sessions/{sid}/runs/{rid}/report

导出 Markdown 执行报告

权限：`user`。 当前账号资源；不属于本人返回404。

参数：
```json
[
  {
    "name": "sid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  },
  {
    "name": "rid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  }
]
```

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "Markdown 文件",
      "content": {
        "text/markdown; charset=utf-8": {
          "schema": {
            "type": "string"
          }
        }
      }
    }
  }
}
```

## GET /api/console/v1/admin/invocations

查询脱敏调用元数据

权限：`super_admin|admin`。 当前账号资源；不属于本人返回404。

参数：
```json
[
  {
    "name": "page",
    "in": "query",
    "required": false,
    "schema": {
      "type": "integer",
      "default": 1,
      "title": "Page"
    }
  },
  {
    "name": "page_size",
    "in": "query",
    "required": false,
    "schema": {
      "type": "integer",
      "default": 20,
      "title": "Page Size"
    }
  },
  {
    "name": "query",
    "in": "query",
    "required": false,
    "schema": {
      "type": "string"
    }
  },
  {
    "name": "start",
    "in": "query",
    "required": false,
    "schema": {
      "type": "string"
    }
  },
  {
    "name": "end",
    "in": "query",
    "required": false,
    "schema": {
      "type": "string"
    }
  },
  {
    "name": "uid",
    "in": "query",
    "required": false,
    "schema": {
      "type": "string"
    }
  },
  {
    "name": "department_id",
    "in": "query",
    "required": false,
    "schema": {
      "type": "string"
    }
  },
  {
    "name": "model_id",
    "in": "query",
    "required": false,
    "schema": {
      "type": "string"
    }
  },
  {
    "name": "skill_id",
    "in": "query",
    "required": false,
    "schema": {
      "type": "string"
    }
  },
  {
    "name": "status",
    "in": "query",
    "required": false,
    "schema": {
      "type": "string"
    }
  }
]
```

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/InvocationPage"
          }
        }
      }
    }
  }
}
```

## GET /api/console/v1/admin/invocations/export

导出 UTF-8 BOM CSV

权限：`super_admin|admin`。 当前账号资源；不属于本人返回404。

参数：
```json
[
  {
    "name": "query",
    "in": "query",
    "required": false,
    "schema": {
      "type": "string"
    }
  },
  {
    "name": "start",
    "in": "query",
    "required": false,
    "schema": {
      "type": "string"
    }
  },
  {
    "name": "end",
    "in": "query",
    "required": false,
    "schema": {
      "type": "string"
    }
  },
  {
    "name": "uid",
    "in": "query",
    "required": false,
    "schema": {
      "type": "string"
    }
  },
  {
    "name": "department_id",
    "in": "query",
    "required": false,
    "schema": {
      "type": "string"
    }
  },
  {
    "name": "model_id",
    "in": "query",
    "required": false,
    "schema": {
      "type": "string"
    }
  },
  {
    "name": "skill_id",
    "in": "query",
    "required": false,
    "schema": {
      "type": "string"
    }
  },
  {
    "name": "status",
    "in": "query",
    "required": false,
    "schema": {
      "type": "string"
    }
  }
]
```

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "UTF-8 BOM CSV",
      "content": {
        "text/csv; charset=utf-8": {
          "schema": {
            "type": "string"
          }
        }
      }
    }
  }
}
```

## GET /api/console/v1/admin/invocations/{iid}

查询脱敏调用详情

权限：`super_admin|admin`。 当前账号资源；不属于本人返回404。

参数：
```json
[
  {
    "name": "iid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  }
]
```

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/Invocation"
          }
        }
      }
    }
  }
}
```

## GET /api/console/v1/skills

列出自己的技能

权限：`user`。

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "properties": {
              "items": {
                "type": "array",
                "items": {
                  "$ref": "#/components/schemas/Skill"
                }
              }
            },
            "additionalProperties": true,
            "required": [
              "items"
            ]
          }
        }
      }
    }
  }
}
```

## POST /api/console/v1/skills

创建自己的技能

权限：`user`。 保存后返回配置应用任务；任务完成前不能假定技能已加载。

参数：
```json
[
  {
    "name": "Idempotency-Key",
    "in": "header",
    "required": true,
    "schema": {
      "type": "string",
      "pattern": "^[A-Za-z0-9_-]{8,100}$"
    },
    "description": "同账号、同接口、同键与同内容返回首次提交结果；内容冲突返回409。已闭合记录保留至少7天。消息生成与外部工具执行不属于自动重试保证。"
  }
]
```

请求与成功响应：
```json
{
  "request": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/SkillCreateBody"
      }
    }
  },
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/Skill"
          }
        }
      }
    }
  }
}
```

## PATCH /api/console/v1/skills/{sid}

修改自己的技能

权限：`user`。 保存历史并排队应用。

参数：
```json
[
  {
    "name": "sid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  },
  {
    "name": "Idempotency-Key",
    "in": "header",
    "required": true,
    "schema": {
      "type": "string",
      "pattern": "^[A-Za-z0-9_-]{8,100}$"
    },
    "description": "同账号、同接口、同键与同内容返回首次提交结果；内容冲突返回409。已闭合记录保留至少7天。消息生成与外部工具执行不属于自动重试保证。"
  }
]
```

请求与成功响应：
```json
{
  "request": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/SkillUpdateBody"
      }
    }
  },
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/Queued"
          }
        }
      }
    }
  }
}
```

## DELETE /api/console/v1/skills/{sid}

删除自己的技能

权限：`user`。 排队应用运行环境配置。

参数：
```json
[
  {
    "name": "sid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  },
  {
    "name": "Idempotency-Key",
    "in": "header",
    "required": true,
    "schema": {
      "type": "string",
      "pattern": "^[A-Za-z0-9_-]{8,100}$"
    },
    "description": "同账号、同接口、同键与同内容返回首次提交结果；内容冲突返回409。已闭合记录保留至少7天。消息生成与外部工具执行不属于自动重试保证。"
  }
]
```

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/Queued"
          }
        }
      }
    }
  }
}
```

## POST /api/console/v1/skills/{sid}/rollback

恢复自己的上一版技能

权限：`user`。

参数：
```json
[
  {
    "name": "sid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  },
  {
    "name": "Idempotency-Key",
    "in": "header",
    "required": true,
    "schema": {
      "type": "string",
      "pattern": "^[A-Za-z0-9_-]{8,100}$"
    },
    "description": "同账号、同接口、同键与同内容返回首次提交结果；内容冲突返回409。已闭合记录保留至少7天。消息生成与外部工具执行不属于自动重试保证。"
  }
]
```

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/Queued"
          }
        }
      }
    }
  }
}
```

## POST /api/console/v1/skills/{sid}/test

检查技能是否已经加载

权限：`user`。 只核对当前环境是否加载技能，不发起模型效果评测。

参数：
```json
[
  {
    "name": "sid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  }
]
```

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ConnectionTest"
          }
        }
      }
    }
  }
}
```

## GET /api/console/v1/templates

列出管理员提供的技能模板

权限：`user`。

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "properties": {
              "items": {
                "type": "array",
                "items": {
                  "$ref": "#/components/schemas/Template"
                }
              }
            },
            "additionalProperties": true,
            "required": [
              "items"
            ]
          }
        }
      }
    }
  }
}
```

## POST /api/console/v1/templates/{tid}/copy

复制模板为自己的技能

权限：`user`。 返回新技能 id 与配置应用任务。

参数：
```json
[
  {
    "name": "tid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  },
  {
    "name": "Idempotency-Key",
    "in": "header",
    "required": true,
    "schema": {
      "type": "string",
      "pattern": "^[A-Za-z0-9_-]{8,100}$"
    },
    "description": "同账号、同接口、同键与同内容返回首次提交结果；内容冲突返回409。已闭合记录保留至少7天。消息生成与外部工具执行不属于自动重试保证。"
  }
]
```

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/Queued"
          }
        }
      }
    }
  }
}
```

## GET /api/console/v1/plugins

列出已授权插件及自己的配置状态

权限：`user`。 仅管理员发布且授权的插件；私密字段仅返回配置状态，不回显值。

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "properties": {
              "items": {
                "type": "array",
                "items": {
                  "$ref": "#/components/schemas/Plugin"
                }
              }
            },
            "additionalProperties": true,
            "required": [
              "items"
            ]
          }
        }
      }
    }
  }
}
```

## PUT /api/console/v1/plugins/{pid}

安装或配置已授权插件

权限：`user`。 用户无法提交任意包或加载路径；参数校验依赖版本 config_schema。保存后排队应用。

参数：
```json
[
  {
    "name": "pid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  },
  {
    "name": "Idempotency-Key",
    "in": "header",
    "required": true,
    "schema": {
      "type": "string",
      "pattern": "^[A-Za-z0-9_-]{8,100}$"
    },
    "description": "同账号、同接口、同键与同内容返回首次提交结果；内容冲突返回409。已闭合记录保留至少7天。消息生成与外部工具执行不属于自动重试保证。"
  }
]
```

请求与成功响应：
```json
{
  "request": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/PluginInstallBody"
      }
    }
  },
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/Queued"
          }
        }
      }
    }
  }
}
```

## POST /api/console/v1/plugins/{pid}/rollback

恢复自己上一版插件配置

权限：`user`。 目标版本必须仍获授权且启用。

参数：
```json
[
  {
    "name": "pid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  },
  {
    "name": "Idempotency-Key",
    "in": "header",
    "required": true,
    "schema": {
      "type": "string",
      "pattern": "^[A-Za-z0-9_-]{8,100}$"
    },
    "description": "同账号、同接口、同键与同内容返回首次提交结果；内容冲突返回409。已闭合记录保留至少7天。消息生成与外部工具执行不属于自动重试保证。"
  }
]
```

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/Queued"
          }
        }
      }
    }
  }
}
```

## POST /api/console/v1/plugins/{pid}/test

执行插件提供的连接测试

权限：`user`。 配置尚未应用时 connection_tested=false。已应用时调用管理员包的 test 导出；supported=false 表示不提供连接测试，不代表连接成功。

参数：
```json
[
  {
    "name": "pid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  }
]
```

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ConnectionTest"
          }
        }
      }
    }
  }
}
```

## GET /api/console/v1/admin/users/summary

查询可管理用户汇总

权限：`super_admin|admin`。 管理员仅统计普通用户；超管统计普通用户和管理员。

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/UserSummary"
          }
        }
      }
    }
  }
}
```

## GET /api/console/v1/admin/departments/tree

查询部门树

权限：`super_admin|admin`。 三角色中的两个管理角色可读。

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/DepartmentTree"
          }
        }
      }
    }
  }
}
```

## POST /api/console/v1/admin/departments

创建部门

权限：`super_admin`。 仅超级管理员；幂等写入。

参数：
```json
[
  {
    "name": "Idempotency-Key",
    "in": "header",
    "required": true,
    "schema": {
      "type": "string",
      "pattern": "^[A-Za-z0-9_-]{8,100}$"
    },
    "description": "同账号、同接口、同键与同内容返回首次提交结果；内容冲突返回409。已闭合记录保留至少7天。消息生成与外部工具执行不属于自动重试保证。"
  }
]
```

请求与成功响应：
```json
{
  "request": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/DepartmentBody"
      }
    }
  },
  "responses": {
    "201": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/Department"
          }
        }
      }
    }
  }
}
```

## PATCH /api/console/v1/admin/departments/{did}

修改部门

权限：`super_admin`。 仅超级管理员；禁止环。

参数：
```json
[
  {
    "name": "did",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  },
  {
    "name": "Idempotency-Key",
    "in": "header",
    "required": true,
    "schema": {
      "type": "string",
      "pattern": "^[A-Za-z0-9_-]{8,100}$"
    },
    "description": "同账号、同接口、同键与同内容返回首次提交结果；内容冲突返回409。已闭合记录保留至少7天。消息生成与外部工具执行不属于自动重试保证。"
  }
]
```

请求与成功响应：
```json
{
  "request": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/DepartmentBody"
      }
    }
  },
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/Department"
          }
        }
      }
    }
  }
}
```

## DELETE /api/console/v1/admin/departments/{did}

删除空部门

权限：`super_admin`。 仅超级管理员；非空返回409。

参数：
```json
[
  {
    "name": "did",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  },
  {
    "name": "Idempotency-Key",
    "in": "header",
    "required": true,
    "schema": {
      "type": "string",
      "pattern": "^[A-Za-z0-9_-]{8,100}$"
    },
    "description": "同账号、同接口、同键与同内容返回首次提交结果；内容冲突返回409。已闭合记录保留至少7天。消息生成与外部工具执行不属于自动重试保证。"
  }
]
```

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/Ok"
          }
        }
      }
    }
  }
}
```

## GET /api/console/v1/admin/users

列出账号与环境名额

权限：`super_admin|admin`。

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/UserList"
          }
        }
      }
    }
  }
}
```

## POST /api/console/v1/admin/users

创建普通用户或管理员

权限：`super_admin|admin`。 super_admin 可创建 user/admin；admin 只能创建 user，且不得提交 role 或 plugin_ids，即使值为 user 或空数组。角色默认 user。创建 user 时账号、初始授权与开通任务在同一事务保存；202 不代表环境已就绪。创建 admin 不接受 model_ids/plugin_ids，不创建环境，runtime 与 job 均为 null。未知字段或混合越权字段整笔拒绝。

参数：
```json
[
  {
    "name": "Idempotency-Key",
    "in": "header",
    "required": true,
    "schema": {
      "type": "string",
      "pattern": "^[A-Za-z0-9_-]{8,100}$"
    },
    "description": "同账号、同接口、同键与同内容返回首次提交结果；内容冲突返回409。已闭合记录保留至少7天。消息生成与外部工具执行不属于自动重试保证。"
  }
]
```

请求与成功响应：
```json
{
  "request": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/UserCreateBody"
      }
    }
  },
  "responses": {
    "202": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/UserChanged"
          }
        }
      }
    }
  }
}
```

## PATCH /api/console/v1/admin/users/{uid}

修改账号启用状态或授权

权限：`super_admin|admin`。 admin 只能管理全部 user 的 active/model_ids，不得携带 plugin_ids。super_admin 另可管理 user 的插件授权及 admin 的 active；admin 账号不接受模型/插件授权。角色不可更改，super_admin 账号不能作为此接口目标。停用立即撤销认证；user 同事务排队停止环境，admin 无环境任务。原已停用 user 重新启用会同事务预留容量并排队 resume；容量不足或暂停任务仍在途返回409，账号仍停用。已启用但被超管手动暂停的账号不会因重复启用或修改授权自动恢复。混合越权字段整笔拒绝。

参数：
```json
[
  {
    "name": "uid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  },
  {
    "name": "Idempotency-Key",
    "in": "header",
    "required": true,
    "schema": {
      "type": "string",
      "pattern": "^[A-Za-z0-9_-]{8,100}$"
    },
    "description": "同账号、同接口、同键与同内容返回首次提交结果；内容冲突返回409。已闭合记录保留至少7天。消息生成与外部工具执行不属于自动重试保证。"
  }
]
```

请求与成功响应：
```json
{
  "request": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/UserUpdateBody"
      }
    }
  },
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/UserChanged"
          }
        }
      }
    }
  }
}
```

## POST /api/console/v1/admin/users/{uid}/reset-password

重设账号初始密码

权限：`super_admin|admin`。

参数：
```json
[
  {
    "name": "uid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  },
  {
    "name": "Idempotency-Key",
    "in": "header",
    "required": true,
    "schema": {
      "type": "string",
      "pattern": "^[A-Za-z0-9_-]{8,100}$"
    },
    "description": "同账号、同接口、同键与同内容返回首次提交结果；内容冲突返回409。已闭合记录保留至少7天。消息生成与外部工具执行不属于自动重试保证。"
  }
]
```

请求与成功响应：
```json
{
  "request": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/PasswordResetBody"
      }
    }
  },
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/PasswordReset"
          }
        }
      }
    }
  }
}
```

## POST /api/console/v1/admin/users/{uid}/runtime/{action}

排队执行环境操作

权限：`super_admin`。 pause 保留数据并停止环境；resume 恢复；retry 重试开通；apply 应用当前授权配置。

参数：
```json
[
  {
    "name": "uid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  },
  {
    "name": "action",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "enum": [
        "pause",
        "resume",
        "retry",
        "apply"
      ]
    }
  },
  {
    "name": "Idempotency-Key",
    "in": "header",
    "required": true,
    "schema": {
      "type": "string",
      "pattern": "^[A-Za-z0-9_-]{8,100}$"
    },
    "description": "同账号、同接口、同键与同内容返回首次提交结果；内容冲突返回409。已闭合记录保留至少7天。消息生成与外部工具执行不属于自动重试保证。"
  }
]
```

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/Queued"
          }
        }
      }
    }
  }
}
```

## GET /api/console/v1/admin/jobs

查看最近环境任务

权限：`super_admin`。 最多最近 200 项。

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "properties": {
              "items": {
                "type": "array",
                "items": {
                  "$ref": "#/components/schemas/Job"
                }
              }
            },
            "additionalProperties": true,
            "required": [
              "items"
            ]
          }
        }
      }
    }
  }
}
```

## GET /api/console/v1/admin/maintenance

查看维护与恢复状态

权限：`super_admin`。 仅超级管理员；不包含用户正文或内部凭据。

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/Maintenance"
          }
        }
      }
    }
  }
}
```

## POST /api/console/v1/admin/maintenance

调整持久维护状态

权限：`super_admin`。 要求当前状态版本；冻结跨重启保留。解除冻结不跳过实际运行状态核对。

参数：
```json
[
  {
    "name": "Idempotency-Key",
    "in": "header",
    "required": true,
    "schema": {
      "type": "string",
      "pattern": "^[A-Za-z0-9_-]{8,100}$"
    },
    "description": "同账号、同接口、同键与同内容返回首次提交结果；内容冲突返回409。已闭合记录保留至少7天。消息生成与外部工具执行不属于自动重试保证。"
  }
]
```

请求与成功响应：
```json
{
  "request": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/MaintenanceBody"
      }
    }
  },
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/Maintenance"
          }
        }
      }
    }
  }
}
```

## GET /api/console/v1/admin/diagnostics/events

事件连接诊断

权限：`super_admin`。 仅超级管理员。返回 Hub、订阅、缓存淘汰、数据库及密码工作池排队/拒绝的聚合计数，不包含账号、任务参数或正文。所有计数随进程重启清零，不代表容量验收结果。

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "additionalProperties": true
          }
        }
      }
    }
  }
}
```

## POST /api/console/v1/admin/recovery/{uid}

处理等待排空的环境

权限：`super_admin`。 仅超管选择继续等待或取消已准入活动后更新；取消不保证撤销外部副作用。

参数：
```json
[
  {
    "name": "uid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  },
  {
    "name": "Idempotency-Key",
    "in": "header",
    "required": true,
    "schema": {
      "type": "string",
      "pattern": "^[A-Za-z0-9_-]{8,100}$"
    },
    "description": "同账号、同接口、同键与同内容返回首次提交结果；内容冲突返回409。已闭合记录保留至少7天。消息生成与外部工具执行不属于自动重试保证。"
  }
]
```

请求与成功响应：
```json
{
  "request": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/RecoveryBody"
      }
    }
  },
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/Queued"
          }
        }
      }
    }
  }
}
```

## GET /api/console/v1/admin/audit

查看最近管理审计

权限：`super_admin|admin`。 最多最近 500 项。actor 为账号 ID 精确筛选，action 为管理动作精确筛选，result 为 success/denied/failed。仅管理操作元数据；不包含业务调用、迁移负载、密钥、正文或文件路径。

参数：
```json
[
  {
    "name": "actor",
    "in": "query",
    "required": false,
    "schema": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Actor"
    }
  },
  {
    "name": "action",
    "in": "query",
    "required": false,
    "schema": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Action"
    }
  },
  {
    "name": "result",
    "in": "query",
    "required": false,
    "schema": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Result"
    }
  }
]
```

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "properties": {
              "items": {
                "type": "array",
                "items": {
                  "$ref": "#/components/schemas/Audit"
                }
              }
            },
            "additionalProperties": true,
            "required": [
              "items"
            ]
          }
        }
      }
    }
  }
}
```

## GET /api/console/v1/admin/models

列出模型配置

权限：`super_admin|admin`。 返回 api_key_configured，不返回密钥值。

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "properties": {
              "items": {
                "type": "array",
                "items": {
                  "$ref": "#/components/schemas/AdminModel"
                }
              }
            },
            "additionalProperties": true,
            "required": [
              "items"
            ]
          }
        }
      }
    }
  }
}
```

## POST /api/console/v1/admin/models

新增可授权模型

权限：`super_admin|admin`。

参数：
```json
[
  {
    "name": "Idempotency-Key",
    "in": "header",
    "required": true,
    "schema": {
      "type": "string",
      "pattern": "^[A-Za-z0-9_-]{8,100}$"
    },
    "description": "同账号、同接口、同键与同内容返回首次提交结果；内容冲突返回409。已闭合记录保留至少7天。消息生成与外部工具执行不属于自动重试保证。"
  }
]
```

请求与成功响应：
```json
{
  "request": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/ModelCreateBody"
      }
    }
  },
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/AdminModel"
          }
        }
      }
    }
  }
}
```

## POST /api/console/v1/admin/models/test

保存前模型连接测试

权限：`super_admin|admin`。 不落模型配置；只验证连接和模型ID，不验证推理或工具能力。

请求与成功响应：
```json
{
  "request": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/ModelCreateBody"
      }
    }
  },
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ModelTestResult"
          }
        }
      }
    }
  }
}
```

## PATCH /api/console/v1/admin/models/{mid}

修改模型并排队应用

权限：`super_admin|admin`。

参数：
```json
[
  {
    "name": "mid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  },
  {
    "name": "Idempotency-Key",
    "in": "header",
    "required": true,
    "schema": {
      "type": "string",
      "pattern": "^[A-Za-z0-9_-]{8,100}$"
    },
    "description": "同账号、同接口、同键与同内容返回首次提交结果；内容冲突返回409。已闭合记录保留至少7天。消息生成与外部工具执行不属于自动重试保证。"
  }
]
```

请求与成功响应：
```json
{
  "request": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/ModelUpdateBody"
      }
    }
  },
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ModelChanged"
          }
        }
      }
    }
  }
}
```

## POST /api/console/v1/admin/models/{mid}/test

测试已保存模型

权限：`super_admin|admin`。 只验证连接和模型ID，返回真实耗时。

参数：
```json
[
  {
    "name": "mid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  }
]
```

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ModelTestResult"
          }
        }
      }
    }
  }
}
```

## GET /api/console/v1/admin/plugins

列出已发布插件版本

权限：`super_admin`。

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "properties": {
              "items": {
                "type": "array",
                "items": {
                  "$ref": "#/components/schemas/AdminPlugin"
                }
              }
            },
            "additionalProperties": true,
            "required": [
              "items"
            ]
          }
        }
      }
    }
  }
}
```

## POST /api/console/v1/admin/plugins

发布经过管理员审核的插件包

权限：`super_admin`。 版本不可覆盖。ZIP 需安全路径、最多 1000 项、解压最多 100 MiB；加载的代码具有该账号环境内代码执行能力，Skill 指令本身不是安全隔离边界。

参数：
```json
[
  {
    "name": "Idempotency-Key",
    "in": "header",
    "required": true,
    "schema": {
      "type": "string",
      "pattern": "^[A-Za-z0-9_-]{8,100}$"
    },
    "description": "同账号、同接口、同键与同内容返回首次提交结果；内容冲突返回409。已闭合记录保留至少7天。消息生成与外部工具执行不属于自动重试保证。"
  }
]
```

请求与成功响应：
```json
{
  "request": {
    "multipart/form-data": {
      "schema": {
        "$ref": "#/components/schemas/PluginUploadBody"
      }
    }
  },
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/AdminPlugin"
          }
        }
      }
    }
  }
}
```

## PATCH /api/console/v1/admin/plugins/{pid}/{version}

启用或停用插件版本

权限：`super_admin`。 相关账号会排队应用配置。

参数：
```json
[
  {
    "name": "pid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  },
  {
    "name": "version",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "title": "Version"
    }
  },
  {
    "name": "Idempotency-Key",
    "in": "header",
    "required": true,
    "schema": {
      "type": "string",
      "pattern": "^[A-Za-z0-9_-]{8,100}$"
    },
    "description": "同账号、同接口、同键与同内容返回首次提交结果；内容冲突返回409。已闭合记录保留至少7天。消息生成与外部工具执行不属于自动重试保证。"
  }
]
```

请求与成功响应：
```json
{
  "request": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/PluginStateBody"
      }
    }
  },
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/Ok"
          }
        }
      }
    }
  }
}
```

## GET /api/console/v1/admin/templates

列出技能模板

权限：`super_admin`。

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "properties": {
              "items": {
                "type": "array",
                "items": {
                  "$ref": "#/components/schemas/Template"
                }
              }
            },
            "additionalProperties": true,
            "required": [
              "items"
            ]
          }
        }
      }
    }
  }
}
```

## POST /api/console/v1/admin/templates

新增技能模板

权限：`super_admin`。

参数：
```json
[
  {
    "name": "Idempotency-Key",
    "in": "header",
    "required": true,
    "schema": {
      "type": "string",
      "pattern": "^[A-Za-z0-9_-]{8,100}$"
    },
    "description": "同账号、同接口、同键与同内容返回首次提交结果；内容冲突返回409。已闭合记录保留至少7天。消息生成与外部工具执行不属于自动重试保证。"
  }
]
```

请求与成功响应：
```json
{
  "request": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/TemplateCreateBody"
      }
    }
  },
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/Template"
          }
        }
      }
    }
  }
}
```

## PATCH /api/console/v1/admin/templates/{tid}

修改技能模板

权限：`super_admin`。

参数：
```json
[
  {
    "name": "tid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  },
  {
    "name": "Idempotency-Key",
    "in": "header",
    "required": true,
    "schema": {
      "type": "string",
      "pattern": "^[A-Za-z0-9_-]{8,100}$"
    },
    "description": "同账号、同接口、同键与同内容返回首次提交结果；内容冲突返回409。已闭合记录保留至少7天。消息生成与外部工具执行不属于自动重试保证。"
  }
]
```

请求与成功响应：
```json
{
  "request": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/TemplateUpdateBody"
      }
    }
  },
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/Template"
          }
        }
      }
    }
  }
}
```

## DELETE /api/console/v1/admin/templates/{tid}

删除技能模板

权限：`super_admin`。

参数：
```json
[
  {
    "name": "tid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  },
  {
    "name": "Idempotency-Key",
    "in": "header",
    "required": true,
    "schema": {
      "type": "string",
      "pattern": "^[A-Za-z0-9_-]{8,100}$"
    },
    "description": "同账号、同接口、同键与同内容返回首次提交结果；内容冲突返回409。已闭合记录保留至少7天。消息生成与外部工具执行不属于自动重试保证。"
  }
]
```

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/Ok"
          }
        }
      }
    }
  }
}
```

## GET /api/console/v1/admin/connections

列出服务连接

权限：`super_admin`。 仅超级管理员；凭据只返回 secret_configured。

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "properties": {
              "items": {
                "type": "array",
                "items": {
                  "$ref": "#/components/schemas/ServiceConnection"
                }
              }
            },
            "additionalProperties": true,
            "required": [
              "items"
            ]
          }
        }
      }
    }
  }
}
```

## POST /api/console/v1/admin/connections

创建固定服务连接

权限：`super_admin`。 配置鉴权、固定地址、方法及路径范围。

参数：
```json
[
  {
    "name": "Idempotency-Key",
    "in": "header",
    "required": true,
    "schema": {
      "type": "string",
      "pattern": "^[A-Za-z0-9_-]{8,100}$"
    },
    "description": "同账号、同接口、同键与同内容返回首次提交结果；内容冲突返回409。已闭合记录保留至少7天。消息生成与外部工具执行不属于自动重试保证。"
  }
]
```

请求与成功响应：
```json
{
  "request": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/ServiceConnectionCreate"
      }
    }
  },
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ServiceConnection"
          }
        }
      }
    }
  }
}
```

## PATCH /api/console/v1/admin/connections/{cid}

更新服务连接

权限：`super_admin`。 新版本配置与受影响安装账号的应用任务在同一事务保存；不影响其他账号。

参数：
```json
[
  {
    "name": "cid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  },
  {
    "name": "Idempotency-Key",
    "in": "header",
    "required": true,
    "schema": {
      "type": "string",
      "pattern": "^[A-Za-z0-9_-]{8,100}$"
    },
    "description": "同账号、同接口、同键与同内容返回首次提交结果；内容冲突返回409。已闭合记录保留至少7天。消息生成与外部工具执行不属于自动重试保证。"
  }
]
```

请求与成功响应：
```json
{
  "request": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/ServiceConnectionUpdate"
      }
    }
  },
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ServiceConnectionChanged"
          }
        }
      }
    }
  }
}
```

## DELETE /api/console/v1/admin/connections/{cid}

删除未绑定的服务连接

权限：`super_admin`。 仍被插件版本引用时返回409；可先停用或解除绑定。

参数：
```json
[
  {
    "name": "cid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  },
  {
    "name": "Idempotency-Key",
    "in": "header",
    "required": true,
    "schema": {
      "type": "string",
      "pattern": "^[A-Za-z0-9_-]{8,100}$"
    },
    "description": "同账号、同接口、同键与同内容返回首次提交结果；内容冲突返回409。已闭合记录保留至少7天。消息生成与外部工具执行不属于自动重试保证。"
  }
]
```

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/Ok"
          }
        }
      }
    }
  }
}
```

## POST /api/console/v1/admin/connections/{cid}/test

测试固定服务连接

权限：`super_admin`。 沿用出口相同的范围、超时与大小校验。只返回状态，不返回业务正文；默认使用已允许的GET路径，写方法测试由超级管理员明确提交。

参数：
```json
[
  {
    "name": "cid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  }
]
```

请求与成功响应：
```json
{
  "request": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/ServiceRequest"
      }
    }
  },
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ServiceTest"
          }
        }
      }
    }
  }
}
```

## GET /api/console/v1/admin/plugins/{pid}/{version}/connections

查看插件版本连接绑定

权限：`super_admin`。 别名由不可变发布清单声明，不能由普通用户配置。

参数：
```json
[
  {
    "name": "pid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  },
  {
    "name": "version",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "title": "Version"
    }
  }
]
```

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/PluginBindings"
          }
        }
      }
    }
  }
}
```

## PUT /api/console/v1/admin/plugins/{pid}/{version}/connections

保存插件版本连接绑定

权限：`super_admin`。 完整替换此版本绑定并原子排队应用。未绑定或停用的必需连接使插件处于 unconfigured，停止在新配置中加载。

参数：
```json
[
  {
    "name": "pid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  },
  {
    "name": "version",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "title": "Version"
    }
  },
  {
    "name": "Idempotency-Key",
    "in": "header",
    "required": true,
    "schema": {
      "type": "string",
      "pattern": "^[A-Za-z0-9_-]{8,100}$"
    },
    "description": "同账号、同接口、同键与同内容返回首次提交结果；内容冲突返回409。已闭合记录保留至少7天。消息生成与外部工具执行不属于自动重试保证。"
  }
]
```

请求与成功响应：
```json
{
  "request": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/PluginBindingBody"
      }
    }
  },
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/PluginBindings"
          }
        }
      }
    }
  }
}
```

## GET /api/console/v1/me/runtime

查询本人助手状态

权限：`user`。 仅按需模式；不访问 Agent；只返回本人公开状态和允许动作。

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/SelfRuntime"
          }
        }
      }
    }
  }
}
```

## POST /api/console/v1/me/runtime/start

显式启动本人助手

权限：`user`。 空对象，不接受账号或宿主参数。202表示申请已受理，200表示已就绪；幂等重放保持原状态码。7A满额返回409；显式启用7B时进入waiting_capacity，返回本人近似位置和到期时间。重试不续期、就绪不自动发送问题；等待队列满返回429。

参数：
```json
[
  {
    "name": "Idempotency-Key",
    "in": "header",
    "required": true,
    "schema": {
      "type": "string",
      "pattern": "^[A-Za-z0-9_-]{8,100}$"
    },
    "description": "同账号、同接口、同键与同内容返回首次提交结果；内容冲突返回409。已闭合记录保留至少7天。消息生成与外部工具执行不属于自动重试保证。"
  }
]
```

请求与成功响应：
```json
{
  "request": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/RuntimeStartBody"
      }
    }
  },
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/SelfRuntimeResult"
          }
        }
      }
    },
    "202": {
      "description": "启停任务已受理；幂等重放维持首次响应语义",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/SelfRuntimeResult"
          }
        }
      }
    }
  }
}
```

## POST /api/console/v1/me/runtime/stop

显式停止或取消本人助手启动

权限：`user`。 状态版本必须匹配；取消启动另传start_job_id。202表示排空停止已受理，200表示无需宿主操作。保留文件和历史，不取消管理员禁止。

参数：
```json
[
  {
    "name": "Idempotency-Key",
    "in": "header",
    "required": true,
    "schema": {
      "type": "string",
      "pattern": "^[A-Za-z0-9_-]{8,100}$"
    },
    "description": "同账号、同接口、同键与同内容返回首次提交结果；内容冲突返回409。已闭合记录保留至少7天。消息生成与外部工具执行不属于自动重试保证。"
  }
]
```

请求与成功响应：
```json
{
  "request": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/RuntimeStopBody"
      }
    }
  },
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/SelfRuntimeResult"
          }
        }
      }
    },
    "202": {
      "description": "启停任务已受理；幂等重放维持首次响应语义",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/SelfRuntimeResult"
          }
        }
      }
    }
  }
}
```

## GET /api/console/v1/files

列出自己的上传文件

权限：`user`。

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "properties": {
              "items": {
                "type": "array",
                "items": {
                  "$ref": "#/components/schemas/File"
                }
              }
            },
            "additionalProperties": true,
            "required": [
              "items"
            ]
          }
        }
      }
    }
  }
}
```

## POST /api/console/v1/files

上传文件并自动排队解析

权限：`user`。 multipart/form-data 中唯一文件字段 file；单文件最大 20 MiB，每账号原始上传累计 1 GiB，实际字节计量。解析 TXT/MD/CSV/XLSX/文本 PDF/DOCX，无 OCR。202 后轮询 files 或 text；queued/parsing 尚未完成。

请求与成功响应：
```json
{
  "request": {
    "multipart/form-data": {
      "schema": {
        "$ref": "#/components/schemas/FileUploadBody"
      }
    }
  },
  "responses": {
    "202": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/File"
          }
        }
      }
    }
  }
}
```

## DELETE /api/console/v1/files/{fid}

删除自己的上传文件

权限：`user`。 上传或解析期间返回 409；删除成功释放原始上传配额。

参数：
```json
[
  {
    "name": "fid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  }
]
```

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/Ok"
          }
        }
      }
    }
  }
}
```

## GET /api/console/v1/results

列出自己的可下载结果文件

权限：`user`。 固定工作区内的显式非隐藏文件；relative_path 仅作展示，下载仍使用 id。

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/ResultList"
          }
        }
      }
    }
  }
}
```

## GET /api/console/v1/results/{fid}/download

下载自己的结果文件

权限：`user`。

参数：
```json
[
  {
    "name": "fid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  }
]
```

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/octet-stream": {
          "schema": {
            "type": "string",
            "format": "binary"
          }
        }
      },
      "headers": {
        "Content-Disposition": {
          "schema": {
            "type": "string"
          },
          "description": "attachment；文件名由服务端安全编码。"
        },
        "X-Content-Type-Options": {
          "schema": {
            "type": "string"
          },
          "description": "nosniff"
        }
      }
    }
  }
}
```

## GET /api/console/v1/files/{fid}/preview

预览文件解析文本

权限：`user`。 最多 20000 字符及 100 个来源块；截断由 truncated 标示。

参数：
```json
[
  {
    "name": "fid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  }
]
```

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/FileText"
          }
        }
      }
    }
  }
}
```

## GET /api/console/v1/files/{fid}/text

读取文件解析文本及来源

权限：`user`。 仅 ready 且未截断可用于模型引用；partial 或 truncated=true 的模型引用会返回 413，可在我的文件查看已提取范围并拆分后重新上传。no_text 表示无可提取文本，扫描件不会执行 OCR。

参数：
```json
[
  {
    "name": "fid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  }
]
```

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "$ref": "#/components/schemas/FileText"
          }
        }
      }
    }
  }
}
```

## GET /api/console/v1/files/{fid}/download

下载原始上传文件

权限：`user`。 原始二进制内容；通过文件 ID 定位，不接受路径。

参数：
```json
[
  {
    "name": "fid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  }
]
```

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/octet-stream": {
          "schema": {
            "type": "string",
            "format": "binary"
          }
        }
      },
      "headers": {
        "Content-Disposition": {
          "schema": {
            "type": "string"
          },
          "description": "attachment；文件名由服务端安全编码。"
        },
        "X-Content-Type-Options": {
          "schema": {
            "type": "string"
          },
          "description": "nosniff"
        }
      }
    }
  }
}
```

## GET /api/console/v1/permissions

列出自己的待确认权限

权限：`user`。

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "properties": {
              "items": {
                "type": "array",
                "items": {
                  "$ref": "#/components/schemas/Confirmation"
                }
              }
            },
            "additionalProperties": true,
            "required": [
              "items"
            ]
          }
        }
      }
    }
  }
}
```

## GET /api/console/v1/questions

列出自己的待回答问题

权限：`user`。

请求与成功响应：
```json
{
  "request": {},
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "properties": {
              "items": {
                "type": "array",
                "items": {
                  "$ref": "#/components/schemas/Confirmation"
                }
              }
            },
            "additionalProperties": true,
            "required": [
              "items"
            ]
          }
        }
      }
    }
  }
}
```

## POST /api/console/v1/permissions/{rid}/reply

允许本次操作或拒绝权限请求

权限：`user`。 只允许 once/reject；拒绝也使用本 reply 路径。

参数：
```json
[
  {
    "name": "rid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  }
]
```

请求与成功响应：
```json
{
  "request": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/PermissionReplyBody"
      }
    }
  },
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "type": "boolean"
          }
        }
      }
    }
  }
}
```

## POST /api/console/v1/questions/{rid}/reply

回答模型问题

权限：`user`。 answers 按问题顺序排列，每题为选项字符串数组。

参数：
```json
[
  {
    "name": "rid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  }
]
```

请求与成功响应：
```json
{
  "request": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/QuestionReplyBody"
      }
    }
  },
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "type": "boolean"
          }
        }
      }
    }
  }
}
```

## POST /api/console/v1/questions/{rid}/reject

拒绝回答模型问题

权限：`user`。 仍需 JSON 对象请求体，可传空对象。

参数：
```json
[
  {
    "name": "rid",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "description": "资源标识；普通业务资源必须属于当前认证账号。"
  }
]
```

请求与成功响应：
```json
{
  "request": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/QuestionRejectBody"
      }
    }
  },
  "responses": {
    "200": {
      "description": "成功",
      "content": {
        "application/json": {
          "schema": {
            "type": "boolean"
          }
        }
      }
    }
  }
}
```

## 字段结构

所有 $ref 指向下面对应组件。类型、必填、枚举和长度限制以此为准。

### Error

```json
{
  "type": "object",
  "properties": {
    "message": {
      "type": "string"
    },
    "code": {
      "type": "string"
    },
    "request_id": {
      "type": "string"
    },
    "field_errors": {
      "type": "object",
      "additionalProperties": {
        "type": "string"
      }
    }
  },
  "additionalProperties": false,
  "required": [
    "message",
    "code"
  ]
}
```

### Ok

```json
{
  "type": "object",
  "properties": {
    "ok": {
      "type": "boolean"
    }
  },
  "additionalProperties": true,
  "required": [
    "ok"
  ]
}
```

### Health

```json
{
  "type": "object",
  "properties": {
    "status": {
      "type": "string"
    },
    "version": {
      "type": "string"
    },
    "schema_version": {
      "type": "integer",
      "enum": [
        4,
        5,
        6
      ]
    },
    "runtime_protocol_version": {
      "type": "integer",
      "const": 2
    }
  },
  "additionalProperties": false,
  "required": [
    "status",
    "version",
    "schema_version"
  ]
}
```

### LoginBody

```json
{
  "type": "object",
  "properties": {
    "username": {
      "type": "string"
    },
    "password": {
      "type": "string",
      "format": "password",
      "writeOnly": true
    }
  },
  "additionalProperties": false,
  "required": [
    "username",
    "password"
  ]
}
```

### PasswordBody

```json
{
  "type": "object",
  "properties": {
    "current_password": {
      "type": "string",
      "format": "password",
      "writeOnly": true
    },
    "password": {
      "type": "string",
      "minLength": 12,
      "maxLength": 256,
      "format": "password",
      "writeOnly": true
    }
  },
  "additionalProperties": false,
  "required": [
    "current_password",
    "password"
  ]
}
```

### TokenBody

```json
{
  "type": "object",
  "properties": {
    "name": {
      "type": "string",
      "maxLength": 80
    }
  },
  "additionalProperties": false
}
```

### SessionBody

```json
{
  "type": "object",
  "properties": {
    "title": {
      "type": "string",
      "maxLength": 200
    }
  },
  "additionalProperties": false
}
```

### MessageBody

```json
{
  "type": "object",
  "properties": {
    "text": {
      "type": "string",
      "minLength": 1,
      "maxLength": 32000,
      "pattern": "\\S",
      "description": "非空白问题。文字、选中技能内容与文件文本合计还受 18000 UTF-8 字节预算限制。"
    },
    "model_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$",
      "description": "GET /models 返回的已授权平台模型 ID；省略时选择授权列表中的默认模型。"
    },
    "skill_ids": {
      "type": "array",
      "items": {
        "type": "string",
        "minLength": 1,
        "maxLength": 100,
        "pattern": "^[A-Za-z0-9_-]+$"
      },
      "maxItems": 5
    },
    "file_ids": {
      "type": "array",
      "items": {
        "type": "string",
        "minLength": 1,
        "maxLength": 100,
        "pattern": "^[A-Za-z0-9_-]+$"
      },
      "maxItems": 5,
      "description": "本账号已解析为 ready 且未截断的上传文件 ID；partial 或 truncated=true 返回 413，要求拆分后重新上传；不接受文件路径或 URL。"
    },
    "client_request_id": {
      "type": "string",
      "format": "uuid",
      "description": "新客户端必须发送。旧客户端省略时服务端生成，不具备客户端重试去重保证。"
    },
    "plugin_ids": {
      "type": "array",
      "items": {
        "type": "string",
        "minLength": 1,
        "maxLength": 100,
        "pattern": "^[A-Za-z0-9_-]+$"
      },
      "maxItems": 5
    },
    "mode": {
      "enum": [
        "standard"
      ]
    }
  },
  "additionalProperties": false,
  "required": [
    "text"
  ]
}
```

### SkillCreateBody

```json
{
  "type": "object",
  "properties": {
    "name": {
      "type": "string",
      "minLength": 1,
      "maxLength": 60,
      "pattern": "^[^/\\\\\\r\\n\\u0000]+$"
    },
    "description": {
      "type": "string",
      "maxLength": 500
    },
    "content": {
      "type": "string",
      "minLength": 1,
      "maxLength": 32000
    },
    "enabled": {
      "type": "boolean"
    },
    "dependency_ids": {
      "type": "array",
      "items": {
        "type": "string",
        "minLength": 1,
        "maxLength": 100,
        "pattern": "^[A-Za-z0-9_-]+$"
      },
      "maxItems": 20
    }
  },
  "additionalProperties": false,
  "required": [
    "name",
    "content"
  ]
}
```

### SkillUpdateBody

```json
{
  "type": "object",
  "properties": {
    "name": {
      "type": "string",
      "minLength": 1,
      "maxLength": 60,
      "pattern": "^[^/\\\\\\r\\n\\u0000]+$"
    },
    "description": {
      "type": "string",
      "maxLength": 500
    },
    "content": {
      "type": "string",
      "minLength": 1,
      "maxLength": 32000
    },
    "enabled": {
      "type": "boolean"
    },
    "dependency_ids": {
      "type": "array",
      "items": {
        "type": "string",
        "minLength": 1,
        "maxLength": 100,
        "pattern": "^[A-Za-z0-9_-]+$"
      },
      "maxItems": 20
    }
  },
  "additionalProperties": false
}
```

### PluginInstallBody

```json
{
  "type": "object",
  "properties": {
    "version": {
      "type": "string",
      "description": "管理员发布的可用版本；省略时选择最新发布的可用版本。"
    },
    "enabled": {
      "type": "boolean"
    },
    "config": {
      "type": "object",
      "additionalProperties": true,
      "description": "必须满足该发布版本的 config_schema；密码字段留空或省略可保留原值。"
    }
  },
  "additionalProperties": false
}
```

### UserCreateBody

```json
{
  "type": "object",
  "properties": {
    "username": {
      "type": "string",
      "minLength": 3,
      "maxLength": 40,
      "pattern": "^[a-zA-Z0-9][a-zA-Z0-9_.-]{2,39}$"
    },
    "password": {
      "type": "string",
      "minLength": 12,
      "maxLength": 256,
      "format": "password",
      "writeOnly": true,
      "description": "省略时生成初始密码，仅在本次响应返回；首次登录必须修改。"
    },
    "role": {
      "type": "string",
      "enum": [
        "user",
        "admin"
      ],
      "default": "user",
      "description": "仅超管可提交此字段；admin 操作者即使提交 role=user 也返回403。创建的管理员账号不创建业务环境且不得携带任何授权字段。"
    },
    "model_ids": {
      "type": "array",
      "items": {
        "type": "string",
        "minLength": 1,
        "maxLength": 100,
        "pattern": "^[A-Za-z0-9_-]+$"
      },
      "maxItems": 100
    },
    "plugin_ids": {
      "type": "array",
      "items": {
        "type": "string",
        "minLength": 1,
        "maxLength": 100,
        "pattern": "^[A-Za-z0-9_-]+$"
      },
      "maxItems": 100
    },
    "display_name": {
      "type": "string"
    },
    "police_no": {
      "type": "string"
    },
    "position": {
      "type": "string"
    },
    "department_id": {
      "anyOf": [
        {
          "type": "string",
          "minLength": 1,
          "maxLength": 100,
          "pattern": "^[A-Za-z0-9_-]+$"
        },
        {
          "type": "null"
        }
      ]
    }
  },
  "additionalProperties": false,
  "required": [
    "username"
  ]
}
```

### UserUpdateBody

```json
{
  "type": "object",
  "properties": {
    "active": {
      "type": "boolean"
    },
    "model_ids": {
      "type": "array",
      "items": {
        "type": "string",
        "minLength": 1,
        "maxLength": 100,
        "pattern": "^[A-Za-z0-9_-]+$"
      },
      "maxItems": 100
    },
    "plugin_ids": {
      "type": "array",
      "items": {
        "type": "string",
        "minLength": 1,
        "maxLength": 100,
        "pattern": "^[A-Za-z0-9_-]+$"
      },
      "maxItems": 100
    },
    "display_name": {
      "type": "string"
    },
    "police_no": {
      "type": "string"
    },
    "position": {
      "type": "string"
    },
    "department_id": {
      "anyOf": [
        {
          "type": "string",
          "minLength": 1,
          "maxLength": 100,
          "pattern": "^[A-Za-z0-9_-]+$"
        },
        {
          "type": "null"
        }
      ]
    }
  },
  "additionalProperties": false
}
```

### PasswordResetBody

```json
{
  "type": "object",
  "properties": {
    "password": {
      "type": "string",
      "minLength": 12,
      "maxLength": 256,
      "format": "password",
      "writeOnly": true,
      "description": "省略时生成新初始密码。撤销旧认证并要求修改。"
    }
  },
  "additionalProperties": false
}
```

### ModelCreateBody

```json
{
  "type": "object",
  "properties": {
    "name": {
      "type": "string",
      "minLength": 1,
      "maxLength": 500
    },
    "description": {
      "type": "string",
      "maxLength": 500
    },
    "base_url": {
      "type": "string",
      "format": "uri",
      "maxLength": 500,
      "description": "管理员配置的 HTTP/HTTPS OpenAI 兼容接口基地址；不得包含 URL 用户信息、查询或片段。"
    },
    "model_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 500,
      "description": "上游服务实际模型 ID；与普通用户选择的平台模型 ID 不同。"
    },
    "api_key": {
      "type": "string",
      "format": "password",
      "writeOnly": true,
      "description": "仅写入；更新时省略或空字符串保留原凭据。允许无鉴权的内网模型。"
    },
    "enabled": {
      "type": "boolean"
    },
    "is_default": {
      "type": "boolean"
    },
    "provider": {
      "type": "string"
    },
    "context_length": {
      "anyOf": [
        {
          "type": "integer",
          "minimum": 256,
          "maximum": 2000000
        },
        {
          "type": "null"
        }
      ]
    },
    "access_mode": {
      "type": "string",
      "enum": [
        "api",
        "local"
      ]
    },
    "supports_tools": {
      "type": "boolean"
    }
  },
  "additionalProperties": false,
  "required": [
    "name",
    "base_url",
    "model_id"
  ]
}
```

### ModelUpdateBody

```json
{
  "type": "object",
  "properties": {
    "name": {
      "type": "string",
      "minLength": 1,
      "maxLength": 500
    },
    "description": {
      "type": "string",
      "maxLength": 500
    },
    "base_url": {
      "type": "string",
      "format": "uri",
      "maxLength": 500,
      "description": "管理员配置的 HTTP/HTTPS OpenAI 兼容接口基地址；不得包含 URL 用户信息、查询或片段。"
    },
    "model_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 500,
      "description": "上游服务实际模型 ID；与普通用户选择的平台模型 ID 不同。"
    },
    "api_key": {
      "type": "string",
      "format": "password",
      "writeOnly": true,
      "description": "仅写入；更新时省略或空字符串保留原凭据。允许无鉴权的内网模型。"
    },
    "enabled": {
      "type": "boolean"
    },
    "is_default": {
      "type": "boolean"
    },
    "provider": {
      "type": "string"
    },
    "context_length": {
      "anyOf": [
        {
          "type": "integer",
          "minimum": 256,
          "maximum": 2000000
        },
        {
          "type": "null"
        }
      ]
    },
    "access_mode": {
      "type": "string",
      "enum": [
        "api",
        "local"
      ]
    },
    "supports_tools": {
      "type": "boolean"
    }
  },
  "additionalProperties": false
}
```

### PluginStateBody

```json
{
  "type": "object",
  "properties": {
    "enabled": {
      "type": "boolean"
    }
  },
  "additionalProperties": false,
  "required": [
    "enabled"
  ]
}
```

### TemplateCreateBody

```json
{
  "type": "object",
  "properties": {
    "name": {
      "type": "string",
      "minLength": 1,
      "maxLength": 60,
      "pattern": "^[^/\\\\\\r\\n\\u0000]+$"
    },
    "description": {
      "type": "string",
      "maxLength": 500
    },
    "content": {
      "type": "string",
      "minLength": 1,
      "maxLength": 32000
    }
  },
  "additionalProperties": false,
  "required": [
    "name",
    "content"
  ]
}
```

### TemplateUpdateBody

```json
{
  "type": "object",
  "properties": {
    "name": {
      "type": "string",
      "minLength": 1,
      "maxLength": 60,
      "pattern": "^[^/\\\\\\r\\n\\u0000]+$"
    },
    "description": {
      "type": "string",
      "maxLength": 500
    },
    "content": {
      "type": "string",
      "minLength": 1,
      "maxLength": 32000
    }
  },
  "additionalProperties": false
}
```

### PermissionReplyBody

```json
{
  "type": "object",
  "properties": {
    "reply": {
      "type": "string",
      "enum": [
        "once",
        "reject"
      ]
    },
    "answers": {
      "type": "array",
      "items": {
        "type": "array",
        "items": {
          "type": "string"
        }
      }
    },
    "message": {
      "type": "string"
    }
  },
  "additionalProperties": false,
  "required": [
    "reply"
  ]
}
```

### QuestionReplyBody

```json
{
  "type": "object",
  "properties": {
    "reply": {
      "type": "string"
    },
    "answers": {
      "type": "array",
      "items": {
        "type": "array",
        "items": {
          "type": "string"
        }
      }
    },
    "message": {
      "type": "string"
    }
  },
  "additionalProperties": false,
  "required": [
    "answers"
  ]
}
```

### QuestionRejectBody

```json
{
  "type": "object",
  "properties": {
    "reply": {
      "type": "string"
    },
    "answers": {
      "type": "array",
      "items": {
        "type": "array",
        "items": {
          "type": "string"
        }
      }
    },
    "message": {
      "type": "string"
    }
  },
  "additionalProperties": false
}
```

### FileUploadBody

```json
{
  "type": "object",
  "properties": {
    "file": {
      "type": "string",
      "format": "binary",
      "description": "一个原始文件，最大 20 MiB。"
    }
  },
  "additionalProperties": false,
  "required": [
    "file"
  ]
}
```

### PluginUploadBody

```json
{
  "type": "object",
  "properties": {
    "file": {
      "type": "string",
      "format": "binary",
      "description": "管理员审核的 ZIP 包，含 manifest.json 与打包好的 .mjs 入口；最大 20 MiB。"
    }
  },
  "additionalProperties": false,
  "required": [
    "file"
  ]
}
```

### Runtime

```json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "status": {
      "type": "string"
    },
    "revision": {
      "type": "integer"
    },
    "desired": {
      "type": "integer"
    },
    "error": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "phase": {
      "type": "string",
      "enum": [
        "claimed",
        "draining",
        "closing",
        "applying",
        "reconciling",
        "awaiting_action",
        "finished"
      ]
    },
    "gate_policy": {
      "type": "string"
    },
    "security_blocked": {
      "type": "boolean"
    },
    "recovery_required": {
      "type": "boolean"
    },
    "cancellation_confirmed": {
      "type": "boolean"
    },
    "interaction": {
      "type": "object",
      "properties": {
        "can_submit_new": {
          "type": "boolean"
        },
        "can_observe": {
          "type": "boolean"
        },
        "can_continue": {
          "type": "boolean"
        }
      },
      "additionalProperties": false,
      "required": [
        "can_submit_new",
        "can_observe",
        "can_continue"
      ]
    },
    "maintenance_mode": {
      "type": "string",
      "enum": [
        "normal",
        "frozen",
        "repair_only"
      ]
    }
  },
  "additionalProperties": true,
  "description": "普通管理员查看他人环境只返回 status；不返回内部运行环境 ID、配置修订或错误详情。 revision 是实际验证的 applied；desired 是期望版本，可能尚未生效。安全阻断不证明外部操作已撤销。",
  "required": [
    "status"
  ]
}
```

### User

```json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "username": {
      "type": "string"
    },
    "role": {
      "type": "string",
      "enum": [
        "user",
        "admin",
        "super_admin"
      ]
    },
    "active": {
      "type": "boolean"
    },
    "must_change_password": {
      "type": "boolean"
    },
    "runtime": {
      "anyOf": [
        {
          "$ref": "#/components/schemas/Runtime"
        },
        {
          "type": "null"
        }
      ]
    },
    "model_ids": {
      "type": "array",
      "items": {
        "type": "string",
        "minLength": 1,
        "maxLength": 100,
        "pattern": "^[A-Za-z0-9_-]+$"
      },
      "maxItems": 100
    },
    "plugin_ids": {
      "type": "array",
      "items": {
        "type": "string",
        "minLength": 1,
        "maxLength": 100,
        "pattern": "^[A-Za-z0-9_-]+$"
      },
      "maxItems": 100
    },
    "display_name": {
      "type": "string"
    },
    "police_no": {
      "type": "string"
    },
    "position": {
      "type": "string"
    },
    "department_id": {
      "anyOf": [
        {
          "type": "string",
          "minLength": 1,
          "maxLength": 100,
          "pattern": "^[A-Za-z0-9_-]+$"
        },
        {
          "type": "null"
        }
      ]
    },
    "department": {
      "anyOf": [
        {
          "$ref": "#/components/schemas/Department"
        },
        {
          "type": "null"
        }
      ]
    },
    "last_login_at": {
      "anyOf": [
        {
          "type": "string",
          "format": "date-time"
        },
        {
          "type": "null"
        }
      ]
    },
    "system_role": {
      "type": "string",
      "enum": [
        "super_admin",
        "admin",
        "user"
      ]
    }
  },
  "additionalProperties": true,
  "required": [
    "id",
    "username",
    "role",
    "active",
    "must_change_password",
    "runtime"
  ]
}
```

### Identity

```json
{
  "type": "object",
  "properties": {
    "user": {
      "$ref": "#/components/schemas/User"
    },
    "csrf_token": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "capabilities": {
      "type": "array",
      "items": {
        "type": "string",
        "enum": [
          "users.manage",
          "admins.manage",
          "models.manage",
          "audit.read",
          "plugins.manage",
          "templates.manage",
          "runtimes.manage",
          "jobs.read",
          "business.use",
          "connections.manage",
          "departments.manage",
          "invocations.read"
        ]
      }
    }
  },
  "additionalProperties": false,
  "required": [
    "user",
    "csrf_token",
    "capabilities"
  ]
}
```

### Token

```json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "name": {
      "type": "string"
    },
    "created": {
      "type": "integer"
    },
    "expires": {
      "type": "integer"
    }
  },
  "additionalProperties": false,
  "required": [
    "id",
    "name",
    "created",
    "expires"
  ]
}
```

### TokenCreated

```json
{
  "type": "object",
  "properties": {
    "token": {
      "type": "string",
      "description": "只在创建响应返回一次；作为 Bearer 使用，不得写入日志。"
    },
    "item": {
      "$ref": "#/components/schemas/Token"
    }
  },
  "additionalProperties": false,
  "required": [
    "token",
    "item"
  ]
}
```

### Job

```json
{
  "type": "object",
  "properties": {
    "id": {
      "anyOf": [
        {
          "type": "string",
          "minLength": 1,
          "maxLength": 100,
          "pattern": "^[A-Za-z0-9_-]+$"
        },
        {
          "type": "null"
        }
      ]
    },
    "uid": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "action": {
      "type": "string"
    },
    "status": {
      "type": "string"
    },
    "revision": {
      "type": "integer"
    },
    "error": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "created": {
      "type": "integer"
    },
    "updated": {
      "type": "integer"
    },
    "phase": {
      "type": "string",
      "enum": [
        "claimed",
        "draining",
        "closing",
        "applying",
        "reconciling",
        "awaiting_action",
        "finished"
      ]
    },
    "not_before": {
      "type": "integer"
    },
    "defer_count": {
      "type": "integer"
    },
    "recovery_required": {
      "type": "boolean"
    }
  },
  "additionalProperties": true,
  "description": "普通管理员由账号或模型变更触发的后台任务仅返回 status，不授予独立任务管理权限。",
  "required": [
    "status"
  ]
}
```

### Queued

```json
{
  "type": "object",
  "properties": {
    "ok": {
      "type": "boolean"
    },
    "id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "job": {
      "anyOf": [
        {
          "$ref": "#/components/schemas/Job"
        },
        {
          "type": "null"
        }
      ]
    }
  },
  "additionalProperties": true,
  "required": [
    "job"
  ]
}
```

### UserChanged

```json
{
  "type": "object",
  "properties": {
    "user": {
      "$ref": "#/components/schemas/User"
    },
    "job": {
      "anyOf": [
        {
          "$ref": "#/components/schemas/Job"
        },
        {
          "type": "null"
        }
      ]
    },
    "password": {
      "type": "string",
      "description": "仅创建响应提供的初始密码；不持久化到客户端日志。"
    }
  },
  "additionalProperties": false,
  "required": [
    "user",
    "job"
  ]
}
```

### PasswordReset

```json
{
  "type": "object",
  "properties": {
    "password": {
      "type": "string",
      "description": "新初始密码；仅本次响应返回。"
    }
  },
  "additionalProperties": false,
  "required": [
    "password"
  ]
}
```

### Model

```json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "name": {
      "type": "string"
    },
    "description": {
      "type": "string"
    },
    "is_default": {
      "anyOf": [
        {
          "type": "boolean"
        },
        {
          "type": "integer",
          "enum": [
            0,
            1
          ]
        }
      ]
    }
  },
  "additionalProperties": false,
  "required": [
    "id",
    "name",
    "description",
    "is_default"
  ]
}
```

### AdminModel

```json
{
  "type": "object",
  "properties": {
    "name": {
      "type": "string",
      "minLength": 1,
      "maxLength": 500
    },
    "description": {
      "type": "string",
      "maxLength": 500
    },
    "base_url": {
      "type": "string",
      "format": "uri",
      "maxLength": 500,
      "description": "管理员配置的 HTTP/HTTPS OpenAI 兼容接口基地址；不得包含 URL 用户信息、查询或片段。"
    },
    "model_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 500,
      "description": "上游服务实际模型 ID；与普通用户选择的平台模型 ID 不同。"
    },
    "enabled": {
      "anyOf": [
        {
          "type": "boolean"
        },
        {
          "type": "integer",
          "enum": [
            0,
            1
          ]
        }
      ]
    },
    "is_default": {
      "anyOf": [
        {
          "type": "boolean"
        },
        {
          "type": "integer",
          "enum": [
            0,
            1
          ]
        }
      ]
    },
    "id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "api_key_configured": {
      "type": "boolean"
    },
    "provider": {
      "type": "string"
    },
    "context_length": {
      "anyOf": [
        {
          "type": "integer",
          "minimum": 256,
          "maximum": 2000000
        },
        {
          "type": "null"
        }
      ]
    },
    "access_mode": {
      "type": "string",
      "enum": [
        "api",
        "local"
      ]
    },
    "supports_tools": {
      "type": "boolean"
    },
    "test_status": {
      "type": "string"
    },
    "updated_at": {
      "anyOf": [
        {
          "type": "string",
          "format": "date-time"
        },
        {
          "type": "null"
        }
      ]
    }
  },
  "additionalProperties": false,
  "required": [
    "id",
    "name",
    "description",
    "base_url",
    "model_id",
    "enabled",
    "is_default",
    "api_key_configured"
  ]
}
```

### ModelChanged

```json
{
  "type": "object",
  "properties": {
    "model": {
      "$ref": "#/components/schemas/AdminModel"
    },
    "jobs": {
      "type": "array",
      "items": {
        "$ref": "#/components/schemas/Job"
      }
    }
  },
  "additionalProperties": false,
  "required": [
    "model",
    "jobs"
  ]
}
```

### ScenarioPresentation

```json
{
  "type": "object",
  "properties": {
    "version": {
      "const": "1.0"
    },
    "turn_id": {
      "type": "string"
    },
    "title": {
      "type": "string"
    },
    "subject_ref": {
      "type": "string"
    },
    "process": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "id": {
            "type": "string"
          },
          "title": {
            "type": "string"
          },
          "detail": {
            "type": "string"
          },
          "status": {
            "enum": [
              "pending",
              "running",
              "completed",
              "failed"
            ]
          },
          "time": {
            "type": "string"
          }
        },
        "additionalProperties": false
      }
    },
    "conclusions": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "text": {
            "type": "string"
          },
          "clue_id": {
            "type": "string"
          },
          "source_ids": {
            "type": "array",
            "items": {
              "type": "string"
            }
          }
        },
        "additionalProperties": false
      }
    },
    "evidence": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "type": {
            "type": "string"
          },
          "title": {
            "type": "string"
          },
          "value": {
            "type": [
              "string",
              "integer"
            ]
          },
          "unit": {
            "type": "string"
          },
          "summary": {
            "type": "string"
          },
          "items": {
            "type": "array",
            "items": {
              "type": "string"
            }
          },
          "clue_id": {
            "type": "string"
          }
        },
        "additionalProperties": false
      }
    },
    "clues": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "id": {
            "type": "string"
          },
          "type": {
            "type": "string"
          },
          "title": {
            "type": "string"
          },
          "headline": {
            "type": "string"
          },
          "summary": {
            "type": "string"
          },
          "discoveries": {
            "type": "array",
            "items": {
              "type": "string"
            }
          },
          "evidence": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "type": {
                  "type": "string"
                },
                "label": {
                  "type": "string"
                },
                "content": {
                  "type": "string"
                },
                "source_ids": {
                  "type": "array",
                  "items": {
                    "type": "string"
                  }
                }
              },
              "additionalProperties": false
            }
          }
        },
        "additionalProperties": false
      }
    },
    "missing": {
      "type": "array",
      "items": {
        "type": "string"
      }
    }
  },
  "additionalProperties": false
}
```

### ScenarioEvidence

```json
{
  "type": "object",
  "properties": {
    "presentation": {
      "$ref": "#/components/schemas/ScenarioPresentation"
    },
    "summary_check": {
      "type": "string"
    },
    "verified_summary": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "fact_id": {
            "type": "string"
          },
          "statement": {
            "type": "string"
          },
          "source_ids": {
            "type": "array",
            "items": {
              "type": "string"
            }
          }
        },
        "additionalProperties": false
      }
    },
    "schema_version": {
      "const": "1"
    },
    "status": {
      "type": "string",
      "enum": [
        "empty",
        "partial",
        "complete",
        "unavailable"
      ]
    },
    "turn_id": {
      "type": "string"
    },
    "notice": {
      "type": "string"
    },
    "scenario": {
      "anyOf": [
        {
          "type": "object",
          "properties": {
            "title": {
              "type": "string"
            },
            "scenario_id": {
              "type": "string"
            },
            "subject_ref": {
              "type": "string"
            },
            "snapshot_id": {
              "type": "string"
            },
            "records_snapshot_id": {
              "type": "string"
            },
            "rule_version": {
              "type": "string"
            },
            "timezone": {
              "type": "string"
            },
            "night_window": {
              "type": "string"
            },
            "case_window": {
              "type": "array",
              "items": {
                "type": "string"
              }
            }
          },
          "additionalProperties": false
        },
        {
          "type": "null"
        }
      ]
    },
    "steps": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "label": {
            "type": "string"
          },
          "status": {
            "type": "string",
            "enum": [
              "pending",
              "running",
              "completed",
              "error"
            ]
          }
        },
        "additionalProperties": false,
        "required": [
          "label",
          "status"
        ]
      }
    },
    "cards": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "id": {
            "type": "string"
          },
          "title": {
            "type": "string"
          },
          "description": {
            "type": "string"
          },
          "time": {
            "type": "string"
          },
          "source_ids": {
            "type": "array",
            "items": {
              "type": "string"
            }
          },
          "fields": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "label": {
                  "type": "string"
                },
                "value": {
                  "type": "string"
                }
              },
              "additionalProperties": false,
              "required": [
                "label",
                "value"
              ]
            }
          },
          "message_id": {
            "type": "string"
          },
          "snapshot_id": {
            "type": "string"
          }
        },
        "additionalProperties": false
      }
    },
    "missing": {
      "type": "array",
      "items": {
        "type": "string"
      }
    },
    "summary": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "label": {
            "type": "string"
          },
          "count": {
            "type": "integer"
          },
          "dates": {
            "type": "array",
            "items": {
              "type": "string"
            }
          },
          "night_count": {
            "type": "integer"
          }
        },
        "additionalProperties": false
      }
    }
  },
  "additionalProperties": false,
  "required": [
    "schema_version",
    "status",
    "notice",
    "scenario",
    "steps",
    "cards",
    "missing",
    "summary"
  ]
}
```

### Session

```json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "title": {
      "type": "string"
    },
    "time": {
      "type": "object",
      "additionalProperties": true
    },
    "parentID": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "status": {
      "type": "string"
    }
  },
  "additionalProperties": true,
  "required": [
    "id"
  ]
}
```

### ScalarMap

```json
{
  "type": "object",
  "maxProperties": 20,
  "propertyNames": {
    "pattern": "^[A-Za-z][A-Za-z0-9_]{0,59}$"
  },
  "additionalProperties": {
    "anyOf": [
      {
        "type": "string",
        "maxLength": 300
      },
      {
        "type": "number"
      },
      {
        "type": "boolean"
      }
    ]
  },
  "description": "管理员批准展示且经过过滤的标量字段；值仅为文字、数字、布尔，不含数组、对象或 null。"
}
```

### CredentialState

```json
{
  "type": "object",
  "additionalProperties": {
    "anyOf": [
      {
        "type": "boolean"
      },
      {
        "$ref": "#/components/schemas/CredentialState"
      }
    ]
  },
  "description": "按嵌套配置字段组织的布尔状态树；只表明是否已配置，不含凭据值。"
}
```

### Message

```json
{
  "type": "object",
  "properties": {
    "info": {
      "type": "object",
      "properties": {
        "id": {
          "type": "string",
          "minLength": 1,
          "maxLength": 100,
          "pattern": "^[A-Za-z0-9_-]+$"
        },
        "role": {
          "type": "string"
        },
        "time": {
          "type": "object",
          "additionalProperties": true
        },
        "sessionID": {
          "type": "string",
          "minLength": 1,
          "maxLength": 100,
          "pattern": "^[A-Za-z0-9_-]+$"
        },
        "finish": {
          "type": "string"
        },
        "error": {
          "type": "object",
          "properties": {
            "message": {
              "type": "string"
            }
          },
          "additionalProperties": false,
          "required": [
            "message"
          ]
        }
      },
      "additionalProperties": true
    },
    "parts": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "id": {
            "type": "string",
            "minLength": 1,
            "maxLength": 100,
            "pattern": "^[A-Za-z0-9_-]+$"
          },
          "type": {
            "type": "string",
            "enum": [
              "text",
              "tool",
              "analysis_result"
            ]
          },
          "sessionID": {
            "type": "string",
            "minLength": 1,
            "maxLength": 100,
            "pattern": "^[A-Za-z0-9_-]+$"
          },
          "messageID": {
            "type": "string",
            "minLength": 1,
            "maxLength": 100,
            "pattern": "^[A-Za-z0-9_-]+$"
          },
          "text": {
            "type": "string"
          },
          "tool": {
            "type": "string"
          },
          "state": {
            "type": "object",
            "properties": {
              "status": {
                "type": "string"
              },
              "title": {
                "type": "string"
              }
            },
            "additionalProperties": true
          },
          "details": {
            "type": "object",
            "properties": {
              "inputs": {
                "$ref": "#/components/schemas/ScalarMap"
              },
              "outputs": {
                "$ref": "#/components/schemas/ScalarMap"
              }
            },
            "additionalProperties": false,
            "required": [
              "inputs",
              "outputs"
            ]
          },
          "data": {
            "$ref": "#/components/schemas/AnalysisResult"
          }
        },
        "additionalProperties": true
      }
    }
  },
  "additionalProperties": false,
  "required": [
    "info",
    "parts"
  ]
}
```

### MessageAccepted

```json
{
  "type": "object",
  "properties": {
    "accepted": {
      "type": "boolean",
      "const": true
    },
    "run_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    }
  },
  "additionalProperties": false,
  "required": [
    "accepted",
    "run_id"
  ]
}
```

### Skill

```json
{
  "type": "object",
  "properties": {
    "name": {
      "type": "string",
      "minLength": 1,
      "maxLength": 60,
      "pattern": "^[^/\\\\\\r\\n\\u0000]+$"
    },
    "description": {
      "type": "string",
      "maxLength": 500
    },
    "content": {
      "type": "string",
      "minLength": 1,
      "maxLength": 32000
    },
    "enabled": {
      "anyOf": [
        {
          "type": "boolean"
        },
        {
          "type": "integer",
          "enum": [
            0,
            1
          ]
        }
      ]
    },
    "id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "version": {
      "type": "integer"
    },
    "job": {
      "$ref": "#/components/schemas/Job"
    },
    "dependency_ids": {
      "type": "array",
      "items": {
        "type": "string",
        "minLength": 1,
        "maxLength": 100,
        "pattern": "^[A-Za-z0-9_-]+$"
      },
      "maxItems": 20
    }
  },
  "additionalProperties": false,
  "required": [
    "id",
    "name",
    "description",
    "content",
    "enabled",
    "version"
  ]
}
```

### Template

```json
{
  "type": "object",
  "properties": {
    "name": {
      "type": "string",
      "minLength": 1,
      "maxLength": 60,
      "pattern": "^[^/\\\\\\r\\n\\u0000]+$"
    },
    "description": {
      "type": "string",
      "maxLength": 500
    },
    "content": {
      "type": "string",
      "minLength": 1,
      "maxLength": 32000
    },
    "id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    }
  },
  "additionalProperties": false,
  "required": [
    "id",
    "name",
    "content"
  ]
}
```

### Plugin

```json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "version": {
      "type": "string"
    },
    "name": {
      "type": "string"
    },
    "description": {
      "type": "string"
    },
    "versions": {
      "type": "array",
      "items": {
        "type": "string"
      }
    },
    "config_schema": {
      "type": "object",
      "additionalProperties": true,
      "description": "最新可用发布版本的表单 schema。"
    },
    "schemas": {
      "type": "object",
      "additionalProperties": {
        "type": "object",
        "additionalProperties": true
      },
      "description": "可用版本号到该版本表单 schema 的映射；编辑时选择对应版本，不能一律使用最新 schema。"
    },
    "installed": {
      "anyOf": [
        {
          "type": "object",
          "properties": {
            "version": {
              "type": "string"
            },
            "enabled": {
              "type": "boolean"
            },
            "config": {
              "type": "object"
            },
            "credentials_configured": {
              "$ref": "#/components/schemas/CredentialState"
            },
            "state": {
              "type": "string",
              "enum": [
                "active",
                "pending",
                "unavailable",
                "unconfigured"
              ]
            },
            "missing_connections": {
              "type": "array",
              "items": {
                "type": "string"
              }
            }
          },
          "additionalProperties": false,
          "required": [
            "version",
            "enabled",
            "config",
            "credentials_configured",
            "state"
          ]
        },
        {
          "type": "null"
        }
      ]
    },
    "connection_status": {
      "type": "object",
      "additionalProperties": {
        "type": "object",
        "properties": {
          "ready": {
            "type": "boolean"
          },
          "missing": {
            "type": "array",
            "items": {
              "type": "string"
            }
          }
        },
        "additionalProperties": false,
        "required": [
          "ready",
          "missing"
        ]
      }
    }
  },
  "additionalProperties": false,
  "required": [
    "id",
    "version",
    "name",
    "description",
    "versions",
    "config_schema",
    "schemas",
    "installed"
  ]
}
```

### AdminPlugin

```json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "version": {
      "type": "string"
    },
    "name": {
      "type": "string"
    },
    "description": {
      "type": "string"
    },
    "digest": {
      "type": "string"
    },
    "enabled": {
      "anyOf": [
        {
          "type": "boolean"
        },
        {
          "type": "integer",
          "enum": [
            0,
            1
          ]
        }
      ]
    },
    "connections": {
      "type": "object",
      "additionalProperties": {
        "type": "object",
        "properties": {
          "description": {
            "type": "string"
          }
        },
        "additionalProperties": false
      }
    }
  },
  "additionalProperties": true,
  "required": [
    "id",
    "version"
  ]
}
```

### ConnectionTest

```json
{
  "type": "object",
  "properties": {
    "ok": {
      "type": "boolean"
    },
    "message": {
      "type": "string"
    },
    "supported": {
      "type": "boolean"
    },
    "connection_tested": {
      "type": "boolean"
    }
  },
  "additionalProperties": false,
  "required": [
    "ok",
    "message"
  ]
}
```

### File

```json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "name": {
      "type": "string"
    },
    "extension": {
      "type": "string"
    },
    "size": {
      "type": "integer",
      "minimum": 0
    },
    "status": {
      "type": "string",
      "enum": [
        "uploading",
        "queued",
        "parsing",
        "ready",
        "partial",
        "no_text",
        "unsupported",
        "failed"
      ]
    },
    "created_at": {
      "type": "string",
      "format": "date-time"
    },
    "updated_at": {
      "type": "string",
      "format": "date-time"
    },
    "truncated": {
      "type": "boolean"
    },
    "error": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "warnings": {
      "type": "array",
      "items": {
        "type": "string"
      }
    }
  },
  "additionalProperties": true,
  "required": [
    "id",
    "name",
    "size",
    "status",
    "truncated"
  ]
}
```

### TextChunk

```json
{
  "type": "object",
  "properties": {
    "text": {
      "type": "string"
    },
    "source": {
      "type": "object",
      "additionalProperties": true,
      "description": "解析器来源标注，例如行号、工作表/表格及行号、PDF 页码或 DOCX 段落号；不是绝对路径。"
    }
  },
  "additionalProperties": false,
  "required": [
    "text",
    "source"
  ]
}
```

### FileText

```json
{
  "type": "object",
  "properties": {
    "text": {
      "type": "string"
    },
    "chunks": {
      "type": "array",
      "items": {
        "$ref": "#/components/schemas/TextChunk"
      }
    },
    "truncated": {
      "type": "boolean"
    },
    "status": {
      "type": "string",
      "enum": [
        "uploading",
        "queued",
        "parsing",
        "ready",
        "partial",
        "no_text",
        "unsupported",
        "failed"
      ]
    },
    "name": {
      "type": "string"
    }
  },
  "additionalProperties": false,
  "required": [
    "text",
    "chunks",
    "truncated",
    "status",
    "name"
  ]
}
```

### Result

```json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "name": {
      "type": "string"
    },
    "relative_path": {
      "type": "string"
    },
    "size": {
      "type": "integer"
    },
    "modified_at": {
      "type": "string",
      "format": "date-time"
    }
  },
  "additionalProperties": false,
  "required": [
    "id",
    "name",
    "relative_path",
    "size",
    "modified_at"
  ]
}
```

### Confirmation

```json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "sessionID": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "questions": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": true
      }
    },
    "description": {
      "type": "string"
    }
  },
  "additionalProperties": false,
  "required": [
    "id",
    "sessionID",
    "questions",
    "description"
  ]
}
```

### Audit

```json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "actor": {
      "type": "string"
    },
    "actor_role": {
      "type": "string"
    },
    "action": {
      "type": "string"
    },
    "target": {
      "type": "string"
    },
    "result": {
      "type": "string",
      "enum": [
        "success",
        "denied",
        "failed"
      ]
    },
    "created": {
      "type": "integer"
    },
    "username": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    }
  },
  "additionalProperties": false,
  "required": [
    "id",
    "actor",
    "actor_role",
    "action",
    "target",
    "result",
    "created",
    "username"
  ]
}
```

### CompleteBody

```json
{
  "type": "object",
  "properties": {
    "lease": {
      "type": "string",
      "writeOnly": true
    },
    "attempt": {
      "type": "integer",
      "minimum": 1
    },
    "operation_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "ok": {
      "type": "boolean"
    },
    "deferred": {
      "type": "boolean"
    },
    "defer_reason": {
      "type": "string",
      "enum": [
        "runtime_busy"
      ]
    },
    "error": {
      "type": "string"
    },
    "rolled_back": {
      "type": "boolean"
    },
    "observation_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "cleanup_confirmed": {
      "type": "boolean"
    }
  },
  "additionalProperties": false,
  "description": "相同 operation_id 和内容返回原回执；内容冲突为409。defer仅可用于确认的runtime_busy，延后时间由Control计算。回执不证明当前仍可开放入口。",
  "required": [
    "lease",
    "attempt",
    "operation_id"
  ]
}
```

### LegacyImportBody

```json
{
  "type": "object",
  "properties": {
    "username": {
      "type": "string"
    },
    "password": {
      "type": "string",
      "minLength": 12,
      "maxLength": 256,
      "format": "password",
      "writeOnly": true
    },
    "model_ids": {
      "type": "array",
      "items": {
        "type": "string",
        "minLength": 1,
        "maxLength": 100,
        "pattern": "^[A-Za-z0-9_-]+$"
      },
      "maxItems": 100
    },
    "legacy": {
      "type": "object",
      "properties": {
        "home_volume": {
          "type": "string"
        },
        "workspace_volume": {
          "type": "string"
        }
      },
      "additionalProperties": false,
      "description": "仅允许执行器预登记并实际核验的固定旧卷组合；禁止任意路径或卷。",
      "required": [
        "home_volume",
        "workspace_volume"
      ]
    },
    "snapshot": {
      "type": "object",
      "properties": {
        "id": {
          "type": "string",
          "minLength": 1,
          "maxLength": 100,
          "pattern": "^[A-Za-z0-9_-]+$"
        },
        "sha256": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$"
        }
      },
      "additionalProperties": false,
      "required": [
        "id",
        "sha256"
      ]
    }
  },
  "additionalProperties": false,
  "required": [
    "username",
    "password",
    "legacy",
    "snapshot"
  ]
}
```

### LegacyRollbackBody

```json
{
  "type": "object",
  "properties": {
    "uid": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "snapshot_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "cleanup_confirmed": {
      "type": "boolean",
      "const": true
    },
    "observation_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "expected_state_version": {
      "type": "integer"
    },
    "operation_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    }
  },
  "additionalProperties": false,
  "required": [
    "uid",
    "snapshot_id",
    "cleanup_confirmed",
    "observation_id",
    "expected_state_version",
    "operation_id"
  ]
}
```

### LegacyRetryBody

```json
{
  "type": "object",
  "properties": {
    "uid": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "snapshot_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "legacy_stopped": {
      "type": "boolean",
      "const": true,
      "description": "可信执行器已实际核验对应旧环境停止；不是普通用户可声明的生命周期操作。"
    }
  },
  "additionalProperties": false,
  "required": [
    "uid",
    "snapshot_id",
    "legacy_stopped"
  ]
}
```

### LegacyRetryResult

```json
{
  "type": "object",
  "properties": {
    "uid": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "runtime_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "status": {
      "type": "string",
      "enum": [
        "provisioning",
        "ready"
      ]
    },
    "revision": {
      "type": "integer"
    },
    "desired": {
      "type": "integer"
    },
    "job_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    }
  },
  "additionalProperties": false,
  "required": [
    "uid",
    "runtime_id",
    "status",
    "revision",
    "desired",
    "job_id"
  ]
}
```

### LegacyStatus

```json
{
  "type": "object",
  "properties": {
    "uid": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "runtime_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "created": {
      "type": "boolean"
    },
    "status": {
      "type": "string"
    },
    "revision": {
      "type": "integer"
    },
    "desired": {
      "type": "integer"
    },
    "reserved": {
      "type": "boolean"
    }
  },
  "additionalProperties": true,
  "required": [
    "uid",
    "runtime_id",
    "status"
  ]
}
```

### UserList

```json
{
  "type": "object",
  "properties": {
    "items": {
      "type": "array",
      "items": {
        "$ref": "#/components/schemas/User"
      }
    },
    "capacity": {
      "type": "object",
      "properties": {
        "maximum": {
          "type": "integer"
        },
        "reserved": {
          "type": "integer"
        }
      },
      "additionalProperties": false,
      "required": [
        "maximum",
        "reserved"
      ]
    }
  },
  "additionalProperties": false,
  "required": [
    "items",
    "capacity"
  ]
}
```

### ResultList

```json
{
  "type": "object",
  "properties": {
    "items": {
      "type": "array",
      "items": {
        "$ref": "#/components/schemas/Result"
      }
    },
    "truncated": {
      "type": "boolean"
    }
  },
  "additionalProperties": false,
  "required": [
    "items",
    "truncated"
  ]
}
```

### Platform

```json
{
  "type": "object",
  "properties": {
    "name": {
      "type": "string"
    },
    "short_name": {
      "type": "string"
    },
    "description": {
      "type": "string"
    }
  },
  "additionalProperties": false,
  "required": [
    "name",
    "short_name",
    "description"
  ]
}
```

### ServiceConnectionCreate

```json
{
  "type": "object",
  "properties": {
    "name": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100
    },
    "base_url": {
      "type": "string",
      "format": "uri",
      "maxLength": 1000
    },
    "auth_type": {
      "type": "string",
      "enum": [
        "none",
        "bearer",
        "api_key"
      ],
      "default": "none"
    },
    "secret": {
      "type": "string",
      "format": "password",
      "writeOnly": true,
      "maxLength": 4096,
      "description": "不回显；鉴权方式及头名未变时，省略或空串保留旧值。修改鉴权方式须重新填写，none 清除旧值。"
    },
    "header_name": {
      "type": "string"
    },
    "enabled": {
      "type": "boolean"
    },
    "allowed_methods": {
      "type": "array",
      "items": {
        "type": "string",
        "enum": [
          "GET",
          "POST",
          "PUT",
          "PATCH",
          "DELETE"
        ]
      },
      "minItems": 1,
      "maxItems": 5
    },
    "allowed_paths": {
      "type": "array",
      "items": {
        "type": "string",
        "description": "精确路径或末尾 /* 前缀匹配；不接受转义、查询、片段和目录跳转。"
      },
      "minItems": 1,
      "maxItems": 100
    },
    "timeout_seconds": {
      "type": "integer",
      "minimum": 1,
      "maximum": 60,
      "default": 15
    },
    "max_response_bytes": {
      "type": "integer",
      "minimum": 1024,
      "maximum": 10485760,
      "default": 1048576
    }
  },
  "additionalProperties": false,
  "required": [
    "name",
    "base_url"
  ]
}
```

### ServiceConnectionUpdate

```json
{
  "type": "object",
  "properties": {
    "name": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100
    },
    "base_url": {
      "type": "string",
      "format": "uri",
      "maxLength": 1000
    },
    "auth_type": {
      "type": "string",
      "enum": [
        "none",
        "bearer",
        "api_key"
      ],
      "default": "none"
    },
    "secret": {
      "type": "string",
      "format": "password",
      "writeOnly": true,
      "maxLength": 4096,
      "description": "不回显；鉴权方式及头名未变时，省略或空串保留旧值。修改鉴权方式须重新填写，none 清除旧值。"
    },
    "header_name": {
      "type": "string"
    },
    "enabled": {
      "type": "boolean"
    },
    "allowed_methods": {
      "type": "array",
      "items": {
        "type": "string",
        "enum": [
          "GET",
          "POST",
          "PUT",
          "PATCH",
          "DELETE"
        ]
      },
      "minItems": 1,
      "maxItems": 5
    },
    "allowed_paths": {
      "type": "array",
      "items": {
        "type": "string",
        "description": "精确路径或末尾 /* 前缀匹配；不接受转义、查询、片段和目录跳转。"
      },
      "minItems": 1,
      "maxItems": 100
    },
    "timeout_seconds": {
      "type": "integer",
      "minimum": 1,
      "maximum": 60,
      "default": 15
    },
    "max_response_bytes": {
      "type": "integer",
      "minimum": 1024,
      "maximum": 10485760,
      "default": 1048576
    }
  },
  "additionalProperties": false
}
```

### ServiceConnection

```json
{
  "type": "object",
  "properties": {
    "name": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100
    },
    "base_url": {
      "type": "string",
      "format": "uri",
      "maxLength": 1000
    },
    "auth_type": {
      "type": "string",
      "enum": [
        "none",
        "bearer",
        "api_key"
      ],
      "default": "none"
    },
    "header_name": {
      "type": "string"
    },
    "enabled": {
      "type": "boolean"
    },
    "allowed_methods": {
      "type": "array",
      "items": {
        "type": "string",
        "enum": [
          "GET",
          "POST",
          "PUT",
          "PATCH",
          "DELETE"
        ]
      },
      "minItems": 1,
      "maxItems": 5
    },
    "allowed_paths": {
      "type": "array",
      "items": {
        "type": "string",
        "description": "精确路径或末尾 /* 前缀匹配；不接受转义、查询、片段和目录跳转。"
      },
      "minItems": 1,
      "maxItems": 100
    },
    "timeout_seconds": {
      "type": "integer",
      "minimum": 1,
      "maximum": 60,
      "default": 15
    },
    "max_response_bytes": {
      "type": "integer",
      "minimum": 1024,
      "maximum": 10485760,
      "default": 1048576
    },
    "id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "secret_configured": {
      "type": "boolean"
    },
    "revision": {
      "type": "integer"
    }
  },
  "additionalProperties": false,
  "required": [
    "id",
    "name",
    "base_url",
    "secret_configured",
    "revision"
  ]
}
```

### ServiceConnectionChanged

```json
{
  "type": "object",
  "properties": {
    "connection": {
      "$ref": "#/components/schemas/ServiceConnection"
    },
    "jobs": {
      "type": "array",
      "items": {
        "$ref": "#/components/schemas/Job"
      }
    }
  },
  "additionalProperties": false,
  "required": [
    "connection",
    "jobs"
  ]
}
```

### ServiceRequest

```json
{
  "type": "object",
  "properties": {
    "method": {
      "type": "string",
      "enum": [
        "GET",
        "POST",
        "PUT",
        "PATCH",
        "DELETE"
      ]
    },
    "path": {
      "type": "string"
    },
    "query": {
      "type": "object",
      "additionalProperties": {
        "type": [
          "string",
          "number",
          "boolean"
        ]
      }
    },
    "json": {}
  },
  "additionalProperties": false,
  "required": [
    "path"
  ]
}
```

### ServiceTest

```json
{
  "type": "object",
  "properties": {
    "ok": {
      "type": "boolean"
    },
    "message": {
      "type": "string"
    },
    "status": {
      "type": "integer"
    }
  },
  "additionalProperties": false,
  "required": [
    "ok",
    "message"
  ]
}
```

### PluginBindingBody

```json
{
  "type": "object",
  "properties": {
    "bindings": {
      "type": "object",
      "additionalProperties": {
        "type": "string",
        "minLength": 1,
        "maxLength": 100,
        "pattern": "^[A-Za-z0-9_-]+$"
      }
    }
  },
  "additionalProperties": false,
  "required": [
    "bindings"
  ]
}
```

### PluginBindings

```json
{
  "type": "object",
  "properties": {
    "bindings": {
      "type": "object",
      "additionalProperties": {
        "type": "string",
        "minLength": 1,
        "maxLength": 100,
        "pattern": "^[A-Za-z0-9_-]+$"
      }
    },
    "aliases": {
      "type": "object",
      "additionalProperties": {
        "type": "object",
        "properties": {
          "description": {
            "type": "string"
          }
        },
        "additionalProperties": false
      }
    },
    "jobs": {
      "type": "array",
      "items": {
        "$ref": "#/components/schemas/Job"
      }
    }
  },
  "additionalProperties": false,
  "required": [
    "bindings",
    "aliases"
  ]
}
```

### RuntimeStartBody

```json
{
  "type": "object",
  "properties": {},
  "additionalProperties": false
}
```

### PoolInventoryBody

```json
{
  "type": "object",
  "properties": {
    "host_boot_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "observed_at": {
      "type": "integer"
    },
    "registry_digest": {
      "type": "string"
    },
    "complete": {
      "type": "boolean"
    },
    "resources": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "runtime_id": {
            "type": "string",
            "minLength": 1,
            "maxLength": 100,
            "pattern": "^[A-Za-z0-9_-]+$"
          },
          "uid": {
            "type": "string",
            "minLength": 1,
            "maxLength": 100,
            "pattern": "^[A-Za-z0-9_-]+$"
          },
          "running": {
            "type": "boolean"
          },
          "mutation_state": {
            "type": "string",
            "enum": [
              "idle",
              "running",
              "unknown"
            ]
          }
        },
        "additionalProperties": false,
        "required": [
          "runtime_id",
          "uid",
          "running",
          "mutation_state"
        ]
      },
      "maxItems": 10000
    }
  },
  "additionalProperties": false,
  "required": [
    "host_boot_id",
    "observed_at",
    "registry_digest",
    "complete",
    "resources"
  ]
}
```

### RuntimeStopBody

```json
{
  "type": "object",
  "properties": {
    "expected_state_version": {
      "type": "integer",
      "minimum": 0
    },
    "start_job_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    }
  },
  "additionalProperties": false,
  "required": [
    "expected_state_version"
  ]
}
```

### SelfRuntime

```json
{
  "type": "object",
  "properties": {
    "runtime_mode": {
      "type": "string",
      "const": "on_demand"
    },
    "status": {
      "type": "string"
    },
    "ready": {
      "type": "boolean"
    },
    "state_version": {
      "type": "integer"
    },
    "desired": {
      "type": "integer"
    },
    "revision": {
      "type": "integer"
    },
    "stop_reason": {
      "type": "string"
    },
    "manual_stop_reason": {
      "type": "string"
    },
    "allowed_actions": {
      "type": "array",
      "items": {
        "type": "string",
        "enum": [
          "start",
          "stop"
        ]
      }
    },
    "job": {
      "anyOf": [
        {
          "$ref": "#/components/schemas/Job"
        },
        {
          "type": "null"
        }
      ]
    },
    "waiting": {
      "anyOf": [
        {
          "type": "object",
          "properties": {
            "expires_at": {
              "type": "integer"
            },
            "approximate_position": {
              "type": "integer"
            }
          },
          "additionalProperties": false
        },
        {
          "type": "null"
        }
      ]
    },
    "wait_result": {
      "type": [
        "string",
        "null"
      ]
    },
    "interaction": {
      "type": "object",
      "properties": {
        "can_submit_new": {
          "type": "boolean"
        },
        "can_observe": {
          "type": "boolean"
        },
        "can_continue": {
          "type": "boolean"
        }
      },
      "additionalProperties": false,
      "required": [
        "can_submit_new",
        "can_observe",
        "can_continue"
      ]
    },
    "maintenance_mode": {
      "type": "string",
      "enum": [
        "normal",
        "frozen",
        "repair_only"
      ]
    }
  },
  "additionalProperties": true
}
```

### SelfRuntimeResult

```json
{
  "type": "object",
  "properties": {
    "accepted": {
      "type": "boolean"
    },
    "runtime": {
      "$ref": "#/components/schemas/SelfRuntime"
    },
    "job": {
      "anyOf": [
        {
          "$ref": "#/components/schemas/Job"
        },
        {
          "type": "null"
        }
      ]
    }
  },
  "additionalProperties": false,
  "required": [
    "accepted",
    "runtime",
    "job"
  ]
}
```

### IdleProof

```json
{
  "type": "object",
  "properties": {
    "complete": {
      "type": "boolean"
    },
    "sequence": {
      "type": "integer"
    },
    "idle_seconds": {
      "type": "number",
      "minimum": 0
    }
  },
  "additionalProperties": false,
  "required": [
    "complete",
    "sequence",
    "idle_seconds"
  ]
}
```

### IdleObservationBody

```json
{
  "type": "object",
  "properties": {
    "uid": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "state_version": {
      "type": "integer"
    },
    "gateway_boot_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "observed_at": {
      "type": "integer"
    },
    "idle_proof": {
      "anyOf": [
        {
          "$ref": "#/components/schemas/IdleProof"
        },
        {
          "type": "null"
        }
      ]
    },
    "activity_count": {
      "type": [
        "integer",
        "null"
      ]
    },
    "complete": {
      "type": "boolean"
    }
  },
  "additionalProperties": false,
  "required": [
    "uid",
    "state_version",
    "gateway_boot_id",
    "observed_at",
    "idle_proof",
    "activity_count",
    "complete"
  ]
}
```

### PhaseBody

```json
{
  "type": "object",
  "properties": {
    "lease": {
      "type": "string",
      "writeOnly": true
    },
    "attempt": {
      "type": "integer",
      "minimum": 1
    },
    "operation_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "expected_phase": {
      "type": "string",
      "enum": [
        "claimed",
        "draining",
        "closing",
        "applying",
        "reconciling",
        "awaiting_action",
        "finished"
      ]
    },
    "phase": {
      "type": "string",
      "enum": [
        "claimed",
        "draining",
        "closing",
        "applying",
        "reconciling",
        "awaiting_action",
        "finished"
      ]
    },
    "observation_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    }
  },
  "additionalProperties": false,
  "required": [
    "lease",
    "attempt",
    "operation_id",
    "expected_phase",
    "phase"
  ]
}
```

### BootBody

```json
{
  "type": "object",
  "properties": {
    "lease": {
      "type": "string",
      "writeOnly": true
    },
    "attempt": {
      "type": "integer",
      "minimum": 1
    },
    "operation_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "runtime_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "gateway_boot_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "relay_boot_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    }
  },
  "additionalProperties": false,
  "required": [
    "lease",
    "attempt",
    "operation_id",
    "runtime_id",
    "gateway_boot_id",
    "relay_boot_id"
  ]
}
```

### ObservationBody

```json
{
  "type": "object",
  "properties": {
    "observation_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "runtime_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "state_version": {
      "type": "integer"
    },
    "host_boot_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "observed_at": {
      "type": "integer"
    },
    "components": {
      "type": "object",
      "properties": {
        "agent": {
          "type": "string",
          "enum": [
            "running",
            "stopped",
            "unknown"
          ]
        },
        "gateway": {
          "type": "string",
          "enum": [
            "running",
            "stopped",
            "unknown"
          ]
        },
        "relay": {
          "type": "string",
          "enum": [
            "running",
            "stopped",
            "unknown"
          ]
        }
      },
      "additionalProperties": false,
      "required": [
        "agent",
        "gateway",
        "relay"
      ]
    },
    "mutation_state": {
      "type": "string",
      "enum": [
        "idle",
        "running",
        "unknown"
      ]
    },
    "complete": {
      "type": "boolean"
    },
    "evidence_ref": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "job_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "attempt": {
      "type": "integer"
    },
    "lease": {
      "type": "string",
      "writeOnly": true
    },
    "gateway_boot_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "gate_epoch": {
      "type": "integer"
    },
    "accepting": {
      "type": "boolean"
    },
    "egress_closed": {
      "type": "boolean"
    },
    "activity_count": {
      "type": [
        "integer",
        "null"
      ]
    },
    "applied_revision": {
      "type": "integer"
    },
    "spec_digest": {
      "type": [
        "string",
        "null"
      ]
    },
    "idle_proof": {
      "anyOf": [
        {
          "$ref": "#/components/schemas/IdleProof"
        },
        {
          "type": "null"
        }
      ]
    }
  },
  "additionalProperties": false,
  "required": [
    "observation_id",
    "runtime_id",
    "state_version",
    "host_boot_id",
    "observed_at",
    "components",
    "mutation_state",
    "complete",
    "evidence_ref",
    "job_id",
    "attempt",
    "lease",
    "gateway_boot_id",
    "gate_epoch",
    "accepting",
    "egress_closed",
    "activity_count",
    "applied_revision",
    "spec_digest"
  ]
}
```

### ReconcileBody

```json
{
  "type": "object",
  "properties": {
    "observation_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "runtime_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "state_version": {
      "type": "integer"
    },
    "host_boot_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "observed_at": {
      "type": "integer"
    },
    "components": {
      "type": "object",
      "properties": {
        "agent": {
          "type": "string",
          "enum": [
            "running",
            "stopped",
            "unknown"
          ]
        },
        "gateway": {
          "type": "string",
          "enum": [
            "running",
            "stopped",
            "unknown"
          ]
        },
        "relay": {
          "type": "string",
          "enum": [
            "running",
            "stopped",
            "unknown"
          ]
        }
      },
      "additionalProperties": false,
      "required": [
        "agent",
        "gateway",
        "relay"
      ]
    },
    "mutation_state": {
      "type": "string",
      "enum": [
        "idle",
        "running",
        "unknown"
      ]
    },
    "complete": {
      "type": "boolean"
    },
    "evidence_ref": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "orphan_resources": {
      "type": "boolean"
    }
  },
  "additionalProperties": false,
  "required": [
    "observation_id",
    "runtime_id",
    "state_version",
    "host_boot_id",
    "observed_at",
    "components",
    "mutation_state",
    "complete",
    "evidence_ref"
  ]
}
```

### Maintenance

```json
{
  "type": "object",
  "properties": {
    "mode": {
      "type": "string",
      "enum": [
        "normal",
        "frozen",
        "repair_only"
      ]
    },
    "maintenance_mode": {
      "type": "string"
    },
    "state_version": {
      "type": "integer"
    },
    "capacity_healthy": {
      "type": "boolean"
    },
    "recovery_required": {
      "type": "integer"
    },
    "security_pending": {
      "type": "integer"
    },
    "safety_sync_failures": {
      "type": "integer"
    }
  },
  "additionalProperties": true
}
```

### MaintenanceBody

```json
{
  "type": "object",
  "properties": {
    "mode": {
      "type": "string",
      "enum": [
        "normal",
        "frozen",
        "repair_only"
      ]
    },
    "state_version": {
      "type": "integer"
    }
  },
  "additionalProperties": false,
  "required": [
    "mode",
    "state_version"
  ]
}
```

### RecoveryBody

```json
{
  "type": "object",
  "properties": {
    "action": {
      "type": "string",
      "enum": [
        "continue",
        "cancel"
      ]
    }
  },
  "additionalProperties": false,
  "required": [
    "action"
  ]
}
```

### Department

```json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "name": {
      "type": "string"
    },
    "code": {
      "type": "string"
    },
    "parent_id": {
      "anyOf": [
        {
          "type": "string",
          "minLength": 1,
          "maxLength": 100,
          "pattern": "^[A-Za-z0-9_-]+$"
        },
        {
          "type": "null"
        }
      ]
    },
    "sort_order": {
      "type": "integer"
    },
    "updated_at": {
      "type": "string",
      "format": "date-time"
    },
    "children": {
      "type": "array",
      "items": {
        "$ref": "#/components/schemas/Department"
      }
    }
  },
  "additionalProperties": false,
  "required": [
    "id",
    "name",
    "code",
    "parent_id",
    "sort_order"
  ]
}
```

### DepartmentBody

```json
{
  "type": "object",
  "properties": {
    "name": {
      "type": "string"
    },
    "code": {
      "type": "string"
    },
    "parent_id": {
      "anyOf": [
        {
          "type": "string",
          "minLength": 1,
          "maxLength": 100,
          "pattern": "^[A-Za-z0-9_-]+$"
        },
        {
          "type": "null"
        }
      ]
    },
    "sort_order": {
      "type": "integer"
    }
  },
  "additionalProperties": false
}
```

### DepartmentTree

```json
{
  "type": "object",
  "properties": {
    "items": {
      "type": "array",
      "items": {
        "$ref": "#/components/schemas/Department"
      }
    },
    "total": {
      "type": "integer"
    },
    "page": {
      "type": "integer"
    },
    "page_size": {
      "type": "integer"
    }
  },
  "additionalProperties": false,
  "required": [
    "items",
    "total",
    "page",
    "page_size"
  ]
}
```

### UserSummary

```json
{
  "type": "object",
  "properties": {
    "users": {
      "type": "integer"
    },
    "enabled": {
      "type": "integer"
    },
    "disabled": {
      "type": "integer"
    },
    "departments": {
      "type": "integer"
    }
  },
  "additionalProperties": false,
  "required": [
    "users",
    "enabled",
    "disabled",
    "departments"
  ]
}
```

### ModelTestResult

```json
{
  "type": "object",
  "properties": {
    "ok": {
      "type": "boolean"
    },
    "message": {
      "type": "string"
    },
    "elapsed_ms": {
      "type": "integer"
    }
  },
  "additionalProperties": false,
  "required": [
    "ok",
    "message",
    "elapsed_ms"
  ]
}
```

### Run

```json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "session_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "status": {
      "type": "string",
      "enum": [
        "queued",
        "running",
        "cancelling",
        "reconciling",
        "completed",
        "failed",
        "cancelled"
      ]
    },
    "phase": {
      "type": "string"
    },
    "cancel_requested": {
      "type": "boolean"
    },
    "model_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "message_id": {
      "anyOf": [
        {
          "type": "string",
          "minLength": 1,
          "maxLength": 100,
          "pattern": "^[A-Za-z0-9_-]+$"
        },
        {
          "type": "null"
        }
      ]
    },
    "user_message_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "parent_run_id": {
      "anyOf": [
        {
          "type": "string",
          "minLength": 1,
          "maxLength": 100,
          "pattern": "^[A-Za-z0-9_-]+$"
        },
        {
          "type": "null"
        }
      ]
    },
    "created_at": {
      "type": "string",
      "format": "date-time"
    },
    "started_at": {
      "anyOf": [
        {
          "type": "string",
          "format": "date-time"
        },
        {
          "type": "null"
        }
      ]
    },
    "completed_at": {
      "anyOf": [
        {
          "type": "string",
          "format": "date-time"
        },
        {
          "type": "null"
        }
      ]
    },
    "updated_at": {
      "type": "string",
      "format": "date-time"
    },
    "error": {
      "anyOf": [
        {
          "type": "object",
          "properties": {
            "code": {
              "type": "string"
            },
            "message": {
              "type": "string"
            }
          },
          "additionalProperties": false
        },
        {
          "type": "null"
        }
      ]
    }
  },
  "additionalProperties": false,
  "required": [
    "id",
    "session_id",
    "status",
    "phase",
    "created_at"
  ]
}
```

### RunAccepted

```json
{
  "type": "object",
  "properties": {
    "accepted": {
      "const": true
    },
    "run_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "message_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    }
  },
  "additionalProperties": false,
  "required": [
    "accepted",
    "run_id",
    "message_id"
  ]
}
```

### RunEvent

```json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "sequence": {
      "type": "integer"
    },
    "step_type": {
      "type": "string"
    },
    "name": {
      "type": "string"
    },
    "status": {
      "type": "string"
    },
    "started_at": {
      "anyOf": [
        {
          "type": "string",
          "format": "date-time"
        },
        {
          "type": "null"
        }
      ]
    },
    "completed_at": {
      "anyOf": [
        {
          "type": "string",
          "format": "date-time"
        },
        {
          "type": "null"
        }
      ]
    },
    "elapsed_ms": {
      "anyOf": [
        {
          "type": "integer"
        },
        {
          "type": "null"
        }
      ]
    },
    "capability_id": {
      "anyOf": [
        {
          "type": "string",
          "minLength": 1,
          "maxLength": 100,
          "pattern": "^[A-Za-z0-9_-]+$"
        },
        {
          "type": "null"
        }
      ]
    },
    "input_summary": {
      "type": "string"
    },
    "output_summary": {
      "type": "string"
    },
    "record_count": {
      "type": "integer"
    },
    "evidence_refs": {
      "type": "array",
      "items": {
        "type": "string"
      }
    },
    "error_message": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    }
  },
  "additionalProperties": false,
  "required": [
    "id",
    "sequence",
    "step_type",
    "name",
    "status"
  ]
}
```

### RunEvidence

```json
{
  "type": "object",
  "properties": {
    "presentation": {
      "$ref": "#/components/schemas/ScenarioPresentation"
    },
    "summary_check": {
      "type": "string"
    },
    "verified_summary": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "fact_id": {
            "type": "string"
          },
          "statement": {
            "type": "string"
          },
          "source_ids": {
            "type": "array",
            "items": {
              "type": "string"
            }
          }
        },
        "additionalProperties": false
      }
    },
    "schema_version": {
      "const": "1"
    },
    "status": {
      "enum": [
        "pending",
        "empty",
        "partial",
        "complete",
        "unavailable"
      ]
    },
    "turn_id": {
      "type": "string"
    },
    "notice": {
      "type": "string"
    },
    "scenario": {
      "anyOf": [
        {
          "type": "object",
          "properties": {
            "title": {
              "type": "string"
            },
            "scenario_id": {
              "type": "string"
            },
            "subject_ref": {
              "type": "string"
            },
            "snapshot_id": {
              "type": "string"
            },
            "records_snapshot_id": {
              "type": "string"
            },
            "rule_version": {
              "type": "string"
            },
            "timezone": {
              "type": "string"
            },
            "night_window": {
              "type": "string"
            },
            "case_window": {
              "type": "array",
              "items": {
                "type": "string"
              }
            }
          },
          "additionalProperties": false
        },
        {
          "type": "null"
        }
      ]
    },
    "steps": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "label": {
            "type": "string"
          },
          "status": {
            "type": "string",
            "enum": [
              "pending",
              "running",
              "completed",
              "error"
            ]
          }
        },
        "additionalProperties": false,
        "required": [
          "label",
          "status"
        ]
      }
    },
    "cards": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "id": {
            "type": "string"
          },
          "title": {
            "type": "string"
          },
          "description": {
            "type": "string"
          },
          "time": {
            "type": "string"
          },
          "source_ids": {
            "type": "array",
            "items": {
              "type": "string"
            }
          },
          "fields": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "label": {
                  "type": "string"
                },
                "value": {
                  "type": "string"
                }
              },
              "additionalProperties": false,
              "required": [
                "label",
                "value"
              ]
            }
          },
          "message_id": {
            "type": "string"
          },
          "snapshot_id": {
            "type": "string"
          }
        },
        "additionalProperties": false
      }
    },
    "missing": {
      "type": "array",
      "items": {
        "type": "string"
      }
    },
    "summary": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "label": {
            "type": "string"
          },
          "count": {
            "type": "integer"
          },
          "dates": {
            "type": "array",
            "items": {
              "type": "string"
            }
          },
          "night_count": {
            "type": "integer"
          }
        },
        "additionalProperties": false
      }
    },
    "run_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    }
  },
  "additionalProperties": false,
  "required": [
    "run_id",
    "status",
    "cards",
    "summary"
  ]
}
```

### AnalysisResult

```json
{
  "type": "object",
  "properties": {
    "schema": {
      "const": "peixian.analysis-result"
    },
    "version": {
      "const": "1.0"
    },
    "run_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "generated_at": {
      "type": "string",
      "format": "date-time"
    },
    "intro": {
      "type": "string"
    },
    "process": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "id": {
            "type": "string"
          },
          "title": {
            "type": "string"
          },
          "detail": {
            "type": "string"
          },
          "status": {
            "enum": [
              "pending",
              "running",
              "completed",
              "failed"
            ]
          },
          "time": {
            "type": "string"
          }
        },
        "additionalProperties": false
      }
    },
    "subjects": {
      "type": "array",
      "items": {
        "type": "object"
      }
    },
    "conclusions": {
      "type": "array",
      "items": {
        "type": "string"
      }
    },
    "evidence": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "type": {
            "type": "string"
          },
          "title": {
            "type": "string"
          },
          "value": {
            "type": [
              "string",
              "integer"
            ]
          },
          "unit": {
            "type": "string"
          },
          "summary": {
            "type": "string"
          },
          "items": {
            "type": "array",
            "items": {
              "type": "string"
            }
          },
          "clue_id": {
            "type": "string"
          }
        },
        "additionalProperties": false
      }
    },
    "clues": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "id": {
            "type": "string"
          },
          "type": {
            "type": "string"
          },
          "title": {
            "type": "string"
          },
          "headline": {
            "type": "string"
          },
          "summary": {
            "type": "string"
          },
          "discoveries": {
            "type": "array",
            "items": {
              "type": "string"
            }
          },
          "evidence": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "type": {
                  "type": "string"
                },
                "label": {
                  "type": "string"
                },
                "content": {
                  "type": "string"
                },
                "source_ids": {
                  "type": "array",
                  "items": {
                    "type": "string"
                  }
                }
              },
              "additionalProperties": false
            }
          }
        },
        "additionalProperties": false
      }
    },
    "next_steps": {
      "type": "string"
    },
    "conclusion_sources": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "text": {
            "type": "string"
          },
          "clue_id": {
            "type": "string"
          },
          "source_ids": {
            "type": "array",
            "items": {
              "type": "string"
            }
          }
        },
        "additionalProperties": false
      }
    },
    "source_metadata": {
      "type": "object",
      "additionalProperties": true
    },
    "presentation_version": {
      "type": "string"
    }
  },
  "additionalProperties": false,
  "required": [
    "schema",
    "version",
    "run_id",
    "process",
    "subjects",
    "conclusions",
    "evidence",
    "clues"
  ]
}
```

### Capability

```json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "kind": {
      "enum": [
        "personal_skill",
        "plugin",
        "official_skill"
      ]
    },
    "name": {
      "type": "string"
    },
    "description": {
      "type": "string"
    },
    "version": {
      "anyOf": [
        {},
        {
          "type": "null"
        }
      ]
    },
    "category": {
      "type": "string"
    },
    "recommended": {
      "type": "boolean"
    },
    "enabled": {
      "type": "boolean"
    },
    "owned": {
      "type": "boolean"
    },
    "scope": {
      "type": "string"
    },
    "available": {
      "type": "boolean"
    },
    "unavailable_reason": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "dependency_ids": {
      "type": "array",
      "items": {
        "type": "string",
        "minLength": 1,
        "maxLength": 100,
        "pattern": "^[A-Za-z0-9_-]+$"
      }
    }
  },
  "additionalProperties": false,
  "required": [
    "id",
    "kind",
    "name",
    "available"
  ]
}
```

### Invocation

```json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "run_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "session_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "username": {
      "type": "string"
    },
    "display_name": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "department_name": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "model_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "model_name": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ]
    },
    "status": {
      "type": "string"
    },
    "query_summary": {
      "type": "string"
    },
    "created_at": {
      "type": "string",
      "format": "date-time"
    },
    "duration_ms": {
      "anyOf": [
        {
          "type": "integer"
        },
        {
          "type": "null"
        }
      ]
    },
    "record_count": {
      "type": "integer"
    },
    "skill_ids": {
      "type": "array",
      "items": {
        "type": "string",
        "minLength": 1,
        "maxLength": 100,
        "pattern": "^[A-Za-z0-9_-]+$"
      }
    },
    "plugin_ids": {
      "type": "array",
      "items": {
        "type": "string",
        "minLength": 1,
        "maxLength": 100,
        "pattern": "^[A-Za-z0-9_-]+$"
      }
    },
    "actual_plugin_ids": {
      "type": "array",
      "items": {
        "type": "string",
        "minLength": 1,
        "maxLength": 100,
        "pattern": "^[A-Za-z0-9_-]+$"
      }
    },
    "steps": {
      "type": "array",
      "items": {
        "$ref": "#/components/schemas/RunEvent"
      }
    }
  },
  "additionalProperties": false,
  "required": [
    "id",
    "run_id",
    "status",
    "query_summary",
    "created_at"
  ]
}
```

### RunPage

```json
{
  "type": "object",
  "properties": {
    "items": {
      "type": "array",
      "items": {
        "$ref": "#/components/schemas/Run"
      }
    },
    "total": {
      "type": "integer"
    },
    "page": {
      "type": "integer"
    },
    "page_size": {
      "type": "integer"
    }
  },
  "additionalProperties": false,
  "required": [
    "items",
    "total",
    "page",
    "page_size"
  ]
}
```

### RunEventPage

```json
{
  "type": "object",
  "properties": {
    "items": {
      "type": "array",
      "items": {
        "$ref": "#/components/schemas/RunEvent"
      }
    },
    "total": {
      "type": "integer"
    },
    "page": {
      "type": "integer"
    },
    "page_size": {
      "type": "integer"
    }
  },
  "additionalProperties": false,
  "required": [
    "items",
    "total",
    "page",
    "page_size"
  ]
}
```

### CapabilityPage

```json
{
  "type": "object",
  "properties": {
    "items": {
      "type": "array",
      "items": {
        "$ref": "#/components/schemas/Capability"
      }
    },
    "total": {
      "type": "integer"
    },
    "page": {
      "type": "integer"
    },
    "page_size": {
      "type": "integer"
    }
  },
  "additionalProperties": false,
  "required": [
    "items",
    "total",
    "page",
    "page_size"
  ]
}
```

### InvocationPage

```json
{
  "type": "object",
  "properties": {
    "items": {
      "type": "array",
      "items": {
        "$ref": "#/components/schemas/Invocation"
      }
    },
    "total": {
      "type": "integer"
    },
    "page": {
      "type": "integer"
    },
    "page_size": {
      "type": "integer"
    }
  },
  "additionalProperties": false,
  "required": [
    "items",
    "total",
    "page",
    "page_size"
  ]
}
```

### RerunBody

```json
{
  "type": "object",
  "properties": {
    "text": {
      "type": "string",
      "minLength": 1,
      "maxLength": 32000,
      "pattern": "\\S",
      "description": "非空白问题。文字、选中技能内容与文件文本合计还受 18000 UTF-8 字节预算限制。"
    },
    "model_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$",
      "description": "GET /models 返回的已授权平台模型 ID；省略时选择授权列表中的默认模型。"
    },
    "skill_ids": {
      "type": "array",
      "items": {
        "type": "string",
        "minLength": 1,
        "maxLength": 100,
        "pattern": "^[A-Za-z0-9_-]+$"
      },
      "maxItems": 5
    },
    "file_ids": {
      "type": "array",
      "items": {
        "type": "string",
        "minLength": 1,
        "maxLength": 100,
        "pattern": "^[A-Za-z0-9_-]+$"
      },
      "maxItems": 5,
      "description": "本账号已解析为 ready 且未截断的上传文件 ID；partial 或 truncated=true 返回 413，要求拆分后重新上传；不接受文件路径或 URL。"
    },
    "client_request_id": {
      "type": "string",
      "format": "uuid",
      "description": "新客户端必须发送。旧客户端省略时服务端生成，不具备客户端重试去重保证。"
    },
    "plugin_ids": {
      "type": "array",
      "items": {
        "type": "string",
        "minLength": 1,
        "maxLength": 100,
        "pattern": "^[A-Za-z0-9_-]+$"
      },
      "maxItems": 5
    },
    "mode": {
      "enum": [
        "standard"
      ]
    }
  },
  "additionalProperties": false,
  "required": [
    "client_request_id"
  ]
}
```

### SkillDraftBody

```json
{
  "type": "object",
  "properties": {
    "name": {
      "type": "string"
    },
    "description": {
      "type": "string"
    },
    "content": {
      "type": "string"
    },
    "dependency_ids": {
      "type": "array",
      "items": {
        "type": "string",
        "minLength": 1,
        "maxLength": 100,
        "pattern": "^[A-Za-z0-9_-]+$"
      }
    },
    "input_schema": {
      "type": "object",
      "additionalProperties": true
    },
    "default_rules": {
      "type": "array",
      "items": {
        "type": "string"
      }
    }
  },
  "additionalProperties": false
}
```

### SkillDraft

```json
{
  "type": "object",
  "properties": {
    "name": {
      "type": "string"
    },
    "description": {
      "type": "string"
    },
    "content": {
      "type": "string"
    },
    "dependency_ids": {
      "type": "array",
      "items": {
        "type": "string",
        "minLength": 1,
        "maxLength": 100,
        "pattern": "^[A-Za-z0-9_-]+$"
      }
    },
    "input_schema": {
      "type": "object",
      "additionalProperties": true
    },
    "default_rules": {
      "type": "array",
      "items": {
        "type": "string"
      }
    },
    "id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "session_id": {
      "anyOf": [
        {
          "type": "string",
          "minLength": 1,
          "maxLength": 100,
          "pattern": "^[A-Za-z0-9_-]+$"
        },
        {
          "type": "null"
        }
      ]
    },
    "source_type": {
      "type": "string"
    },
    "status": {
      "enum": [
        "preparing",
        "generating",
        "ready",
        "needs_review",
        "failed",
        "saved"
      ]
    },
    "run_id": {
      "anyOf": [
        {
          "type": "string",
          "minLength": 1,
          "maxLength": 100,
          "pattern": "^[A-Za-z0-9_-]+$"
        },
        {
          "type": "null"
        }
      ]
    },
    "saved_skill_id": {
      "anyOf": [
        {
          "type": "string",
          "minLength": 1,
          "maxLength": 100,
          "pattern": "^[A-Za-z0-9_-]+$"
        },
        {
          "type": "null"
        }
      ]
    },
    "scope": {
      "const": "personal"
    },
    "error": {
      "anyOf": [
        {
          "type": "object",
          "properties": {
            "code": {
              "type": "string"
            },
            "message": {
              "type": "string"
            }
          },
          "additionalProperties": false
        },
        {
          "type": "null"
        }
      ]
    },
    "created_at": {
      "type": "string",
      "format": "date-time"
    },
    "updated_at": {
      "type": "string",
      "format": "date-time"
    }
  },
  "additionalProperties": false,
  "required": [
    "id",
    "status",
    "source_type",
    "scope",
    "created_at",
    "updated_at"
  ]
}
```

### DraftGenerateBody

```json
{
  "type": "object",
  "properties": {
    "requirement": {
      "type": "string"
    },
    "session_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "model_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "client_request_id": {
      "type": "string",
      "format": "uuid"
    }
  },
  "additionalProperties": false,
  "required": [
    "client_request_id"
  ]
}
```

### DraftTestBody

```json
{
  "type": "object",
  "properties": {
    "mode": {
      "enum": [
        "validation",
        "model"
      ]
    },
    "text": {
      "type": "string"
    },
    "model_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "client_request_id": {
      "type": "string",
      "format": "uuid"
    }
  },
  "additionalProperties": false
}
```

### DraftTestResult

```json
{
  "type": "object",
  "properties": {
    "mode": {
      "enum": [
        "validation",
        "model"
      ]
    },
    "ok": {
      "type": "boolean"
    },
    "field_errors": {
      "type": "object",
      "additionalProperties": {
        "type": "string"
      }
    },
    "model_executed": {
      "anyOf": [
        {
          "type": "boolean"
        },
        {
          "type": "null"
        }
      ]
    },
    "accepted": {
      "type": "boolean"
    },
    "session_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "run_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "message_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    }
  },
  "additionalProperties": false,
  "required": [
    "mode",
    "model_executed"
  ]
}
```

### EmptyBody

```json
{
  "type": "object",
  "properties": {},
  "additionalProperties": false
}
```

### DraftSaveResult

```json
{
  "type": "object",
  "properties": {
    "skill_id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100,
      "pattern": "^[A-Za-z0-9_-]+$"
    },
    "scope": {
      "const": "personal"
    },
    "enabled": {
      "type": "boolean"
    },
    "job": {
      "$ref": "#/components/schemas/Job"
    },
    "already_saved": {
      "type": "boolean"
    }
  },
  "additionalProperties": false,
  "required": [
    "skill_id",
    "scope",
    "already_saved"
  ]
}
```
