// UI contract regression with explicit synthetic Gateway/file responses.
// Actual parser and account ownership are covered separately by repository Python tests.
import assert from "node:assert/strict"
import { chromium } from "playwright"
const browser=await chromium.launch({headless:true})
const cases=[]
try {
 const context=await browser.newContext(), page=await context.newPage(), writes=[], errors=[]
 let uploaded=false, fail=false, state="ready", parserReads=0
 const file={id:"file-a",name:"合成资料.txt",size:45,created:1750000000,status:"ready"}
 page.on("pageerror",e=>errors.push(e.message))
 await page.route("**/api/console/v1/**",async route=>{
  const request=route.request(),path=new URL(request.url()).pathname.split("/api/console/v1")[1]
  let body={items:[]},status=200
  if(request.method()!=="GET") {
   assert.ok(request.headers()["idempotency-key"])
   assert.equal(request.headers()["x-csrf-token"],"synthetic-csrf")
   if(path==="/files") {
    assert.ok(request.headers()["content-type"].startsWith("multipart/form-data"))
    if(fail) return route.fulfill({status:413,json:{message:"合成上传配额不足",code:"quota"}})
    uploaded=true;parserReads=0;body={...file,status:"parsing"}
   } else {
    const data=request.postDataJSON();writes.push({path,data})
    if(path==="/sessions") body={id:"session-a",title:"引用验收"}
    else if(path==="/sessions/session-a/messages") body={accepted:true}
    else return route.fulfill({status:404,json:{message:"unexpected write"}})
   }
  } else if(path==="/me") body={user:{id:"user-a",username:"合成验收",role:"user",runtime:{status:state,gate_policy:state==="ready"?"open":"closed",interaction:{can_observe:true,can_continue:true,can_submit_new:state==="ready"}}},capabilities:["business.use"],csrf_token:"synthetic-csrf"}
  else if(path==="/platform") body={name:"沛警智枢"}
  else if(path==="/models") body={items:[{id:"model-a",name:"合成模型"}]}
  else if(path==="/skills") body={items:[{id:"skill-a",name:"合成方法",content:"使用资料",enabled:true,version:1}]}
  else if(path==="/plugins") body={items:[{id:"plugin-a",name:"合成工具",version:"1",installed:{version:"1",enabled:true,state:"active"}}]}
  else if(path==="/files") body={items:uploaded?[{...file,status:++parserReads<3?"parsing":"ready"}]:[]}
  else if(path==="/files/file-a/preview") { await new Promise(resolve=>setTimeout(resolve,6000)); body={status:"ready",chunks:[{text:"合成内容，待核实",source:{line_start:1,line_end:2}}]} }
  else if(path==="/events") return route.fulfill({contentType:"text/event-stream",body:": fixture\n\n"})
  else if(!["/sessions","/sessions/session-a/messages","/results","/permissions","/questions"].includes(path)) return route.fulfill({status:404,json:{message:"unexpected read "+path}})
  await route.fulfill({status,json:body})
 })
 await page.goto(process.env.ALIGNMENT_URL||"http://127.0.0.1:15178")
 const input=page.getByRole("textbox",{name:"输入消息"})
 await input.fill("请按照方法分析附件")
 // Use actual rendered accessible names after inspecting the composer.
 await page.locator(".composer-tools").getByRole("button").filter({hasText:"文件"}).click()
 await page.getByRole("button",{name:"上传与管理文件",exact:true}).click()
 await page.getByLabel("选择上传文件").setInputFiles({name:file.name,mimeType:"text/plain",buffer:Buffer.from("合成内容，待核实")})
 await page.getByRole("button",{name:"用于对话",exact:true}).waitFor()
 await page.waitForFunction(()=>[...document.querySelectorAll("button")].some(x=>x.textContent.trim()==="用于对话"&&!x.disabled))
 await page.getByRole("button",{name:"预览",exact:true}).click()
 await page.getByText("第 1–2 行",{exact:false}).waitFor()
 await page.keyboard.press("Escape")
 assert.equal(await page.getByRole("dialog").count(),1)
 await page.getByRole("button",{name:"用于对话",exact:true}).click()
 assert.equal(await input.inputValue(),"请按照方法分析附件")
 await page.locator(".related-capabilities-list").getByRole("button").filter({hasText:"合成方法"}).click()
 await page.getByRole("button",{name:"发送",exact:true}).click()
 await page.waitForFunction(()=>document.querySelector("textarea")?.value==="")
 const submitted=writes.find(x=>x.path.endsWith("/messages"))
 assert.deepEqual(submitted.data.file_ids,["file-a"])
 assert.deepEqual(submitted.data.skill_ids,["skill-a"])
 assert.ok(!("plugin_ids" in submitted.data))
 cases.push("multipart upload, parser status polling, slow source preview across identity refresh, draft preservation, exact file/skill message IDs; no invented plugin_ids")
 await page.locator(".composer-tools").getByRole("button").filter({hasText:"文件"}).click()
 await page.getByRole("button",{name:"上传与管理文件",exact:true}).click()
 fail=true
 await page.getByLabel("选择上传文件").setInputFiles({name:"错误.txt",mimeType:"text/plain",buffer:Buffer.from("failed")})
 await page.getByText("已上传 0 个文件。合成上传配额不足",{exact:true}).waitFor()
 await page.waitForTimeout(1200)
 assert.ok(await page.getByText("已上传 0 个文件。合成上传配额不足",{exact:true}).isVisible())
 for(const width of [1366,1920,390]) {
  await page.setViewportSize({width,height:900})
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2),false)
  await page.screenshot({path:`output/playwright/step2-files-${width}.png`,fullPage:true})
 }
 cases.push("failed upload remains visible after list refresh; file manager layouts at 1366/1920/390")
 assert.deepEqual(errors,[])
 console.log(JSON.stringify({passed:true,cases,evidence:"synthetic HTTP contract, not real Agent/model"},null,2))
 await context.close()
} finally {await browser.close()}
