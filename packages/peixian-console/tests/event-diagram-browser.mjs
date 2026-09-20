import assert from "node:assert/strict"
import fs from "node:fs"
import path from "node:path"
import http from "node:http"
import { chromium } from "playwright"
const dist=path.resolve("dist"), out=path.resolve("../../output/playwright/event-diagram")
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
const fixtures=JSON.parse(fs.readFileSync(process.env.DIAGRAM_FIXTURES??"tests/fixtures/event-diagrams.json","utf8"))
const report=[]
try {
 for(const width of [1366,1920,390])for(const scenario of Object.keys(fixtures)) {
  const context=await browser.newContext({viewport:{width,height:900},acceptDownloads:true}),page=await context.newPage(),errors=[]
  page.on("pageerror",error=>errors.push(error.message))
  await page.route("**/api/console/v1/**",async route=>{
   const endpoint=new URL(route.request().url()).pathname.replace("/api/console/v1","")
   let data={items:[]}
   if(endpoint==="/me")data={user:{id:"demo-user",username:"demo",role:"user",must_change_password:false,runtime:{status:"ready",ready:true,gate_policy:"open",interaction:{can_submit_new:true,can_observe:true,can_continue:true}}},capabilities:["business.use"],csrf_token:"synthetic"}
   if(endpoint==="/sessions")data={items:[{id:"ses_demo",title:"图形测试",time:{updated:1}}]}
   if(endpoint.endsWith("/runs"))data={items:[{id:"run_demo",session_id:"ses_demo",status:"completed",phase:"completed",created_at:"2026-09-20T00:00:00Z"}]}
   if(endpoint.endsWith("/messages")){const view=fixtures[scenario].presentation;data={items:[{info:{id:"msg_demo",role:"assistant",time:{created:1}},parts:[{type:"analysis_result",data:{...view,schema:"peixian.analysis-result",version:"1.0",run_id:"run_demo",subjects:[],conclusions:view.conclusions.map(x=>x.text),conclusion_sources:view.conclusions}}]}]}}
   if(endpoint.endsWith("/evidence"))data=fixtures[scenario]
   if(endpoint.endsWith("/context"))data={scenario_id:null,name:null,source:"none",generation:null}
   if(endpoint==="/events"){await route.fulfill({status:503,headers:{"Retry-After":"60"},body:""});return}
   await route.fulfill({json:data})
  })
  // All browser resources are local. Fail requests to any other origin.
  await page.route(/^https?:\/\//,async route=>{if(new URL(route.request().url()).origin!==url){await route.abort();return}await route.fallback()})
  await page.goto(url)
  if(width===390)await page.getByRole("button",{name:"显示对话记录",exact:true}).click()
  await page.getByText("图形测试",{exact:true}).first().click()
  try {await page.locator('.event-diagram-svg svg').first().waitFor({timeout:15000})} catch(e){console.log((await page.locator('body').innerText()).slice(-6000));console.log(errors);throw e}
  const svgText=await page.locator('.event-diagram-svg svg').first().textContent();assert.ok(svgText.includes('2026-09-14'));assert.ok(svgText.includes('晚间'));assert.ok(!svgText.includes('#58;'));const before=await page.locator('.event-diagram').innerText();assert.ok(before.includes('虚线箭头仅表示时间先后'));assert.ok(!before.includes('时间不详推断'))
  await page.locator('.event-diagram-scroll').first().scrollIntoViewIfNeeded();await page.locator('.event-diagram-scroll').first().screenshot({path:path.join(out,width+'-'+scenario+'-light.png')})
  await page.getByRole('button',{name:'放大事件图',exact:true}).click();assert.ok((await page.locator('.event-diagram-toolbar').innerText()).includes('125%'))
  await page.getByRole('button',{name:'查看大图',exact:true}).click();await page.getByRole('button',{name:'关闭大图',exact:true}).waitFor();await page.keyboard.press('Escape');await page.getByRole('button',{name:'关闭大图',exact:true}).waitFor({state:'detached'})
  await page.locator('.event-diagram-list button').first().click();await page.getByRole('dialog',{name:'线索详情',exact:true}).waitFor();await page.keyboard.press('Escape')
  for(const format of ['SVG','PNG']){const download=page.waitForEvent('download');await page.getByRole('button',{name:'导出 '+format,exact:true}).click();const value=await download;assert.equal(await value.failure(),null);await value.saveAs(path.join(out,width+'-'+scenario+'.'+format.toLowerCase()))}
  await page.evaluate(()=>document.documentElement.dataset.theme='dark');await page.waitForTimeout(600);await page.locator('.event-diagram-svg svg').first().waitFor();await page.locator('.event-diagram-scroll').first().scrollIntoViewIfNeeded();await page.locator('.event-diagram-scroll').first().screenshot({path:path.join(out,width+'-'+scenario+'-dark.png')})
  assert.deepEqual(errors,[]);report.push({width,scenario,render:true,zoom:true,drawer:true,escape:true,exports:['SVG','PNG'],page_errors:0})
  await context.close()
 }
 fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({scope:'isolated browser, deterministic canonical tool results',report},null,2));console.log(JSON.stringify(report))
}finally{await browser.close();server.close()}
