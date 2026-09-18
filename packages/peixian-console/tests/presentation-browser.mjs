import assert from "node:assert/strict";
import fs from "node:fs";
import { chromium } from "playwright";
const root="/srv/peixian-alignment-20260917", creds=JSON.parse(fs.readFileSync(root+"/private.json","utf8"));
const out="/root/PeiXianDB/frontend-alignment/output/playwright/presentation";fs.mkdirSync(out,{recursive:true});
const browser=await chromium.launch({headless:true,args:["--host-resolver-rules=MAP 36.134.45.38 127.0.0.1","--no-proxy-server"]});
const results=[];
try {
for(const width of [1366,1920,390]) {
 const context=await browser.newContext({ignoreHTTPSErrors:true,viewport:{width,height:1000}});const page=await context.newPage();const errors=[];page.on("pageerror",e=>errors.push(e.message));
 await page.goto("https://36.134.45.38:19460/");await page.getByRole("textbox",{name:"账号",exact:true}).fill("alignment-a");await page.locator('input[autocomplete="current-password"]').fill(creds.accounts["alignment-a"].password);await page.getByRole("button",{name:/登\s*录/}).click();await page.getByRole("button",{name:"退出登录",exact:true}).waitFor();
 if(width===390)await page.getByRole("button",{name:"显示对话记录",exact:true}).click();
 await page.getByRole("button",{name:"涉赌案件资料整理",exact:true}).first().click();await page.getByRole("region",{name:"研判结果",exact:true}).waitFor();
 const result=page.getByRole("region",{name:"研判结果",exact:true});
 assert.equal(await result.locator(".analysis-step").count(),5);assert.equal(await result.locator(".analysis-evidence-card").count(),4);
 const text=await result.innerText();for(const word of ["合成演示","代码核对演示","请以来源记录为准","COUNT-"])assert.ok(!text.includes(word),word);
 assert.ok(text.includes("核心结论")&&text.includes("研判依据"));
 await result.locator(".analysis-conclusions button").first().click();await page.getByRole("dialog",{name:"线索详情"}).waitFor();
 assert.equal(await page.getByRole("dialog").getByText(/风险等级|合成演示/).count(),0);
 await page.screenshot({path:out+"/drawer-"+width+".png",fullPage:true});await page.keyboard.press("Escape");await page.getByRole("dialog").waitFor({state:"detached"});
 assert.ok(await page.evaluate(()=>document.activeElement?.classList.contains("conclusion-link")));
 await page.screenshot({path:out+"/result-"+width+".png",fullPage:true});
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2));
 for(const selector of [".trusted-clues",...(width>1050?[".trusted-clues .clue-card > button"]:[])]) {
  for(const el of await page.locator(selector).all()) {const box=await el.boundingBox();assert.ok(box&&box.x>=0&&box.x+box.width<=width+1,selector+" clipped");}
 }
 if(width===390) {
  const toggle=page.locator(".trusted-clues .clue-panel-head");await toggle.click();
  await page.locator(".trusted-clues .clue-card > button").first().click();await page.getByRole("dialog",{name:"线索详情"}).waitFor();await page.keyboard.press("Escape");await toggle.click();
 }
 await result.locator(".analysis-evidence-grid").scrollIntoViewIfNeeded();
 await page.screenshot({path:out+"/evidence-"+width+".png",fullPage:true});
 if(width===390)await page.getByRole("button",{name:"显示对话记录",exact:true}).click();await page.getByRole("button",{name:"盗窃案件时空资料核对",exact:true}).first().click();await result.locator(".analysis-step strong").filter({hasText:"核对车辆与地点"}).waitFor();
 assert.equal(await result.getByText("资金流水",{exact:true}).count(),0);
 if(width===390)await page.getByRole("button",{name:"显示对话记录",exact:true}).click();await page.getByRole("button",{name:"新建研判",exact:true}).last().click();assert.equal(await page.locator(".trusted-analysis").count(),0);
 const input=page.getByRole("textbox",{name:"输入消息",exact:true});await input.fill("中文草稿保持不变");assert.equal(await input.inputValue(),"中文草稿保持不变");assert.deepEqual(errors,[]);
 results.push({width,steps:5,evidence_cards:4,copy_clean:true,drawer_keyboard:true,focus_restored:true,no_overflow:true,session_clear:true,chinese_draft:true,page_errors:0});await context.close();
}
fs.writeFileSync(out+"/report.json",JSON.stringify({results},null,2));console.log(JSON.stringify(results));
}finally{await browser.close()}
