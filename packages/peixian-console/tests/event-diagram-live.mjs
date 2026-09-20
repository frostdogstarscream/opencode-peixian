import assert from 'node:assert/strict'
import fs from 'node:fs'
import {chromium} from 'playwright'
const root=process.env.PEIXIAN_DEPLOY_ROOT ?? '/srv/peixian-alignment-20260917'
const out=process.env.PEIXIAN_ACCEPTANCE_DIR ?? root+'/diagram-v151-release-20260920'
const credentials=JSON.parse(fs.readFileSync(root+'/private.json','utf8')).accounts
const runs=JSON.parse(fs.readFileSync(out+'/smoke-results.json','utf8'))
const browser=await chromium.launch({headless:true,args:['--host-resolver-rules=MAP 36.134.45.38 127.0.0.1','--no-proxy-server']})
const report=[]
const ready=runs.filter(x=>x.diagram_status==='ready')
assert.ok(ready.length>0,'No successful diagram Run is available; live acceptance cannot pass')
try {
 for(const run of ready)for(const width of [1366,1920,390]) {
  assert.equal(run.diagram_status,'ready')
  const context=await browser.newContext({ignoreHTTPSErrors:true,viewport:{width,height:1000},acceptDownloads:true})
  const page=await context.newPage(), errors=[]
  page.on('pageerror',e=>errors.push(e.message))
  await page.goto('https://36.134.45.38:19460/')
  await page.getByRole('textbox',{name:'账号',exact:true}).fill(run.account)
  await page.locator('input[autocomplete="current-password"]').fill(credentials[run.account].password)
  await page.getByRole('button',{name:/登\s*录/}).click()
  await page.getByRole('button',{name:'退出登录',exact:true}).waitFor({timeout:30000})
  if(width===390)await page.getByRole('button',{name:'显示对话记录',exact:true}).click()
  const title='事件脉络图验收 · '+(run.account==='alignment-a'?'涉赌':'盗窃')
  await page.getByText(title,{exact:true}).first().click()
  await page.locator('.event-diagram-svg svg').first().waitFor({timeout:30000})
  const graph=page.locator('.event-diagram').first()
  assert.ok((await graph.innerText()).includes('虚线箭头仅表示时间先后'))
  await graph.locator('.event-diagram-scroll').scrollIntoViewIfNeeded()
  await graph.getByRole('button',{name:'查看大图',exact:true}).scrollIntoViewIfNeeded()
  await page.screenshot({path:out+'/viewport-'+run.account+'-'+width+'.png'})
  await graph.getByRole('button',{name:'查看大图',exact:true}).click()
  const modal=page.locator('dialog.event-diagram-dialog')
  await modal.waitFor({state:'visible'})
  await page.screenshot({path:out+'/modal-'+run.account+'-'+width+'.png'})
  await page.keyboard.press('Escape')
  await modal.waitFor({state:'detached'})
  await assert.doesNotReject(()=>graph.getByRole('button',{name:'查看大图',exact:true}).evaluate(el=>{if(document.activeElement!==el)throw new Error('Focus was not restored')}))
  let pagination=false
  if(await graph.getByRole('button',{name:'下一页',exact:true}).count()){
   await graph.getByRole('button',{name:'下一页',exact:true}).click()
   await graph.locator('svg').first().waitFor()
   assert.ok((await graph.innerText()).includes('第 2/'))
   pagination=true
   await graph.getByRole('button',{name:'上一页',exact:true}).click()
   await graph.locator('svg').first().waitFor()
  }
  for(const format of ['SVG','PNG']){
   const pending=page.waitForEvent('download')
   await graph.getByRole('button',{name:'导出 '+format,exact:true}).click()
   const download=await pending
   assert.equal(await download.failure(),null)
   await download.saveAs(out+'/live-'+run.account+'-'+width+'.'+format.toLowerCase())
  }
  await graph.locator('.event-diagram-list button').first().click()
  await page.getByRole('dialog',{name:'线索详情',exact:true}).waitFor()
  await page.keyboard.press('Escape')
  assert.deepEqual(errors,[])
  report.push({account:run.account,width,real_api:true,graph:true,pagination,exports:true,source_drawer:true,large_view:true,focus_restore:true,page_errors:0})
  await page.getByRole('button',{name:'退出登录',exact:true}).click()
  await context.close()
 }
 fs.writeFileSync(out+'/live-browser.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report))
}finally{await browser.close()}
