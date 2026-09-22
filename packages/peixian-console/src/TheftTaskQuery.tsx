import { createEffect, createSignal, For, onCleanup, Show } from "solid-js"
import { api, post, safeMessage, ApiError } from "./api"
import { Button, Field, ErrorLine } from "./components"

type Source={run_id:string;result_digest:string;record_id:string;snapshot_id:string}
type RecordRow={record_id:string;snapshot_id:string;module:string;fields:Record<string,unknown>}
export default function TheftTaskQuery(props:{model:string;disabled:boolean;sessionID?:string;runID?:string;onAccepted:(sid:string)=>void}) {
 const [goal,setGoal]=createSignal(""),[scope,setScope]=createSignal<Record<string,string>>({}),[records,setRecords]=createSignal<RecordRow[]>([])
 const [digest,setDigest]=createSignal(""),[selected,setSelected]=createSignal<string[]>([]),[busy,setBusy]=createSignal(false),[error,setError]=createSignal(""),[uncertain,setUncertain]=createSignal(false)
 const [taskID,setTaskID]=createSignal<string>()
 let epoch=0;onCleanup(()=>epoch++)
 createEffect(()=>{const sid=props.sessionID,rid=props.runID,g=++epoch;setRecords([]);setTaskID(undefined);setSelected([]);setDigest("");setScope({});setGoal("");setError("");setUncertain(false)
  if(sid&&rid)void Promise.all([api<{records:RecordRow[];task?:{analysis_task_id?:string}}>(`/sessions/${sid}/runs/${rid}/result`),api<{result_digest:string}>(`/sessions/${sid}/runs/${rid}/reviews`)]).then(([r,d])=>{if(g===epoch){setRecords(r.records??[]);setTaskID(r.task?.analysis_task_id);setDigest(d.result_digest)}}).catch(()=>{})
 })
 async function submit(){if(!goal().trim()||busy()||uncertain())return;const g=epoch;setBusy(true);setError("")
  try{
   const sid=props.sessionID||(await post<{id:string}>("/sessions",{title:goal().slice(0,35)})).id
   if(g!==epoch)return
   const values:Record<string,string|number>={}
   for(const [key,value] of Object.entries(scope()))if(value.trim())values[key]=["radius_m","page","page_size"].includes(key)?Number(value):value.trim()
   const sources:Source[]=selected().map(id=>{const row=records().find(r=>r.record_id===id)!;return {run_id:props.runID!,record_id:id,snapshot_id:row.snapshot_id,result_digest:digest()}})
   await post(`/sessions/${sid}/messages`,{text:goal().trim(),model_id:props.model,agent_id:"theft-assistant",client_request_id:crypto.randomUUID(),scope:values,source_refs:sources})
   if(g===epoch){setGoal("");props.onAccepted(sid)}
  }catch(e){if(g===epoch){setError(safeMessage((e as Error).message));if(!(e instanceof ApiError)||e.status===0||e.status>=500)setUncertain(true)}}finally{setBusy(false)}
 }
 async function exportTask(format:"html"|"md"){const tid=taskID(),sid=props.sessionID,g=epoch;if(!tid||!sid)return;try{const text=await api<string>(`/sessions/${sid}/scenarios/${tid}/report?format=${format}`);if(g!==epoch)return;const url=URL.createObjectURL(new Blob([text],{type:format==="html"?"text/html;charset=utf-8":"text/markdown;charset=utf-8"}));const link=document.createElement("a");link.href=url;link.download=`task-${tid}.${format}`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}catch(e){if(g===epoch)setError(safeMessage((e as Error).message))}}
 return <details class="provider-records"><summary>补充范围或选择来源</summary>
  <p>可以直接在对话中表达目标。这里仅用于补充缺少的参数和明确选择来源，不需要先选择查询接口。</p>
  <For each={records()}>{(row,index)=><label><input type="checkbox" checked={selected().includes(row.record_id)} onChange={e=>setSelected(v=>e.currentTarget.checked?[...v,row.record_id]:v.filter(x=>x!==row.record_id))}/>来源 {index()+1} · {row.record_id}<small>　{String(row.fields.deviceName??row.fields.target_name??row.fields.bzdzmc??row.module)}</small></label>}</For>
  <div class="provider-form"><For each={Object.entries({person_identity:"一个人员身份号码（不进入模型）",lon:"经度",lat:"纬度",radius_m:"半径（米）",start:"开始时间（YYYY-MM-DD HH:mm:ss）",end:"结束时间（YYYY-MM-DD HH:mm:ss）",page:"明确查询页码"})}>{([key,title])=><Field label={title}><input autocomplete="off" value={scope()[key]??""} onInput={e=>setScope(v=>({...v,[key]:e.currentTarget.value}))}/></Field>}</For></div>
  <Field label="希望核对什么"><textarea value={goal()} maxlength={4000} onInput={e=>setGoal(e.currentTarget.value)} placeholder="例如：核对我选定位置的警情资料，半径500米。"/></Field>
  <Show when={taskID()}><Button onClick={()=>void exportTask("html")}>导出任务资料包 HTML</Button><Button onClick={()=>void exportTask("md")}>导出任务资料包 Markdown</Button></Show>
  <ErrorLine message={error()}/><Show when={uncertain()}><p>受理结果待确认。请查看原会话，不要重复提交。</p></Show>
  <Button disabled={props.disabled||busy()||uncertain()||!goal().trim()} onClick={()=>void submit()}>继续核对</Button>
 </details>
}
