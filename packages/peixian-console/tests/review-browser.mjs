// Real built Solid components, synthetic HTTP only. No running user deployment is contacted.
// NODE_PATH must resolve a locally installed playwright. Start Vite preview on 15178 first.
import { createRequire } from 'node:module'
import assert from 'node:assert/strict'
const { chromium } = createRequire(import.meta.url)('playwright')
const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || "msedge" })
const page = await browser.newPage()
let status = 'ready', mode = 'normal', activity = 'busy', question = true, permission = true
let questionsHeld, releaseQuestions
const writes = [], errors = []
page.on('pageerror', error => errors.push(error.message))
await page.route('**/api/console/v1/**', async route => {
  const request = route.request(), path = new URL(request.url()).pathname.replace('/api/console/v1', '')
  const observe = ['ready','draining'].includes(status), proceed = observe && mode !== 'repair_only'
  const runtime = { status, runtime_mode: 'on_demand', gate_policy: status === 'ready' ? 'open' : 'closed',
    ready: status === 'ready', maintenance_mode: mode, manual_stop_reason: 'none', state_version: 1,
    allowed_actions: mode === 'normal' ? ['stop'] : [],
    interaction: { can_submit_new: status === 'ready' && mode === 'normal', can_observe: proceed, can_continue: proceed } }
  let body = { items: [] }
  if (request.method() !== 'GET') {
    writes.push({ path, body: request.postDataJSON() })
    if (path === '/questions/q/reply') question = false
    if (path === '/permissions/p/reply') permission = false
    if (path === '/sessions/session-a/abort') activity = 'idle'
    body = { ok: true }
  } else if (path === '/me') body = { user: { id:'synthetic', username:'synthetic',role:'user',must_change_password:false,runtime }, csrf_token:'synthetic',capabilities:['business.use'] }
  else if (path === '/sessions') body = { items:[{id:'session-a',title:'合成确认任务',status:activity}] }
  else if (path === '/models') body = { items:[{id:'model',name:'合成模型'}] }
  else if (path === '/questions') {
    const items = question ? [{id:'q',sessionID:'session-a',questions:[{header:'范围',question:'选择合成范围',options:[{label:'仅本次'}]}]}] : []
    if (questionsHeld) await new Promise(resolve => { releaseQuestions = resolve })
    body = { items }
  } else if (path === '/permissions') body = { items:permission ? [{id:'p',sessionID:'session-a',description:'合成操作确认'}] : [] }
  else if (path === '/events') return route.fulfill({ status:200,contentType:'text/event-stream',body:'event: change\ndata: {"resources":["messages"]}\n\n' })
  return route.fulfill({status:200,json:body})
})
async function sync() {
  const response = page.waitForResponse(r => r.url().endsWith('/me'))
  await page.evaluate(() => window.dispatchEvent(new Event('online')))
  await response
}
try {
  await page.goto('http://127.0.0.1:15178')
  await page.getByText('合成确认任务',{exact:true}).click()
  await page.getByText('选择合成范围',{exact:true}).waitFor()
  await page.getByRole('textbox',{name:'输入消息'}).fill('保留中文草稿')
  status='draining'; await sync()
  await page.getByText('正在等待当前任务结束后更新配置', {exact:false}).waitFor()
  await page.getByText('仅本次',{exact:true}).click()
  await page.getByRole('button',{name:'提交回答'}).click()
  await page.getByRole('button',{name:'仅允许本次'}).click()
  await page.getByRole('button',{name:'停止生成',exact:true}).click()
  assert.equal(writes.filter(w=>w.path==='/questions/q/reply').length,1)
  assert.equal(writes.filter(w=>w.path==='/permissions/p/reply').length,1)
  assert.equal(writes.filter(w=>w.path==='/sessions/session-a/abort').length,1)
  assert.equal(await page.getByRole('button',{name:'发送',exact:true}).isDisabled(),true)
  assert.equal(await page.getByRole('textbox',{name:'输入消息'}).inputValue(),'保留中文草稿')
  status='ready'; mode='frozen'; await sync()
  await page.getByText('平台维护中，暂不可启停或取消等待。',{exact:false}).waitFor()
  assert.equal(await page.getByRole('button',{name:'停止助手',exact:true}).count(),0)
  // A response admitted before losing observation must not refill the cards afterwards.
  question=true; questionsHeld=true; mode='normal'; await sync()
  await page.waitForFunction(() => true)
  for (let i=0; !releaseQuestions && i<100; i++) await new Promise(r=>setTimeout(r,50))
  assert.ok(releaseQuestions)
  status='paused'; await sync()
  await page.getByText('状态暂不可更新',{exact:false}).waitFor()
  questionsHeld=false; releaseQuestions()
  await page.waitForTimeout(200)
  assert.equal(await page.getByText('选择合成范围',{exact:true}).count(),0)
  status='ready'; await sync()
  for (const width of [1366,1920,390]) {
    await page.setViewportSize({width,height:900})
    assert.equal(await page.getByRole('textbox',{name:'输入消息'}).inputValue(),'保留中文草稿')
  }
  assert.equal(writes.filter(w=>w.path.includes('/messages')||w.path.includes('/runtime/')).length,0)
  assert.deepEqual(errors,[])
  console.log(JSON.stringify({passed:true,scenarios:['question','permission','abort','new_prompt_denied','maintenance','late_read','draft','1366','1920','390'],writes:writes.map(w=>w.path)}))
} finally { await browser.close() }
