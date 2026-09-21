// Synthetic browser component harness; never a production build entry.
import { render } from "solid-js/web"
import { createSignal, Show } from "solid-js"
import {EventDiagramView} from "../src/EventDiagram"
import Panel from "../src/TrustedResultPanel"
import "../src/styles.css"
const context = { agent_id: "theft-assistant", generation: 1, version: 1, pending_clarification_id: "ticket-demo" }
let resolved = false,
  resolveCount = 0,
  queryCount = 0,
  mode = "ready"
const claim = {
  schema: "peixian.claim",
  version: "1.0",
  claim_id: "clm-demo",
  agent_id: "theft-assistant",
  type: "fact",
  statement: "演示对象甲于22:10有一条同框记录，不能据此确认同行。",
  source_ids: ["DEMO-001"],
  source_run_id: "run-demo",
  protected_fields: {},
  verification_status: "approved",
}
const result = {
  schema: "peixian.analysis-result",
  version: "2.0",
  run_id: "run-demo",
  agent: { id: "theft-assistant", version: "1.0.0" },
  task: {
    intent: "companions_check",
    target_refs: ["演示对象甲"],
    query_mode: "new_query",
    target_mode: "default_subject",
    methods: ["companions"],
    scenario_id: "DEMO-CASE-THEFT",
  },
  data_environment: "synthetic",
  data_usage: {
    status: "partial",
    queried: true,
    new_call_count: 1,
    reuse_count: 0,
    source_data_run_id: null,
    modules: [],
  },
  claims: [claim],
  records: [
    {
      record_id: "DEMO-001",
      module: "portrait",
      source_type: "portrait",
      data_source_id: "synthetic.portrait",
      snapshot_id: "DEMO-SNAPSHOT",
      occurred_at: "2026-09-22T22:10:00+08:00",
      kind: "same_frame",
    },
  ],
  missing: ["车辆资料未取得，不能解释为零条。"],
  versions: { scenario_snapshot_id: "DEMO-SCENE", records_snapshot_id: "DEMO-SNAPSHOT" },
  generated_at: "2026-09-22T15:00:00+08:00",
  narrative: {
    status: "conflicted",
    text: "未经核验的模型说明（隔离测试）",
    conflicts: [{ message: "说明与来源不一致" }],
    coverage: "fixed_rules",
  },
}
window.fetch = async (input, init) => {
  const url = String(input)
  let value: unknown = {}
  if (url.includes("/task-context")) value = { ...context, pending_clarification_id: resolved ? null : "ticket-demo" }
  else if (url.endsWith("/task"))
    value = {
      run_id: "run-demo",
      task_spec: result.task,
      agent_profile: mode === "cross-agent" ? {...result.agent,id:"gambling-assistant"} : result.agent,
      response: { clarification_id: "ticket-demo" },
    }
  else if (url.endsWith("/result"))
    value =
      mode === "legacy"
        ? { schema: result.schema, version: "legacy", run_id: "run-demo", status: "legacy" }
        : { ...result, claims: mode === "unknown" ? [] : result.claims, records: mode === "unknown" ? [] : result.records, data_usage: { ...result.data_usage, status: ["unknown","invalid-unknown"].includes(mode) ? "unknown" : "partial" } }
  else if (url.endsWith("/resolve") || url.endsWith("/cancel")) {
    const body = JSON.parse(String(init?.body))
    resolveCount++
    if (mode === "conflict" || body.context_version !== context.version)
      return new Response(JSON.stringify({ code: "task_context_changed", message: "确认已过期，请刷新" }), {
        status: 409,
        headers: { "content-type": "application/json" },
      })
    resolved = true
    context.version++
    value = { context_generation: 1, context_version: context.version, resume_required: url.endsWith("/resolve") }
  } else if (url.includes("/clarifications/"))
    value = {
      clarification_id: "ticket-demo",
      question: "请选择需要核对的演示车辆",
      options: [
        { id: "choice-a", label: "演示车辆甲" },
        { id: "choice-b", label: "演示车辆乙" },
      ],
      context_generation: 1,
      context_version: context.version,
      status: resolved ? "resolved" : "pending",
    }
  else return new Response("not found", { status: 404 })
  if (mode === "slow") await new Promise(resolve=>setTimeout(resolve,300))
  return new Response(JSON.stringify(value), { headers: { "content-type": "application/json" } })
}
function Harness() {
  const [revision, setRevision] = createSignal(0),
    [shown, setShown] = createSignal(true),
    [counts, setCounts] = createSignal("查询0次")
  return (
    <main style={{ "max-width": "1000px", margin: "20px auto", padding: "12px" }}>
      <h1>PR-8B 隔离组件验收</h1>
      <p>此页仅使用合成响应，不连接运行账号。</p>
      <label>
        测试状态
        <select
          onChange={(e) => {
            mode = e.currentTarget.value
            setRevision((v) => v + 1)
          }}
        >
          <option value="ready">部分资料</option>
          <option value="unknown">结果未知</option>
          <option value="legacy">旧结果</option>
          <option value="conflict">过期确认</option>
          <option value="slow">迟到结果</option><option value="invalid-unknown">矛盾未知结果</option><option value="cross-agent">跨助手结果</option>
        </select>
      </label>
      <button onClick={() => setShown((v) => !v)}>切换会话</button>
      <output aria-label="查询次数">{counts()}</output>
      <Show when={shown()}>
        <Panel
          sid="ses-demo"
          rid="run-demo"
          revision={String(revision())}
          agent="theft-assistant"
          disabled={false}
          onContext={() => setCounts(`确认${resolveCount}次，查询${queryCount}次`)}
          onContinue={() => {
            queryCount++
            setCounts(`确认${resolveCount}次，查询${queryCount}次`)
          }}
        />
      </Show>
      <EventDiagramView onSelect={()=>{}} value={{version:"1.0",status:"ready",run_id:"run-demo",scenario_id:"DEMO-CASE-THEFT",timezone:"Asia/Shanghai",window_start:"2026-09-22T22:00:00+08:00",window_end:"2026-09-23T06:00:00+08:00",scenario_snapshot_id:"DEMO-SCENE",records_snapshot_id:"DEMO-SNAPSHOT",rule_version:"v1",legend:"虚线仅表示时间先后",synthetic:true,total_nodes:1,aliases:[],missing:[],pages:[{number:1,mermaid:'flowchart TB\nn1["中文同框记录"]',nodes:[{id:"n1",number:"事件01",time:"2026-09-22T22:10:00+08:00",group:"night",subject:"演示对象甲",subject_ref:"DEMO-A",event:"同框观测",category:"portrait",source_ids:["DEMO-001"],message_id:"demo-message",notes:[]}],groups:[],edges:[]}]}} />
    </main>
  )
}
render(() => <Harness />, document.getElementById("root")!)
