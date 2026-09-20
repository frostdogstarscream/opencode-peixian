import assert from "node:assert/strict"
import fs from "node:fs"
import path from "node:path"
import http from "node:http"
import { chromium } from "playwright"
const dist=path.resolve("dist"), out=path.resolve("../../output/playwright/scenario-context")
fs.mkdirSync(out,{recursive:true})
const server=http.createServer((req,res)=>{
 const relative=decodeURIComponent((req.url??"/").split("?")[0])
 const file=path.resolve(dist,"."+relative)
 if(!file.startsWith(dist+path.sep)&&file!==dist){res.writeHead(404);res.end();return}
 const target=fs.existsSync(file)&&fs.statSync(file).isFile()?file:path.join(dist,"index.html")
 res.setHeader("Content-Type",target.endsWith(".js")?"text/javascript":target.endsWith(".css")?"text/css":target.endsWith(".svg")?"image/svg+xml":target.endsWith(".webp")?"image/webp":"text/html")
 res.end(fs.readFileSync(target))
})
await new Promise(resolve=>server.listen(0,"127.0.0.1",resolve))
const url="http://127.0.0.1:"+server.address().port
const browser=await chromium.launch({headless:true,args:["--no-proxy-server"]})
const report=[]
try {
 for(const width of [1366,1920,390]) {
  let cleared=false
  const context=await browser.newContext({viewport:{width,height:900}}), page=await context.newPage(), errors=[]
  page.on("pageerror",error=>errors.push(error.message))
  await page.route("**/api/console/v1/**",async route=>{
   const endpoint=new URL(route.request().url()).pathname.replace("/api/console/v1","")
   let data={items:[]}
   if(endpoint==="/me")data={user:{id:"demo-user",username:"demo",role:"user",must_change_password:false,runtime:{status:"ready",ready:true,gate_policy:"open",interaction:{can_submit_new:true,can_observe:true,can_continue:true}}},capabilities:["business.use"],csrf_token:"synthetic"}
   if(endpoint==="/models")data={items:[{id:"demo-model",name:"测试模型",is_default:true}]}
   if(endpoint==="/sessions")data={items:[{id:"ses_demo",title:"合成会话",time:{updated:1}}]}
   if(endpoint.endsWith("/runs"))data={items:[{id:"run_demo",session_id:"ses_demo",status:"completed",phase:"completed",created_at:"2026-09-20T00:00:00Z"}]}
   if(endpoint.endsWith("/evidence"))data={run_id:"run_demo",status:"empty",cards:[],summary:[]}
   if(endpoint.endsWith("/context")) {
    if(route.request().method()==="DELETE")cleared=true
    data={scenario_id:cleared?null:"DEMO-CASE-GAMBLING",name:cleared?null:"涉赌案件资料整理",source:cleared?"none":"inherited",generation:cleared?"synthetic-reset":null}
   }
   if(endpoint==="/events"){await route.fulfill({status:503,headers:{"Retry-After":"60"},body:""});return}
   await route.fulfill({json:data})
  })
  await page.goto(url)
  if(width===390) await page.getByRole("button",{name:"显示对话记录",exact:true}).click()
  await page.getByText("合成会话",{exact:true}).first().waitFor()
  await page.getByText("合成会话",{exact:true}).first().click()
  await page.getByRole("button",{name:"清除当前场景",exact:true}).waitFor()
  const text=await page.locator("body").innerText()
  assert.ok(text.includes("涉赌案件资料整理"));assert.ok(text.includes("暂无有效资料"));assert.ok(!text.includes("completed"))
  await page.screenshot({path:path.join(out,width+"-context.png"),fullPage:true})
  await page.getByRole("button",{name:"清除当前场景",exact:true}).click()
  await page.waitForTimeout(300)

  assert.ok(cleared)
  assert.equal(await page.getByRole("button",{name:"清除当前场景",exact:true}).count(),0)
  await page.reload();if(width===390) await page.getByRole("button",{name:"显示对话记录",exact:true}).click();await page.getByText("合成会话",{exact:true}).first().click()
  await page.getByText("暂无有效资料",{exact:false}).waitFor()
  assert.equal(await page.getByRole("button",{name:"清除当前场景",exact:true}).count(),0)
  assert.deepEqual(errors,[])
  report.push({width,scene_visible:true,clear_and_refresh:true,page_errors:0})
  await context.close()
 }
 fs.writeFileSync(path.join(out,"report.json"),JSON.stringify({scope:"isolated frontend with synthetic HTTP responses",real_model_requests:0,report},null,2))
 console.log(JSON.stringify(report))
} finally {await browser.close();server.close()}
