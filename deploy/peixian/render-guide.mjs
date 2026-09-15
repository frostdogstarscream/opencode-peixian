import { marked } from "../../packages/peixian-console/node_modules/marked/lib/marked.esm.js"

// Run with the project's existing Bun; no network or server is needed.
const source = await Bun.file(new URL("USER_GUIDE.md", import.meta.url)).text()
const escape = (value) => value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;")
const headings = [...source.matchAll(/<a id="(section-\d+)"><\/a>\s*\n## (.+)/g)]
const navigation = headings.map((item, index) => `<a href="#${item[1]}"><span>${String(index + 1).padStart(2, "0")}</span>${escape(item[2])}</a>`).join("\n")
const markdown = source.replace(/<!-- GUIDE_TOC_START -->[\s\S]*?<!-- GUIDE_TOC_END -->/, "")
const content = (await marked.parse(markdown, { gfm: true })).replaceAll("<table>", '<div class="table-scroll"><table>').replaceAll("</table>", "</table></div>")
const html = `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<meta name="description" content="沛县研判工作台中文使用手册：超级管理员、管理员、普通用户、Python接入、日常运维和常见问题。">
<title>沛县研判工作台 · 详细使用手册</title>
<style>
:root{color-scheme:light;--ink:#183046;--muted:#617187;--brand:#175aca;--border:#d9e1ec;--paper:#fff;--bg:#f4f7fc}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:26px}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.85 "Segoe UI","Microsoft YaHei",system-ui,sans-serif;overflow-wrap:break-word}a{color:var(--brand);text-decoration:none}a:hover{text-decoration:underline}a:focus-visible{outline:3px solid #d27800;outline-offset:3px;border-radius:3px}
.layout{display:grid;grid-template-columns:262px minmax(0,1fr);max-width:1510px;margin:0 auto;min-height:100vh}.sidebar{position:sticky;top:0;height:100vh;overflow:auto;padding:38px 20px 24px;border-right:1px solid var(--border);background:#edf2fa}.logo{font-weight:750;line-height:1.5;font-size:21px;letter-spacing:.03em}.edition{font-size:12px;color:var(--muted);margin:8px 0 28px}.sidebar summary{font-weight:650;cursor:pointer;margin-bottom:14px}.sidebar nav{display:flex;flex-direction:column;gap:6px}.sidebar nav a{display:flex;gap:10px;padding:9px 7px;font-size:14px;line-height:1.6;color:var(--ink);border-radius:6px}.sidebar nav a:hover{background:#dfe9f9;text-decoration:none}.sidebar nav span{font-variant-numeric:tabular-nums;color:var(--brand);font-size:12px;margin-top:2px}.side-note{border-top:1px solid var(--border);padding-top:18px;color:var(--muted);font-size:12px;margin-top:28px}
main{min-width:0;background:var(--paper);padding:50px clamp(25px,5vw,86px) 80px}.kicker{font-size:12px;font-weight:650;color:var(--brand);letter-spacing:.14em;text-transform:uppercase}.top-tools{display:flex;gap:18px;margin:12px 0 36px;font-size:13px}.top-tools span{color:var(--muted)}article{max-width:1030px;margin:0 auto}h1{font-size:clamp(27px,3vw,39px);line-height:1.35;letter-spacing:-.02em;margin:12px 0 26px}h2{font-size:25px;margin:58px 0 20px;padding-top:18px;border-top:2px solid #dee8f8;line-height:1.5}h3{font-size:20px;line-height:1.55;margin:32px 0 15px}h4{font-size:17px;margin:25px 0 12px}p{margin:13px 0}li{margin:7px 0}ul,ol{padding-left:1.6em}blockquote{margin:22px 0;padding:12px 20px;border-left:4px solid #6c92d7;background:#f2f6fd;color:#43566d;font-size:14px}blockquote p:first-child{margin-top:0}blockquote p:last-child{margin-bottom:0}strong{font-weight:700}code{font: .88em/1.65 Consolas,"Cascadia Mono",monospace;background:#edf2f8;padding:.15em .35em;border-radius:4px;overflow-wrap:anywhere}pre{background:#122337;color:#e1ecfa;border:1px solid #213b55;padding:20px;border-radius:9px;overflow-x:auto;line-height:1.65;tab-size:4}pre code{padding:0;background:none;border-radius:0;overflow-wrap:normal;font-size:13px}.table-scroll{overflow-x:auto;margin:20px 0;border:1px solid var(--border);border-radius:8px}table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;vertical-align:top;padding:12px 14px;border-bottom:1px solid var(--border);min-width:100px}th{background:#eaf0fa;font-weight:650}tr:last-child td{border-bottom:0}tbody tr:nth-child(even){background:#fafcff}hr{border:0;border-top:1px solid var(--border);margin:30px 0}.endnote{font-size:12px;color:var(--muted);margin-top:45px;padding-top:20px;border-top:1px solid var(--border)}
@media(max-width:980px){.layout{grid-template-columns:220px minmax(0,1fr)}.sidebar{padding:26px 14px}main{padding:34px 24px 60px}}
@media(max-width:700px){.layout{display:block}.sidebar{position:relative;height:auto;padding:22px;border-right:0;border-bottom:1px solid var(--border)}.edition{margin-bottom:12px}.sidebar nav{display:grid;grid-template-columns:1fr 1fr;gap:2px}.sidebar nav a{font-size:12px}.side-note{display:none}main{padding:28px 18px 50px}.top-tools{flex-wrap:wrap;gap:8px 16px}h2{font-size:22px}h3{font-size:18px}pre{padding:15px}th,td{padding:10px}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
@media print{body{background:white;font-size:10pt;line-height:1.65}.layout{display:block}.sidebar,.top-tools,.kicker{display:none}main{padding:0}h1{font-size:24pt}h2{font-size:17pt;margin-top:24pt;break-after:avoid}h3,h4{break-after:avoid}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f2f4f8;color:#152b40;font-size:9pt;box-decoration-break:clone}.table-scroll{overflow:visible}table{font-size:9pt}tr{break-inside:avoid}a{color:#16467c}blockquote{break-inside:avoid}.endnote{font-size:8pt}@page{size:A4;margin:16mm}}
</style>
</head>
<body><div class="layout">
<aside class="sidebar"><div class="logo">沛县研判工作台</div><div class="edition">使用手册 · 2026-09-15<br>管理员 / 普通用户 / 开发与维护</div>
<details open><summary>阅读目录</summary><nav aria-label="章节目录">${navigation}</nav></details>
<p class="side-note">离线阅读，无外部字体或脚本。<br>Ctrl + F 查找内容；Ctrl + P 打印或另存为 PDF。</p></aside>
<main><article><div class="kicker">PEIXIAN · USER GUIDE</div><div class="top-tools"><a href="USER_GUIDE.md">Markdown 源文档</a><a href="http://127.0.0.1:14090/">打开本机工作台</a><span>Ctrl + F 搜索 · Ctrl + P 打印</span></div>${content}
<div class="endnote">本阅读版由同目录 USER_GUIDE.md 生成。功能范围以该版本源码及配套验收记录为准；文档不包含任何真实密码、令牌或业务资料。</div>
</article></main></div></body></html>`
await Bun.write(new URL("USER_GUIDE.html", import.meta.url), html)
console.log(`Generated USER_GUIDE.html (${headings.length} sections; local assets only)`)