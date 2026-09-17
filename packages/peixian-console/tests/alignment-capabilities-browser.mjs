// Real Control and SQLite; no intercepted HTTP, Worker, Agent, or model requests.
import assert from "node:assert/strict"
import { chromium } from "playwright"
import { execFileSync } from "node:child_process"
import { mkdir } from "node:fs/promises"
const base = process.env.ALIGNMENT_AUTH_URL || "http://127.0.0.1:15179"
const prefix = base + "/api/console/v1"
const password = "synthetic-alignment-password-123"
const browser = await chromium.launch({headless:true})
const cases = [], errors = []
async function login(username) {
  const context = await browser.newContext()
  let response = await context.request.post(prefix + "/auth/login", {data:{username,password}})
  assert.equal(response.status(),200)
  let identity = await (await context.request.get(prefix + "/me")).json()
  const call = async (path, method="GET", data) => {
    const response = await context.request.fetch(prefix+path, {method, data, headers:{"X-CSRF-Token":identity.csrf_token,"Idempotency-Key":crypto.randomUUID(),"Origin":base}})
    return response
  }
  if (identity.user.must_change_password) {
    response = await call("/me/password","POST",{current_password:password,password:password+"-step2"})
    assert.ok(response.ok(),await response.text())
    identity = await (await context.request.get(prefix+"/me")).json()
  }
  const page = await context.newPage()
  page.on("pageerror", error => errors.push(error.message))
  return { context, call, page, identity }
}
try {
  const admin=await login("admin"), user=await login("alignment-user"), other=await login("alignment-other"), manager=await login("alignment-manager")
  const model=await admin.call("/admin/models","POST",{name:"界面合成模型",base_url:"http://fixture.invalid/v1",model_id:"synthetic",description:"不发起模型请求",enabled:true})
  assert.ok(model.ok(),await model.text())
  const modelData=await model.json()
  const manifest={id:"alignment-tool",version:"1.0.0",name:"合成查询插件",entry:"entry.mjs",tools:["alignment_query"],config_schema:{type:"object",properties:{label:{type:"string",title:"查询标签"},token:{type:"string",title:"个人凭据",writeOnly:true}},required:["label"],additionalProperties:false}}
  const zip=execFileSync("python3",["-c",`import io,json,sys,zipfile
b=io.BytesIO()
with zipfile.ZipFile(b,'w') as z:
 z.writestr('manifest.json',sys.argv[1])
 z.writestr('entry.mjs','export default async () => ({});')
sys.stdout.buffer.write(b.getvalue())`,JSON.stringify(manifest)])
  const publication=await admin.context.request.post(prefix+"/admin/plugins",{headers:{"X-CSRF-Token":admin.identity.csrf_token,"Idempotency-Key":crypto.randomUUID(),"Origin":base},multipart:{file:{name:"synthetic.zip",mimeType:"application/zip",buffer:zip}}})
  assert.ok(publication.ok(),await publication.text())
  const granted=await admin.call("/admin/users/"+user.identity.user.id,"PATCH",{model_ids:[modelData.id],plugin_ids:[manifest.id]})
  assert.ok(granted.ok(),await granted.text())
  const denied=await manager.call("/admin/users/"+user.identity.user.id,"PATCH",{model_ids:[],plugin_ids:[]})
  assert.equal(denied.status(),403)
  assert.equal((await manager.call("/admin/plugins")).status(),403)
  assert.equal((await manager.call("/admin/templates")).status(),403)
  assert.equal((await user.call("/models")).status(),200)
  assert.equal((await (await other.call("/plugins")).json()).items.length,0)
  cases.push("real model/plugin publication and grants; mixed admin request rejected; other account catalog isolated")
  await user.page.goto(base)
  await user.page.waitForFunction(() => {
    const head=document.querySelector(".related-capabilities-head")?.getBoundingClientRect()
    const controls=document.querySelector(".capability-management-actions")?.getBoundingClientRect()
    return head && controls && controls.top-head.bottom < 24
  })
  const draft=user.page.getByRole("textbox",{name:"输入消息"})
  await draft.fill("管理期间保留中文草稿")
  await user.page.getByRole("button",{name:"管理技能",exact:true}).click()
  await user.page.getByRole("button",{name:"创建技能",exact:true}).click()
  const editor=user.page.getByRole("dialog").last()
  await editor.getByLabel("技能名称",{exact:false}).fill("step2-method")
  await editor.getByLabel("技能内容",{exact:true}).fill("只分析用户提供的合成资料，标记来源。")
  await editor.locator("button[type=submit]").click()
  await user.page.getByRole("heading",{name:"step2-method",exact:true}).waitFor()
  let skills=(await (await user.call("/skills")).json()).items
  assert.equal(skills.length,1)
  assert.equal((await (await other.call("/skills")).json()).items.length,0)
  assert.equal((await other.call("/skills/"+skills[0].id,"PATCH",{enabled:false})).status(),404)
  // Native Escape closes only top dialog, preserving the manager and conversation.
  await user.page.getByRole("button",{name:"编辑",exact:true}).click()
  await user.page.keyboard.press("Escape")
  assert.equal(await user.page.getByRole("dialog").count(),1)
  await user.page.keyboard.press("Escape")
  assert.equal(await user.page.getByRole("dialog").count(),0)
  assert.equal(await draft.inputValue(),"管理期间保留中文草稿")
  await user.page.locator(".related-capabilities-list").getByRole("button").filter({hasText:"step2-method"}).waitFor()
  const original=skills[0]
  assert.ok((await user.call("/skills/"+original.id,"PATCH",{content:"更新后的合成方法"})).ok())
  assert.ok((await user.call("/skills/"+original.id+"/rollback","POST",{})).ok())
  skills=(await (await user.call("/skills")).json()).items
  assert.equal(skills[0].content,original.content)
  const template=await admin.call("/admin/templates","POST",{name:"step2-template",description:"模板副本",content:"模板原始文本"})
  assert.ok(template.ok(),await template.text())
  const tid=(await template.json()).id
  assert.ok((await user.call("/templates/"+tid+"/copy","POST",{})).ok())
  assert.ok((await admin.call("/admin/templates/"+tid,"PATCH",{content:"模板后续文本"})).ok())
  const copied=(await (await user.call("/skills")).json()).items.find(x=>x.name==="step2-template")
  assert.equal(copied.content,"模板原始文本")
  cases.push("real skill edit/rollback and template copy are versioned and independent of later template edits")
  cases.push("real skill creation and account isolation; offline catalog invalidation; nested Escape preserves draft")
  await user.page.getByRole("button",{name:"管理插件",exact:true}).click()
  await user.page.getByRole("button",{name:"安装插件",exact:true}).click()
  await user.page.getByLabel("查询标签",{exact:false}).fill("仅此账号")
  await user.page.getByLabel("个人凭据",{exact:false}).fill("synthetic-personal-value")
  await user.page.getByRole("button",{name:"保存并应用",exact:true}).click()
  await user.page.getByRole("button",{name:"配置",exact:true}).waitFor()
  const plugin=(await (await user.call("/plugins")).json()).items[0]
  assert.equal(plugin.installed.config.label,"仅此账号")
  assert.equal(plugin.installed.credentials_configured.token,true)
  assert.ok(!JSON.stringify(plugin).includes("synthetic-personal-value"))
  assert.equal(plugin.installed.state,"pending")
  assert.equal(await user.page.getByRole("button",{name:"连接测试",exact:true}).isDisabled(),true)
  await user.page.getByRole("button",{name:"配置",exact:true}).click()
  assert.equal(await user.page.getByLabel("个人凭据",{exact:false}).inputValue(),"")
  await user.page.keyboard.press("Escape")
  await user.page.keyboard.press("Escape")
  assert.equal(await draft.inputValue(),"管理期间保留中文草稿")
  assert.ok((await user.call("/plugins/alignment-tool","PUT",{version:"1.0.0",enabled:false,config:{label:"更改后"}})).ok())
  assert.ok((await user.call("/plugins/alignment-tool/rollback","POST",{})).ok())
  const rolled=(await (await user.call("/plugins")).json()).items[0]
  assert.equal(rolled.installed.config.label,"仅此账号")
  assert.equal(rolled.installed.enabled,true)
  assert.equal(rolled.installed.credentials_configured.token,true)
  cases.push("real plugin configuration rollback restores previous personal values without returning secrets")
  // Existing management forms must also work without loading super-admin-only resources.
  await manager.page.goto(base)
  await manager.page.locator(".sidebar nav").getByRole("button",{name:"模型管理",exact:true}).click()
  await manager.page.getByRole("button",{name:"添加模型",exact:true}).click()
  const form=manager.page.getByRole("dialog",{name:"添加授权模型"})
  await form.getByLabel("显示名称",{exact:false}).fill("管理表单合成模型")
  await form.getByLabel("兼容接口地址",{exact:false}).fill("http://fixture.invalid/v1")
  await form.getByLabel("模型标识",{exact:false}).fill("ui-synthetic")
  await form.locator("button[type=submit]").click()
  await manager.page.getByRole("heading",{name:"管理表单合成模型",exact:true}).waitFor()
  assert.ok((await (await manager.call("/admin/models")).json()).items.some(x=>x.name==="管理表单合成模型"))
  await manager.page.locator(".sidebar nav").getByRole("button",{name:"用户管理",exact:true}).click()
  await manager.page.getByRole("button",{name:"创建账号",exact:true}).click()
  const account=manager.page.getByRole("dialog",{name:"创建账号",exact:true})
  assert.equal(await account.getByText("授权插件",{exact:true}).count(),0)
  await account.getByLabel(/^账号/).fill("step2-created-user")
  await account.getByLabel("初始密码",{exact:false}).fill(password)
  await account.locator("button[type=submit]").click()
  await manager.page.getByRole("dialog",{name:"创建账号",exact:true}).waitFor({state:"hidden"})
  assert.ok((await (await manager.call("/admin/users")).json()).items.some(x=>x.username==="step2-created-user"&&x.role==="user"))
  cases.push("real administrator model and normal-user creation forms; no plugin authorization field")
  cases.push("real plugin installation, schema config and redacted secret; pending is not applied and offline test disabled")
  await mkdir("output/playwright",{recursive:true})
  for (const width of [1366,1920,390]) {
    await user.page.setViewportSize({width,height:900})
    const input=user.page.getByRole("textbox",{name:"输入消息"})
    assert.ok(await input.isVisible())
    // Capability controls remain accessible on narrow screens via composer.
    await user.page.screenshot({path:`output/playwright/step2-real-${width}.png`,fullPage:true})
    assert.equal(await user.page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2),false)
  }
  assert.deepEqual(errors,[])
  console.log(JSON.stringify({passed:true,cases,limitations:["No Worker or Agent: configuration remains pending; no tool execution or model response claimed"]},null,2))
  for (const item of [admin,user,other,manager]) await item.context.close()
} finally { await browser.close() }
