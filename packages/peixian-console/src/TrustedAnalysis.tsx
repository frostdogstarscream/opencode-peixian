import {EventDiagramView} from "./EventDiagram"
import { createEffect, For, onCleanup, Show } from "solid-js"
import { Icon, Status } from "./components"
import type { AnalysisClue, AnalysisResult } from "./types"
export type Presentation = AnalysisResult
export type TrustedEvidence = {turn_id?: string; presentation?: unknown}
function icon(type: string) { return ({trajectory:"route",companion:"users",vehicle:"car",place:"pin",funds:"file",relation:"users"} as Record<string,string>)[type] || "file" }
export function AnalysisResultView(props: {result: Presentation; onSelect: (clue: AnalysisClue) => void}) {
  const select=(id: string)=>{const clue=props.result.clues.find(x=>x.id===id);if(clue)props.onSelect(clue)}
  return <div class="analysis-result trusted-analysis" role="region" aria-label="研判结果">
    <section class="analysis-section analysis-process"><h3><Icon name="skill" size={17}/>研判过程</h3><div class="analysis-steps"><For each={props.result.process}>{(step,i)=><div class="analysis-step"><span class={"step-state "+step.status}>{step.status==="completed"?"✓":i()+1}</span><strong>{i()+1}. {step.title}</strong><p>{step.detail}</p><time>{step.time}</time><Status value={step.status}/></div>}</For></div></section>
    <section class="analysis-section analysis-conclusions"><h3><Icon name="file" size={17}/>核心结论</h3><ul><For each={props.result.conclusions} fallback={<li>暂无通过核对的结论。</li>}>{item=>{const source=()=>props.result.conclusion_sources?.find(value=>value.text===item);return <li><button class="conclusion-link" disabled={!source()?.clue_id} onClick={()=>source()?.clue_id&&select(source()!.clue_id!)}>{item}</button></li>}}</For></ul></section>
    <EventDiagramView value={props.result.diagram} onSelect={props.onSelect}/>
    <section class="analysis-section"><h3><Icon name="file" size={17}/>研判依据</h3><div class="analysis-evidence-grid"><For each={props.result.evidence}>{item=><button class={"analysis-evidence-card evidence-"+item.type} disabled={!item.clue_id} onClick={()=>item.clue_id&&select(item.clue_id)}><div class="analysis-evidence-title"><span><Icon name={icon(item.type)} size={17}/></span>{item.title}</div><strong>{item.value}<small>{item.unit}</small></strong><p>{item.summary}</p><For each={item.items}>{line=><small class="analysis-evidence-note">{line}</small>}</For></button>}</For></div></section>
    <Show when={props.result.missing?.length}><section class="analysis-section analysis-limits"><h3>资料缺口与局限</h3><ul><For each={props.result.missing}>{item => <li>{item}</li>}</For></ul></section></Show>
    <Show when={props.result.next_steps?.trim()}><section class="analysis-section analysis-next-steps"><h3>下一步建议</h3><p>{props.result.next_steps}</p></section></Show>
  </div>
}
export function CluePanel(props:{clues:AnalysisClue[];expanded:boolean;onExpandedChange:(expanded:boolean)=>void;onSelect:(clue:AnalysisClue)=>void;hideHeader?:boolean}) {
 return <aside class="clue-panel trusted-clues expanded" aria-label="智能发现线索"><Show when={!props.hideHeader}><button class="clue-panel-head" onClick={()=>props.onExpandedChange(false)} aria-expanded={props.expanded} aria-label="收起智能发现线索"><strong><Icon name="star" size={18}/>智能发现线索</strong><span class="clue-panel-actions"><small>{props.clues.length} 项</small><b>收起</b></span></button></Show><div class="clue-list"><For each={props.clues}>{clue=><article class={"clue-card clue-"+clue.type}><div class="clue-card-head"><span><Icon name={icon(clue.type)} size={18}/></span><strong>{clue.title}</strong></div><h4>{clue.headline}</h4><button onClick={()=>props.onSelect(clue)}>查看详情</button></article>}</For></div></aside>
}
export function ClueDrawer(props:{clue:AnalysisClue;onClose:()=>void;onReturn?:()=>void}) {
 let dialog!:HTMLDialogElement
 const origin=document.activeElement as HTMLElement | null
 createEffect(()=>{dialog.showModal();dialog.querySelector<HTMLButtonElement>("button")?.focus()})
 onCleanup(()=>{dialog.close();queueMicrotask(()=>origin?.isConnected&&origin.focus())})
 return <dialog ref={dialog} class="trusted-drawer" aria-label="线索详情" onCancel={e=>{e.preventDefault();props.onClose()}}>
  <header><h2>线索详情</h2><Show when={props.onReturn}><button onClick={()=>props.onReturn?.()}>返回关联消息</button></Show><button class="icon-button" aria-label="关闭线索详情" onClick={props.onClose}><Icon name="close"/></button></header>
  <div class="clue-drawer-scroll">
   <section class="clue-name-card">
    <div class="clue-identity">
     <span class="clue-identity-icon"><Icon name={icon(props.clue.type)} size={22}/></span>
     <div><small>关联{props.clue.type === "person" ? "人员" : "线索"}</small><h3>{props.clue.title}</h3></div>
    </div>
    <div class="clue-meta">
     <Show when={props.clue.level}><span class="clue-level">线索等级：{props.clue.level}</span></Show>
     <Show when={props.clue.time}><span>发现时间：{props.clue.time}</span></Show>
    </div>
    <p>{props.clue.headline}</p>
    <Show when={props.clue.source}><small class="clue-source">来源任务：{props.clue.source}</small></Show>
   </section>
   <section>
    <h3><Icon name="file" size={17}/>线索摘要</h3>
    <p>{props.clue.summary}</p>
   </section>
   <section>
    <h3><Icon name="star" size={17}/>核心发现</h3>
    <ul class="clue-discoveries"><For each={props.clue.discoveries}>{text=><li>{text}</li>}</For></ul>
   </section>
   <section class="clue-evidence-section">
    <h3><Icon name="file" size={17}/>研判依据 <small>{props.clue.evidence.length} 项</small></h3>
    <div class="clue-evidence-list"><For each={props.clue.evidence}>{item=><article><span><Icon name={icon(item.type)} size={16}/></span><div><strong>{item.label}</strong><p>{item.content}</p></div></article>}</For></div>
   </section>
  </div>
 </dialog>
}
