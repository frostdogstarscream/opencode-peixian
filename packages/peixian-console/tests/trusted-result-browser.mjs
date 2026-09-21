// Isolated UI interaction checks. Response fixtures are synthetic, not live-account E2E.
import { chromium } from "playwright"
import assert from "node:assert/strict"
import { mkdir, writeFile } from "node:fs/promises"
import path from "node:path"
const output = path.resolve(process.env.PR8B_BROWSER_OUTPUT || "output/playwright/pr8b")
await mkdir(output, { recursive: true })
const browser = await chromium.launch({
  headless: true,
  ...(process.env.PR8B_CHROMIUM ? { executablePath: process.env.PR8B_CHROMIUM } : {}),
})
const page = await browser.newPage({ viewport: { width: 1366, height: 1000 } })
const errors = []
page.on("pageerror", (error) => errors.push(error.message))
const base = process.env.PR8B_UI_URL || "http://127.0.0.1:19783/tests/trusted-result-harness.html"
const checks = []
const check = (name, value) => {
  assert.ok(value, name)
  checks.push(name)
}
try {
  await page.goto(base)
  await page.getByRole("radio", { name: "演示车辆甲" }).waitFor()
  await page.getByRole("radio", { name: "演示车辆甲" }).check()
  await page.getByRole("button", { name: "确认对象", exact: true }).click()
  await page.getByRole("button", { name: "继续查询", exact: true }).waitFor()
  check(
    "resolve does not query",
    (await page.getByRole("status", { name: "查询次数" }).textContent()).includes("查询0次"),
  )
  await page.getByRole("button", { name: "刷新", exact: true }).click()
  await page.getByRole("button", { name: "继续查询", exact: true }).waitFor()
  check(
    "refresh preserves explicit resume",
    (await page.getByRole("status", { name: "查询次数" }).textContent()).includes("查询0次"),
  )
  await page.getByRole("button", { name: "继续查询", exact: true }).click()
  check(
    "explicit resume invokes only once",
    (await page.getByRole("status", { name: "查询次数" }).textContent()).includes("查询1次"),
  )
  const source = page.getByRole("button", { name: /演示对象甲于22:10/ })
  await source.click()
  await page.getByRole("dialog", { name: "来源详情" }).waitFor()
  check("source drawer snapshot", (await page.getByRole("dialog").textContent()).includes("DEMO-SNAPSHOT"))
  await page.keyboard.press("Escape")
  await page.getByRole("dialog").waitFor({ state: "detached" })
  check("focus restored to source", await source.evaluate((element) => document.activeElement === element))
  await page.getByRole("combobox", { name: "测试状态" }).selectOption("unknown")
  await page.getByText("请求可能已发出，但结果未确认，不会自动重试", { exact: true }).waitFor()
  check("unknown is explicit", await page.getByText("车辆资料未取得，不能解释为零条。", { exact: true }).isVisible())
  for (const width of [1366, 1920, 390]) {
    await page.setViewportSize({ width, height: 1000 })
    check(
      `no horizontal overflow ${width}`,
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    )
    await page.screenshot({ path: path.join(output, `result-${width}.png`), fullPage: true })
  }
  await page.emulateMedia({ colorScheme: "dark" })
  await page.screenshot({ path: path.join(output, "result-dark.png"), fullPage: true })
  await page.emulateMedia({ colorScheme: "light" })
  await page.getByRole("combobox", { name: "测试状态" }).selectOption("legacy")
  await page.getByText(/Legacy 历史结果：/).waitFor()
  check(
    "legacy has no invented facts",
    (await page.getByRole("heading", { name: "已核验事实", exact: true }).count()) === 0,
  )
  await page.getByRole("button", { name: "切换会话", exact: true }).click()
  check("session switch clears panel", (await page.getByRole("region", { name: "任务与可信结果" }).count()) === 0)
  await page.reload()
  await page.getByRole("combobox", {name:"测试状态"}).selectOption("conflict")
  await page.getByRole("radio", {name:"演示车辆甲"}).check()
  await page.getByRole("button", {name:"确认对象",exact:true}).click()
  await page.getByText("确认已过期，请刷新",{exact:true}).waitFor()
  check("stale clarification refuses query",(await page.getByRole("status",{name:"查询次数"}).textContent()).includes("查询0次"))
  check("stale clarification has no resume",await page.getByRole("button",{name:"继续查询",exact:true}).count()===0)
  await page.getByRole("combobox", {name:"测试状态"}).selectOption("slow")
  await page.getByRole("button", {name:"切换会话",exact:true}).click()
  await new Promise(resolve=>setTimeout(resolve,500))
  check("late result cannot restore old panel",await page.getByRole("region",{name:"任务与可信结果"}).count()===0)
  check("no browser exceptions", errors.length === 0)
  await writeFile(
    path.join(output, "checks.json"),
    JSON.stringify(
      { status: "passed", scope: "synthetic_component_browser", checks, errors, model_requests: 0 },
      null,
      2,
    ),
  )
  console.log(JSON.stringify({ status: "passed", checks: checks.length, output }))
} finally {
  await browser.close()
}
