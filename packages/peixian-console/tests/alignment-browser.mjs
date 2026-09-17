// Built Solid UI against a strict synthetic HTTP contract. No real model requests.
import assert from 'node:assert/strict'
import { chromium } from 'playwright'
import { mkdir } from 'node:fs/promises'
const base = process.env.ALIGNMENT_URL || 'http://127.0.0.1:15178'
const browser = await chromium.launch({ headless: true })
const reports = []
await mkdir('output/playwright', { recursive: true })
async function fixture(options = {}) {
  const context = await browser.newContext()
  const page = await context.newPage()
  const state = { role: 'user', status: 'unprovisioned', models: [], sessions: [], messages: [], mustChange: false, mode: 'normal', failure: undefined, ...options }
  const writes = [], reads = [], errors = []
  page.on('pageerror', e => errors.push(e.message))
  await page.route('**/api/console/v1/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname.split('/api/console/v1')[1]
    const roleCaps = state.role === 'user' ? ['business.use'] : state.role === 'admin' ? ['users.manage','models.manage','audit.read'] : ['users.manage','admins.manage','models.manage','audit.read','plugins.manage','connections.manage','templates.manage','jobs.read','runtimes.manage']
    const observe = ['ready', 'draining'].includes(state.status)
    const runtime = { id:'runtime-a', status:state.status, runtime_mode:'on_demand', manual_stop_reason:'none', maintenance_mode:state.mode, ready:state.status==='ready', state_version:7, gate_policy:state.status==='ready'?'open':'closed', allowed_actions:state.status==='unprovisioned'?['start']:['stop'], interaction:{can_observe:observe,can_continue:observe,can_submit_new:state.status==='ready'&&state.mode==='normal'} }
    let body = {items:[]}, status = 200
    if (request.method() !== 'GET') {
      writes.push({ path, body:request.postDataJSON(), headers:request.headers() })
      assert.ok(request.headers()['idempotency-key'], path+' idempotency')
      assert.equal(request.headers()['x-csrf-token'], 'synthetic-csrf', path+' csrf')
      if (path === '/me/runtime/start') state.status = 'provisioning'
      if (path === '/sessions') { state.sessions.push({id:'s1',title:'合成对话',status:'idle'}); body=state.sessions[0] }
      else if (path === '/sessions/s1/messages') {
        if (state.failure==='network') return route.abort('connectionreset')
        if (state.failure==='server') return route.fulfill({status:503,json:{message:'合成网关响应待确认',code:'upstream_timeout'}})
        if (state.failure==='overload') return route.fulfill({status:429,headers:{'Retry-After':'2'},json:{message:'服务繁忙，草稿已保留',code:'busy'}})
        state.messages=[{info:{id:'m1',role:'user'},parts:[{type:'text',text:request.postDataJSON().text}]},{info:{id:'m2',role:'assistant'},parts:[{type:'text',text:'合成接口回答'}]}]
        body={accepted:true,run_id:'not-a-persistent-run'}
      } else if (path === '/me/password') state.mustChange=false
      else body={ok:true}
    } else {
      reads.push(path)
      if (path === '/me') body={user:{id:'user-a',username:'验收账号',role:state.role,must_change_password:state.mustChange,...(state.role==='user'?{runtime}:{})},capabilities:roleCaps,csrf_token:'synthetic-csrf'}
      else if (path === '/models') body={items:state.models}
      else if (path === '/sessions') body={items:state.sessions}
      else if (path === '/sessions/s1/messages') body={items:state.messages}
      else if (path === '/events') return route.fulfill({status:200,contentType:'text/event-stream',body:': synthetic heartbeat\n\n'})
      else if (path === '/platform') body={name:'沛警智枢',short_name:'警',description:'接口与状态验收'}
      else if (!['/files','/skills','/plugins','/questions','/permissions'].includes(path) && !path.startsWith('/admin/')) { status=404; body={message:'未实现接口',code:'not_found'} }
    }
    return route.fulfill({status,json:body})
  })
  await page.goto(base)
  return {context,page,state,writes,reads,errors}
}
try {
  {
    const f=await fixture()
    await f.page.getByRole('textbox',{name:'输入消息'}).fill('启动期间保留的中文草稿')
    await f.page.getByRole('button',{name:'启动助手',exact:true}).click()
    assert.equal(f.writes.filter(w=>w.path==='/me/runtime/start').length,1)
    assert.equal(await f.page.getByRole('textbox',{name:'输入消息'}).inputValue(),'启动期间保留的中文草稿')
    assert.equal(await f.page.getByRole('button',{name:'发送',exact:true}).isDisabled(),true)
    assert.equal(await f.page.getByText('张某夜间活动研判',{exact:true}).count(),0)
    assert.equal(await f.page.getByText('Qwen3-32B',{exact:true}).count(),0)
    assert.ok(!f.reads.some(p=>p==='/capabilities'||p.includes('/runs/')))
    assert.deepEqual(f.errors,[])
    reports.push('empty catalogs have no demo data; on-demand start uses csrf/idempotency and preserves draft')
    await f.context.close()
  }
  for (const failure of [undefined,'network','server','overload']) {
    const f=await fixture({status:'ready',models:[{id:'model-a',name:'合成模型',is_default:true}],failure})
    const input=f.page.getByRole('textbox',{name:'输入消息'}),send=f.page.getByRole('button',{name:'发送',exact:true})
    await input.fill('中文输入验收')
    await send.click()
    if (!failure) {
      await f.page.getByText('合成接口回答',{exact:true}).waitFor()
      assert.equal(await input.inputValue(),'')
      assert.ok(!f.reads.some(p=>p.includes('/runs/')))
      for (const width of [1366,1920,390]) {
        await f.page.setViewportSize({width,height:900})
        await input.fill('窄屏中文草稿')
        assert.equal(await input.inputValue(),'窄屏中文草稿')
        assert.ok(await input.isVisible())
        const overflow=await f.page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2)
        assert.equal(overflow,false,'horizontal overflow '+width)
        await f.page.screenshot({path:`output/playwright/alignment-${width}.png`,fullPage:true})
      }
    } else {
      await f.page.getByText(failure!=='overload'?'提交结果待确认，草稿已保留。请先检查历史和当前任务状态，避免重复调用。':'服务繁忙，草稿已保留',{exact:true}).waitFor()
      assert.equal(await input.inputValue(),'中文输入验收')
      if (failure!=='overload') assert.equal(await send.isDisabled(),true)
      await f.page.waitForTimeout(700)
    }
    assert.equal(f.writes.filter(w=>w.path.endsWith('/messages')).length,1)
    assert.deepEqual(f.errors,[])
    reports.push('message '+(failure||'accepted')+'; no automatic replay, no Run query')
    await f.context.close()
  }
  for (const role of ['admin','super_admin']) {
    const f=await fixture({role})
    const nav=f.page.locator('.sidebar nav')
    await nav.getByRole('button',{name:'用户管理',exact:true}).waitFor()
    assert.equal(await nav.getByRole('button',{name:'插件发布',exact:true}).count(),role==='super_admin'?1:0)
    const modelsRead=f.page.waitForResponse(r=>r.url().endsWith('/admin/models'))
    await nav.getByRole('button',{name:'模型管理',exact:true}).click()
    assert.equal((await modelsRead).status(),200)
    assert.ok(!f.reads.includes('/admin/departments'))
    if(role==='admin') assert.ok(!f.reads.some(p=>['/admin/plugins','/admin/connections','/admin/templates','/admin/jobs'].includes(p)))
    assert.deepEqual(f.errors,[])
    reports.push(role+' menu and resource permissions')
    await f.context.close()
  }
  {
    const f=await fixture({mustChange:true})
    await f.page.getByRole('heading',{name:'设置你的登录密码'}).waitFor()
    assert.equal(await f.page.getByRole('textbox',{name:'输入消息'}).count(),0)
    assert.ok(!f.reads.some(p=>['/models','/sessions','/events'].includes(p)))
    reports.push('first-password gate blocks business reads')
    await f.context.close()
  }
  console.log(JSON.stringify({passed:true,scenarios:reports},null,2))
} finally { await browser.close() }
