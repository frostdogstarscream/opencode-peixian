import assert from 'node:assert/strict'
import fs from 'node:fs'
import {chromium} from 'playwright'
const root='/srv/peixian-alignment-20260917'
const state=JSON.parse(fs.readFileSync(root+'/private.json','utf8'))
const browser=await chromium.launch({headless:true,args:['--host-resolver-rules=MAP 36.134.45.38 127.0.0.1','--no-proxy-server']})
const results=[]
try {
for(const [username,role,width] of [['admin','super_admin',1920],['alignment-manager','admin',1366],['alignment-a','user',1366],['alignment-b','user',390]]) {
 const context=await browser.newContext({ignoreHTTPSErrors:true,viewport:{width,height:900}})
 const page=await context.newPage(), errors=[]
 page.on('pageerror',e=>errors.push(e.message))
 await page.goto('https://36.134.45.38:19460/',{timeout:30000})
 await page.getByRole('textbox',{name:'账号',exact:true}).fill(username)
 await page.locator('input[autocomplete="current-password"]').fill(state.accounts[username].password)
 await page.getByRole('button',{name:/登\s*录/}).click()
 await page.getByRole('button',{name:'退出登录',exact:true}).waitFor({timeout:30000})
 const me=await page.evaluate(async()=> (await fetch('/api/console/v1/me')).json())
 assert.equal(me.user.role,role)
 const cookie=(await context.cookies()).find(c=>c.name==='px_session')
 assert.ok(cookie?.httpOnly && cookie?.secure);assert.equal(cookie.sameSite,'Strict')
 await page.screenshot({path:root+'/browser-'+username+'.png',fullPage:true})
 assert.deepEqual(errors,[])
 results.push({username,role,width,cookie_secure:true,page_errors:0})
 await page.getByRole('button',{name:'退出登录',exact:true}).click()
 await page.getByRole('textbox',{name:'账号',exact:true}).waitFor()
 await context.close()
}
fs.writeFileSync(root+'/browser-report.json',JSON.stringify({real_api:true,route_mocking:false,tls_note:'Temporary self-signed certificate accepted by test browser; Python verifies certificate',results},null,2))
console.log(JSON.stringify(results))
}finally{await browser.close()}
