import { createEffect, createSignal, For, onCleanup, Show } from "solid-js"
import { Icon, Status } from "./components"
import type { AnalysisClue } from "./types"
export type Presentation = {
  version: string; turn_id: string; title: string; subject_ref: string
  process: {id: string; title: string; detail: string; status: string; time: string}[]
  conclusions: {text: string; clue_id: string; source_ids: string[]}[]
  evidence: {type: string; title: string; value: string | number; unit: string; summary: string; items: string[]; clue_id: string}[]
  clues: AnalysisClue[]; missing: string[]
}
export type TrustedEvidence = {turn_id?: string; presentation?: Presentation}
function icon(type: string) { return ({trajectory:"route",companion:"users",vehicle:"car",place:"pin",funds:"file",relation:"users"} as Record<string,string>)[type] || "file" }
export function AnalysisResultView(props: {result: Presentation; onSelect: (clue: AnalysisClue) => void}) {
  const select=(id: string)=>{const clue=props.result.clues.find(x=>x.id===id);if(clue)props.onSelect(clue)}
  return <div class="analysis-result trusted-analysis" role="region" aria-label="研判结果">
    <section class="analysis-section analysis-process"><h3><Icon name="skill" size={17}/>研判过程</h3><div class="analysis-steps"><For each={props.result.process}>{(step,i)=><div class="analysis-step"><span class={"step-state "+step.status}>{step.status==="completed"?"✓":i()+1}</span><strong>{i()+1}. {step.title}</strong><p>{step.detail}</p><time>{step.time}</time><Status value={step.status}/></div>}</For></div></section>
    <section class="analysis-section analysis-conclusions"><h3><Icon name="file" size={17}/>核心结论</h3><ul><For each={props.result.conclusions} fallback={<li>暂无通过核对的结论。</li>}>{item=><li><button class="conclusion-link" onClick={()=>select(item.clue_id)}>{item.text}</button></li>}</For></ul></section>
    <section class="analysis-section"><h3><Icon name="file" size={17}/>研判依据</h3><div class="analysis-evidence-grid"><For each={props.result.evidence}>{item=><button class={"analysis-evidence-card evidence-"+item.type} onClick={()=>select(item.clue_id)}><div class="analysis-evidence-title"><span><Icon name={icon(item.type)} size={17}/></span>{item.title}</div><strong>{item.value}<small>{item.unit}</small></strong><p>{item.summary}</p><For each={item.items}>{line=><small class="analysis-evidence-note">{line}</small>}</For></button>}</For></div></section>
    <details class="analysis-limits"><summary>资料缺口</summary><ul><For each={props.result.missing}>{text=><li>{text}</li>}</For></ul></details>
  </div>
}
export function CluePanel(props:{clues:AnalysisClue[];onSelect:(clue:AnalysisClue)=>void}) {
 const [expanded,setExpanded]=createSignal(false)
 return <aside class={"clue-panel trusted-clues "+(expanded()?"expanded":"")} aria-label="资料发现"><button class="clue-panel-head" onClick={()=>setExpanded(!expanded())} aria-expanded={expanded()}><strong><Icon name="star" size={18}/>资料发现</strong><small>{props.clues.length} 项</small></button><div class="clue-list"><For each={props.clues}>{clue=><article class={"clue-card clue-"+clue.type}><div class="clue-card-head"><span><Icon name={icon(clue.type)} size={18}/></span><strong>{clue.title}</strong></div><h4>{clue.headline}</h4><button onClick={()=>props.onSelect(clue)}>查看详情</button></article>}</For></div></aside>
}
export function ClueDrawer(props:{clue:AnalysisClue;onClose:()=>void}) {
 let dialog!:HTMLDialogElement
 const origin=document.activeElement as HTMLElement | null
 createEffect(()=>{dialog.showModal();dialog.querySelector<HTMLButtonElement>("button")?.focus()})
 onCleanup(()=>{dialog.close();queueMicrotask(()=>origin?.isConnected&&origin.focus())})
 return <dialog ref={dialog} class="trusted-drawer" aria-label="线索详情" onCancel={e=>{e.preventDefault();props.onClose()}}><header><h2>线索详情</h2><button class="icon-button" aria-label="关闭线索详情" onClick={props.onClose}><Icon name="close"/></button></header><div class="clue-drawer-scroll"><section class="clue-name-card"><h3>{props.clue.title}</h3><p>{props.clue.headline}</p></section><section><h3>摘要</h3><p>{props.clue.summary}</p></section><section><h3>核心发现</h3><ul><For each={props.clue.discoveries}>{text=><li>{text}</li>}</For></ul></section><section><h3>研判依据</h3><div class="clue-evidence-list"><For each={props.clue.evidence}>{item=><article><Icon name={icon(item.type)} size={16}/><div><strong>{item.label}</strong><p>{item.content}</p></div></article>}</For></div></section></div></dialog>
}
