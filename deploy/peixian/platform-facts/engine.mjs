// Pure deterministic preparation; no model-written facts are accepted.
export function canonical(value) {
  if (Array.isArray(value)) return '['+value.map(canonical).join(',')+']';
  if (value && typeof value === 'object') return '{'+Object.keys(value).sort().map(k=>JSON.stringify(k)+':'+canonical(value[k])).join(',')+'}';
  return JSON.stringify(value);
}
const labels={night:'夜间观测',portrait:'同框与同行',funds:'资金流水',lookup:'明确关系',vehicle:'车辆记录',calls:'通话记录',composite:'已有关系引用'};
function local(time) {
  if (!/(Z|[+-]\d\d:\d\d)$/.test(time) || !Number.isFinite(Date.parse(time))) throw new Error('invalid_time');
  return new Date(Date.parse(time)+8*3600000).toISOString();
}
export function compile(context, responses) {
  const facts=[], summary=[], missing=[...context.limitations];
  const subject=context.subject_ref;
  const sources=new Set();
  const add=(id,statement,ids,time='',kind='record')=>facts.push({fact_id:id,statement,source_ids:ids,time,kind});
  for (const module of context.required_modules) {
    const data=responses[module];
    if (!data) {missing.push(labels[module]+'未成功取得，不将缺失视为零条或无同行。');continue;}
    const ids=new Set();
    for (const row of data.records) {if(ids.has(row.record_id)) throw new Error('duplicate_record_id');ids.add(row.record_id);sources.add(row.record_id);}
    const rows=data.records.filter(row=>{
      const belongs=module==='night'||module==='lookup' ? row.group_ref===subject : module==='portrait' ? row.member_ref===subject||row.co_member_ref===subject : row.member_ref===subject;
      if(!belongs)return false;
      return !row.occurred_at || (local(row.occurred_at) && Date.parse(row.occurred_at)>=Date.parse(context.window_start)&&Date.parse(row.occurred_at)<Date.parse(context.window_end));
    });
    const dates=[...new Set(rows.filter(x=>x.occurred_at).map(x=>local(x.occurred_at).slice(0,10)))].sort();
    const nights=rows.filter(x=>x.occurred_at&&(Number(local(x.occurred_at).slice(11,13))>=22||Number(local(x.occurred_at).slice(11,13))<6));
    summary.push({module,label:labels[module],count:rows.length,dates,night_count:nights.length});
    add('COUNT-'+module,`${subject} 的${labels[module]}为 ${rows.length} 条原始记录；涉及 ${dates.length} 个北京时间自然日，夜间 ${nights.length} 条。按记录计数，不等同独立事件数。`,rows.map(x=>x.record_id),'','count');
    for (const row of rows) {
      const at=row.occurred_at ? local(row.occurred_at).slice(0,19)+'+08:00' : '资料未提供时间';
      let detail='';
      if(module==='night') {
        const annotations=context.facts.filter(f=>f.source_document&&f.observation&&f.source_record_ids.includes(row.record_id));
        const states=[...new Set(annotations.map(f=>f.observation))];
        const state=states.length===1&&states[0]==='alone'?'明确独行观测（仅此观测片段，不代表作案）':states.length===1&&states[0]==='accompanied'?'明确同行观测':'同行状态无法判断';
        detail=`${state}；设备 ${row.device_ref}。`;
        if(module==='calls')detail=`通话原始记录；来源 ${row.record_id}。`;
      if(module==='composite')detail=`已有跨资料引用；来源 ${row.record_id}，引用 ${(row.source_record_ids||[]).join('、')}；未取得引用原始资料时不证明其内容。`;
      add(row.record_id,`${subject}，${at}，${detail}`,[row.record_id,...annotations.map(f=>f.source_document)],row.occurred_at);continue;
      }
      if(module==='portrait')detail=`${row.kind==='same_trip'?'明确同行':row.kind==='same_frame'?'同框（不据此推导同行）':'关系类型未知'}；记录主体 ${row.member_ref}，共同出现对象 ${row.co_member_ref}，设备 ${row.device_ref}。`;
      if(module==='funds')detail=`原始流水 ${row.transaction_ref}，${row.direction}，金额 ${row.amount_minor} 分，对手账户 ${row.counterparty_ref}；不配对合并，不认定资金用途。`;
      if(module==='vehicle')detail=`车辆 ${row.group_ref}，${row.direction}，设备 ${row.device_ref}；不能据不同时间共用车辆推导同乘。`;
      if(module==='lookup')detail=`明确关系 ${row.kind}，${row.group_ref} → ${row.member_ref}；无时间的关系只作背景，不纳入时段事件数。`;
      if(module==='calls')detail=`通话原始记录；来源 ${row.record_id}。`;
      if(module==='composite')detail=`已有跨资料引用；来源 ${row.record_id}，引用 ${(row.source_record_ids||[]).join('、')}；未取得引用原始资料时不证明其内容。`;
      add(row.record_id,`${subject}，${at}，${detail}`,[row.record_id,...(row.source_record_ids||[])],row.occurred_at||'');
    }
  }
  for (const f of context.facts) {
    if (!f.source_record_ids.every(id=>sources.has(id))) {missing.push(f.record_id+' 引用资料未取得，不能核对。');continue;}
    add(f.record_id,f.description,[...f.source_record_ids,...(f.source_document?[f.source_document]:[])],f.occurred_at,'context');
  }
  facts.sort((a,b)=>a.fact_id.localeCompare(b.fact_id,'en'));
  return {schema_version:'facts-v1',synthetic:true,scenario_id:context.scenario_id,subject_ref:subject,scenario_snapshot_id:context.snapshot_id,records_snapshot_id:context.records_snapshot_id,rule_version:'deterministic-facts-v1',window_start:context.window_start,window_end:context.window_end,timezone:'Asia/Shanghai',night_window:'22:00-06:00',data_status:context.required_modules.every(m=>responses[m])?'complete':'partial',summary,facts,missing};
}
export function checkClaims(table, claims) {
  if(!Array.isArray(claims)||claims.length>40)throw new Error('invalid_claims');
  const approved=[],rejected=[];
  const seen=new Set();
  for(const [index,claim] of claims.entries()){
    const fact=table.facts.find(f=>f.fact_id===claim?.fact_id);
    if(!claim||Object.keys(claim).sort().join(',')!=='fact_id,source_ids,statement'||!fact||seen.has(fact.fact_id)||claim.statement!==fact.statement||canonical(claim.source_ids)!==canonical(fact.source_ids)) {rejected.push({index,reason:'表述或来源不与事实表精确对应，未核验。'});continue;}
    seen.add(fact.fact_id);approved.push(fact);
  }
  return {schema_version:'checked-summary-v1',scenario_id:table.scenario_id,scenario_snapshot_id:table.scenario_snapshot_id,records_snapshot_id:table.records_snapshot_id,data_status:table.data_status,approved,rejected,missing:table.missing,notice:'仅 approved 中的固定表述经过代码核对；其他文字和改写未核验，不判定违法犯罪。'};
}
