// Real Control, real SQLite and browser cookies. Requires ephemeral alignment_server.py.
// No request interception, Worker, Agent, paid model, or production credentials.
import assert from 'node:assert/strict'
import { chromium } from 'playwright'
const base=process.env.ALIGNMENT_AUTH_URL || 'http://127.0.0.1:15179'
const prefix=base+'/api/console/v1'
const password='synthetic-alignment-password-123'
const browser=await chromium.launch({headless:true})
const scenarios=[]
try {
  for (const [username,role] of [['admin','super_admin'],['alignment-manager','admin'],['alignment-user','user']]) {
    const context=await browser.newContext(),page=await context.newPage(),errors=[]
    page.on('pageerror',e=>errors.push(e.message))
    await page.goto(base)
    await page.getByRole('textbox',{name:'账号',exact:true}).fill(username)
    await page.locator('input[autocomplete="current-password"]').fill(password)
    await page.getByRole('button',{name:/登\s*录/}).click()
    await page.getByRole('heading',{name:'设置你的登录密码'}).waitFor()
    const cookie=(await context.cookies()).find(c=>c.name==='px_session')
    assert.ok(cookie?.httpOnly)
    assert.equal(cookie.sameSite,'Strict')
    assert.equal((await page.request.get(prefix+'/me')).status(),200)
    const otherSession=await browser.newContext()
    assert.equal((await otherSession.request.post(prefix+'/auth/login',{data:{username,password}})).status(),200)
    await page.getByLabel('当前密码',{exact:true}).fill(password)
    await page.getByLabel('新密码',{exact:false}).first().fill(password+'-changed')
    await page.getByLabel('确认新密码',{exact:true}).fill(password+'-changed')
    await page.getByRole('button',{name:'保存并进入工作台'}).click()
    await page.getByRole('button',{name:'退出登录',exact:true}).waitFor()
    const identity=await (await page.request.get(prefix+'/me')).json()
    assert.equal(identity.user.role,role)
    assert.equal(identity.user.must_change_password,false)
    const csrf=identity.csrf_token
    const noCsrf=await page.request.post(prefix+'/tokens',{data:{name:'missing-csrf'}})
    assert.equal(noCsrf.status(),403)
    const wrongOrigin=await page.request.post(prefix+'/tokens',{headers:{'X-CSRF-Token':csrf,'Origin':'https://other.invalid'},data:{name:'wrong-origin'}})
    assert.equal(wrongOrigin.status(),403)
    if (role==='user') {
      await page.getByRole('textbox',{name:'输入消息'}).fill('真实控制层启动前草稿')
      assert.equal(await page.locator('.sidebar nav').getByRole('button',{name:'用户管理',exact:true}).count(),0)
      assert.equal((await page.request.get(prefix+'/admin/users')).status(),403)
      const denied=await page.request.post(prefix+'/me/runtime/start',{headers:{'X-CSRF-Token':csrf},data:{}})
      assert.equal(denied.status(),422)
      const start=page.waitForResponse(r=>r.url().endsWith('/me/runtime/start')&&r.request().method()==='POST')
      await page.getByRole('button',{name:'启动助手',exact:true}).click()
      assert.ok((await start).ok())
      await page.getByRole('button',{name:'取消启动',exact:true}).waitFor()
      assert.equal(await page.getByRole('textbox',{name:'输入消息'}).inputValue(),'真实控制层启动前草稿')
      assert.equal(await page.getByRole('button',{name:'发送',exact:true}).isDisabled(),true)
      const cancel=page.waitForResponse(r=>r.url().endsWith('/me/runtime/stop')&&r.request().method()==='POST')
      await page.getByRole('button',{name:'取消启动',exact:true}).click()
      assert.ok((await cancel).ok())
      scenarios.push('real runtime start/cancel with state version and no Worker')
    } else {
      assert.equal((await page.request.get(prefix+'/admin/users')).status(),200)
      assert.equal((await page.request.get(prefix+'/admin/plugins')).status(),role==='admin'?403:200)
      const nav=page.locator('.sidebar nav')
      assert.equal(await nav.getByRole('button',{name:'插件发布',exact:true}).count(),role==='super_admin'?1:0)
    }
    // The documented contract preserves the changing session, revokes other sessions.
    assert.equal((await otherSession.request.get(prefix+'/me')).status(),401)
    await otherSession.close()
    const activeCookie=(await context.cookies()).find(c=>c.name==='px_session')
    const logout=page.waitForResponse(r=>r.url().endsWith('/auth/logout'))
    await page.getByRole('button',{name:'退出登录',exact:true}).click()
    assert.ok((await logout).ok())
    const old=await browser.newContext()
    await old.addCookies([activeCookie])
    assert.equal((await old.request.get(prefix+'/me')).status(),401)
    assert.equal((await page.request.get(prefix+'/me')).status(),401)
    assert.deepEqual(errors,[])
    scenarios.push(role+': real login, initial password, cookie, csrf, origin, menu, logout/revocation')
    await old.close();await context.close()
  }
  console.log(JSON.stringify({passed:true,scenarios},null,2))
} finally { await browser.close() }
