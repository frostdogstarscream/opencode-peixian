import {createEffect, createMemo, createSignal, For, onCleanup, Show} from "solid-js"
import DOMPurify from "dompurify"
import {exportName, isDiagram} from "./event-diagram"
import type {DiagramNode} from "./event-diagram"
import type {AnalysisClue} from "./types"
let serial: Promise<unknown> = Promise.resolve()
let renderId = 0
export function EventDiagramView(props: {value: unknown; onSelect: (clue: AnalysisClue) => void}) {
 const diagram = createMemo(() => isDiagram(props.value) ? props.value : undefined, undefined, {equals:(a,b)=>JSON.stringify(a)===JSON.stringify(b)})
 const [page,setPage]=createSignal(0), [zoom,setZoom]=createSignal(1), [svg,setSvg]=createSignal(""), [error,setError]=createSignal(""), [retry,setRetry]=createSignal(0), [large,setLarge]=createSignal(false), [dark,setDark]=createSignal(false)
 let host: HTMLElement | undefined
 let dialog: HTMLDialogElement | undefined, origin: HTMLElement | null = null, generation=0
 const current=()=>diagram()?.pages[page()]
 createEffect(()=>{diagram(); generation++; setPage(0);setZoom(1);setSvg("");setError("");setLarge(false)})
 createEffect(()=>{
  const observer=new MutationObserver(()=>setDark(document.documentElement.dataset.theme==="dark" || document.documentElement.classList.contains("dark")))
  observer.observe(document.documentElement,{attributes:true,attributeFilter:["class","data-theme"]});setDark(document.documentElement.dataset.theme==="dark" || document.documentElement.classList.contains("dark"));onCleanup(()=>observer.disconnect())
 })
 createEffect(()=>{
  const source=current()?.mermaid, theme=dark();retry();const token=++generation;setSvg("");setError("")
  if(!source)return
  const work=async()=>{
   if(token!==generation)return
   try {
    const {default:mermaid}=await import("mermaid")
    if(token!==generation)return
    mermaid.initialize({startOnLoad:false,securityLevel:"strict",htmlLabels:false,theme:"base",themeVariables:{darkMode:theme,primaryColor:theme?"#123b60":"#e9f3ff",primaryTextColor:theme?"#e0efff":"#173d67",primaryBorderColor:theme?"#6196c4":"#83b5e8",lineColor:theme?"#9dc5ec":"#4d85bd",clusterBkg:theme?"#1d2b3d":"#f4f8fd",clusterBorder:theme?"#6a829a":"#b8cde2"},fontFamily:"Arial, Microsoft YaHei, sans-serif",fontSize:17,flowchart:{htmlLabels:false,useMaxWidth:false,wrappingWidth:300,nodeSpacing:30,rankSpacing:40},maxTextSize:65536})
    const result=await mermaid.render("eventDiagram"+(++renderId),source)
    const clean=DOMPurify.sanitize(result.svg,{USE_PROFILES:{svg:true,svgFilters:true},FORBID_TAGS:["foreignObject","script","image","a","animate","set"],FORBID_ATTR:["href","xlink:href"]})
    if(token===generation)setSvg(clean)
   }catch {if(token===generation)setError("图形暂时无法显示，可重试或查看下方事件列表。")}
  }
  serial=serial.then(work,work)
 })
 onCleanup(()=>{generation++;dialog?.close()})
 const close=()=>{setLarge(false);queueMicrotask(()=>origin?.isConnected&&origin.focus())}
 const detail=(node:DiagramNode)=>{
  const d=diagram();if(!d)return
  props.onSelect({id:(d.run_id??d.scenario_id)+":"+node.id,diagram_run_id:d.run_id??d.scenario_id,message_id:host?.closest<HTMLElement>("[data-message-id]")?.dataset.messageId,type:node.category,title:node.number+" · "+node.event,headline:node.subject,summary:node.event,discoveries:[...node.notes,"对象编号："+node.subject_ref,"场景快照："+d.scenario_snapshot_id,"资料快照："+d.records_snapshot_id,"规则版本："+d.rule_version],evidence:node.source_ids.map(id=>({type:node.category,label:id,content:node.time??"时间未明确"}))})
 }
 const download=async(format:"svg"|"png")=>{
  const d=diagram(),p=current();if(!d||!p||!svg())return
  try{
   const documentSvg=new DOMParser().parseFromString(svg(),"image/svg+xml"),root=documentSvg.documentElement,box=root.getAttribute("viewBox")?.split(/\s+/).map(Number)
   if(!box||box.length!==4)throw new Error()
   const width=Math.max(box[2],900), height=box[3]+180
   root.setAttribute("viewBox",`0 0 ${width} ${height}`);root.setAttribute("width",String(width));root.setAttribute("height",String(height))
   const ns="http://www.w3.org/2000/svg",bg=documentSvg.createElementNS(ns,"rect");bg.setAttribute("width","100%");bg.setAttribute("height","100%");bg.setAttribute("fill",dark()?"#182334":"#ffffff");root.insertBefore(bg,root.firstChild)
   const footer=[(d.scenario_id.endsWith("GAMBLING")?"涉赌案件资料整理":"盗窃案件时空资料核对")+` · 第${p.number}/${d.pages.length}页`,d.window_start+" 至 "+d.window_end+" · 北京时间",d.legend,"来源："+d.scenario_snapshot_id+" / "+d.records_snapshot_id,d.synthetic?"资料性质：合成测试资料":"资料性质：来源记录", "完整来源编号见对应事件列表及报告。"]
   footer.forEach((line,i)=>{const t=documentSvg.createElementNS(ns,"text");t.setAttribute("x","16");t.setAttribute("y",String(box[3]+28+i*24));t.setAttribute("fill",dark()?"#ffffff":"#122a44");t.setAttribute("font-size","15");t.textContent=line;root.appendChild(t)})
   const blob=new Blob([new XMLSerializer().serializeToString(root)],{type:"image/svg+xml;charset=utf-8"});let output=blob
   if(format==="png"){
    if(width*height>24000000||height>16000)throw new Error()
    const uri=URL.createObjectURL(blob)
    try {const img=new Image();await new Promise<void>((resolve,reject)=>{img.onload=()=>resolve();img.onerror=reject;img.src=uri});const canvas=document.createElement("canvas");canvas.width=Math.ceil(width*1.5);canvas.height=Math.ceil(height*1.5);const ctx=canvas.getContext("2d");if(!ctx)throw new Error();ctx.scale(1.5,1.5);ctx.drawImage(img,0,0);output=await new Promise<Blob>((resolve,reject)=>canvas.toBlob(v=>v?resolve(v):reject(),"image/png"))}finally{URL.revokeObjectURL(uri)}
   }
   const uri=URL.createObjectURL(output),a=document.createElement("a");a.href=uri;a.download=exportName(d,p.number,format);a.click();setTimeout(()=>URL.revokeObjectURL(uri),1000)
  }catch {setError("图片导出失败。可尝试 SVG 格式，或通过执行报告保存事件及来源。")}
 }
 const graphic=()=> <div class="event-diagram-scroll"><div class="event-diagram-svg" style={{zoom:zoom()}} innerHTML={svg()}/></div>
 return <section ref={host} class="analysis-section event-diagram" aria-label="事件脉络图"><h3>事件脉络图</h3>
  <Show when={diagram() && current()} fallback={<p class="event-diagram-note">当前结果暂无事件图。可继续查看文字与来源记录。</p>}>
   <p class="event-diagram-note">{diagram()!.window_start.slice(0,10)} 至 {diagram()!.window_end.slice(0,10)}（结束不含） · 北京时间 · 共 {diagram()!.total_nodes} 条事件</p>
   <p class="event-diagram-note">{diagram()!.legend}</p>
   <Show when={diagram()!.case_window?.length}><p class="event-diagram-note">场景登记时间范围：{diagram()!.case_window?.join(" 至 ")}（场景信息，不是人员行为）</p></Show>
   <Show when={diagram()!.status==="partial"}><p role="status">部分资料尚未取得，以下仅展示已经核对的事件。</p></Show>
   <div class="event-diagram-toolbar"><button onClick={()=>setZoom(x=>Math.max(.5,x-.25))} aria-label="缩小事件图">−</button><span>{Math.round(zoom()*100)}%</span><button onClick={()=>setZoom(x=>Math.min(2,x+.25))} aria-label="放大事件图">＋</button><button onClick={()=>setZoom(1)}>恢复比例</button><button disabled={!svg()} onClick={()=>{origin=document.activeElement as HTMLElement;setLarge(true)}}>查看大图</button><button disabled={!svg()} onClick={()=>download("png")}>导出 PNG</button><button disabled={!svg()} onClick={()=>download("svg")}>导出 SVG</button></div>
   <Show when={diagram()!.pages.length>1}><div class="event-diagram-toolbar"><button disabled={page()===0} onClick={()=>setPage(x=>x-1)}>上一页</button><span>第 {page()+1}/{diagram()!.pages.length} 页</span><button disabled={page()+1===diagram()!.pages.length} onClick={()=>setPage(x=>x+1)}>下一页</button></div></Show>
   <Show when={error()}><p role="alert">{error()} <button onClick={()=>setRetry(x=>x+1)}>重试渲染</button></p></Show><Show when={!svg()&&!error()}><p role="status">正在绘制事件图…</p></Show>
   {graphic()}
   <details class="event-diagram-note"><summary>对象编号对照</summary><For each={diagram()!.aliases}>{alias=><p>{alias.name}：{alias.ref}</p>}</For></details>
   <div class="event-diagram-list" aria-label="事件来源列表"><For each={current()!.nodes}>{node=><button onClick={()=>detail(node)}><strong>{node.number} · {node.time?.replace("T"," ").slice(0,16)??"时间未明确"}</strong><span>{node.subject} · {node.event}</span><small>查看来源 · {node.source_ids.length} 项</small></button>}</For></div>
  </Show>
  <Show when={large()}><dialog class="event-diagram-dialog" ref={el=>{dialog=el;queueMicrotask(()=>el.isConnected&&el.showModal())}} onCancel={e=>{e.preventDefault();close()}}><header><h2>事件脉络图</h2><button autofocus onClick={close}>关闭大图</button></header><p>{diagram()?.legend}</p>{graphic()}</dialog></Show>
 </section>
}
