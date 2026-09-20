"""Typed presentation over validated evidence; never render model-authored findings."""
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from .scenario_evidence import DATA

SOURCES = json.loads(Path(__file__).with_name("scenario_presentation_sources.json").read_text())
NAMES = {"DEMO-CASE-GAMBLING": "涉赌案件资料整理", "DEMO-CASE-THEFT": "盗窃案件时空资料核对"}
CODES = {"scope", "night", "portrait", "funds", "lookup", "vehicle", "check"}


def clock(ms):
    return datetime.fromtimestamp(ms / 1000, timezone(timedelta(hours=8))).strftime("%H:%M:%S")


def presentation(result, messages):
    starts = [i for i,m in enumerate(messages) if m.get("info", {}).get("role") == "user"]
    if not starts:
        return None
    parts = [p for m in messages[starts[-1]+1:] if m.get("info", {}).get("role") == "assistant" for p in m.get("parts", []) if p.get("type") == "tool"]
    known = [p for p in parts if p.get("tool") in ("peixian_prepare_scenario_facts", "peixian_check_scenario_summary", "peixian_get_scenario_context")]
    inputs = [p.get("state", {}).get("input", {}) for p in known]
    if any(not isinstance(a, dict) or not isinstance(a.get("scenario_id"), str) for a in inputs):
        return None
    ids = {a["scenario_id"] for a in inputs}
    if len(ids) != 1 or next(iter(ids)) not in NAMES or result["status"] == "unavailable":
        return None
    sid = next(iter(ids))
    from .scenario_versions import select, sources, supported_sources
    meta = result.get("scenario") or {}
    data = select(sid, meta.get("snapshot_id"), meta.get("records_snapshot_id"), DATA) if meta else DATA
    if data is None: return None
    source_map = sources(data, SOURCES)
    context = data["scenarios"][sid]; subject = context["subject_ref"]
    theft = sid == "DEMO-CASE-THEFT"
    cards = {c["id"]: c for c in result["cards"]}
    modules = {m: [row for row in data["records"][m]["records"] if row["record_id"] in cards] for m in context["required_modules"]}
    acquired = {x["label"] for x in result["summary"]}
    from .scenario_evidence import LABELS
    acquired.update(LABELS[m] for m in context["required_modules"] if "COUNT-"+m in cards)
    trace = {}; prepare_status = None; check_status = None
    for p in known:
        state = p.get("state", {}); name = p.get("tool")
        if name == "peixian_prepare_scenario_facts": prepare_status = state.get("status")
        if name == "peixian_check_scenario_summary": check_status = state.get("status")
        events = state.get("metadata", {}).get("peixian_trace", [])
        if state.get("status") == "completed":
            try: events = json.loads(state.get("output", "{}")).get("execution_trace", [])
            except (ValueError, AttributeError): events = []
        bounds = state.get("time", {})
        lo, hi = bounds.get("start"), bounds.get("end")
        if not isinstance(events, list) or len(events)>32: continue
        previous = 0
        for e in events:
            if not isinstance(e, dict) or set(e)!={"code", "status", "at"}: continue
            code, status, at = e["code"], e["status"], e["at"]
            permitted = {"check"} if name == "peixian_check_scenario_summary" else {"scope", *context["required_modules"]}
            if code not in CODES or code not in permitted or status not in ("running", "completed", "failed") or type(at) is not int: continue
            if not 1500000000000 <= at <= 4102444800000 or at < previous: continue
            if not isinstance(lo,(int,float)) or at < lo-1000 or at>lo+600000 or (isinstance(hi,(int,float)) and at>hi+1000): continue
            previous=at; trace[code] = e
    groups = [("scope", "确认案件范围" if theft else "确认资料范围", ["scope"], "确认对象、观察时段与资料范围"),
              ("night", "查询夜间记录", ["night"], "检索观察范围内的夜间记录"),
              ("portrait", "核对同行状态" if theft else "核对同行记录", ["portrait"], "区分明确同行、同框与无法判断的观测"),
              ("related", "核对车辆与地点" if theft else "整理资金与关系", ["vehicle"] if theft else ["funds", "lookup"], "核对车辆记录与明确地点关系" if theft else "整理原始流水与已有关系资料"),
              ("check", "生成研判结果", ["check"], "核对事实与来源，生成结构化结果")]
    process = []
    for key,title,codes,detail in groups:
        rows=[trace.get(code) for code in codes]
        states=[e["status"] if e else None for e in rows]
        state="pending"
        if "failed" in states: state="failed"
        elif all(x=="completed" for x in states): state="completed"
        elif any(x is not None for x in states): state="running"
        elif key=="scope" and result.get("scenario"): state="completed"
        elif key=="check": state="failed" if check_status=="error" or result.get("summary_check")=="rejected" else "completed" if result.get("summary_check")=="checked" else "running" if check_status=="running" else "pending"
        elif all(LABELS.get(code) in acquired for code in codes): state="completed"
        elif prepare_status in ("error","completed") and key!="scope": state="failed"
        elif prepare_status=="running" and key=="scope": state="running"
        if key=="scope" and prepare_status=="completed" and not result.get("scenario"): state="failed"
        if key=="check" and state=="completed" and result.get("summary_check")!="checked": state="failed"
        if key not in ("scope","check") and prepare_status=="completed" and not all(LABELS.get(code) in acquired for code in codes): state="failed"
        at=max((e["at"] for e in rows if e),default=None)
        process.append({"id":key,"title":title,"detail":detail,"status":state,"time":clock(at) if at else "—"})
    clues=[]; evidence=[]; conclusions=[]
    window=context["window_start"][:10]+" 至 "+context["window_end"][:10]+"（结束不含）"
    def add(kind,title,value,unit,summary,rows,discoveries):
        cid="finding-"+kind
        sources=[{"type":kind,"label":x["record_id"],"content":x.get("occurred_at", "时间未提供"),"source_ids":[x["record_id"]]} for x in rows]
        evidence.append({"type":kind,"title":title,"value":value if value is not None else "未获取" if kind!="place" else "无法核对","unit":unit if value is not None else "","summary":window,"items":[summary],"clue_id":cid})
        if value is None: return
        clue={"id":cid,"type":kind,"title":title,"headline":summary,"summary":summary,"discoveries":discoveries,"evidence":sources}
        clues.append(clue)
        if result.get("summary_check")=="checked" or (result["status"]=="complete" and not prepare_status):
            conclusions.append({"text":summary,"clue_id":cid,"source_ids":[x["record_id"] for x in rows]})
    nights=modules.get("night",[])
    add("trajectory","夜间记录",len(nights) if LABELS["night"] in acquired else None,"条",f"观察范围内取得 {len(nights)} 条夜间记录。",nights,["夜间口径：北京时间22:00至次日06:00。","记录数量不等于独立活动次数。"])
    companions=[x for x in modules.get("portrait",[]) if x.get("kind")=="same_trip"]
    people={x["co_member_ref"] if x["member_ref"]==subject else x["member_ref"] for x in companions}
    add("companion","同行人员",len(people) if LABELS["portrait"] in acquired else None,"人",f"明确同行记录涉及 {len(people)} 名去重同行对象，共 {len(companions)} 条记录。",companions,["同框不计为同行；缺少同行记录不表示独行。"])
    if theft:
        vehicles=modules.get("vehicle",[]);count=len({x['group_ref'] for x in vehicles})
        add("vehicle","关联车辆",count if LABELS['vehicle'] in acquired else None,"辆",f"取得 {len(vehicles)} 条车辆记录，涉及 {count} 辆车辆。",vehicles,["不同时间使用同一车辆不表示同乘。"])
        places=[p for p in source_map.get(sid,{}).get("places",[]) if all(x in supported_sources(context, cards) for x in p["source_ids"])]
        rows=[{"record_id":x,"occurred_at":cards[x]["time"]} for p in places for x in p['source_ids'] if x in cards]
        add("place","关联地点",len({p['id'] for p in places}) if places else None,"个",f"有明确来源的地点映射 {len(places)} 项；记录点与登记地点为相邻关系。",rows,["未提供测量距离，不能推算米数。"])
    else:
        funds=modules.get('funds',[]);lookup=modules.get('lookup',[])
        add("funds","资金流水",len(funds) if LABELS['funds'] in acquired else None,"条",f"取得 {len(funds)} 条原始资金流水。",funds,["逐条保留，不合并双边记录，不推断资金用途。"])
        add("relation","明确关系",len(lookup) if LABELS['lookup'] in acquired else None,"条",f"取得 {len(lookup)} 条明确关系记录。",lookup,["关系记录仅说明资料中的对应关系。"])
    # Observations are explicit structured fields, with sources from this exact snapshot.
    observations = [f for f in context["facts"] if f["record_id"] in cards and f.get("observation") in ("alone", "accompanied", "unknown")]
    if theft and observations:
        names = {"alone": "明确独行观测（仅本片段）", "accompanied": "明确同行观测", "unknown": "同行状态无法判断"}
        summary = "；".join((f.get("occurred_at") or "时间未明确")[11:16] + " " + names[f["observation"]] for f in observations)
        refs = [f["record_id"] for f in observations]
        clues.append({"id":"finding-observation","type":"trajectory","title":"观测状态","headline":summary,"summary":summary,"discoveries":["独行仅限有明确来源的该次观测片段。"],"evidence":[{"type":"trajectory","label":x,"content":cards[x]["time"],"source_ids":cards[x]["source_ids"]} for x in refs]})
        if result.get("summary_check")=="checked": conclusions.append({"text":summary,"clue_id":"finding-observation","source_ids":refs})
    missing=["部分资料未取得或核对未完成，请查看步骤状态。"] if result['status']!='complete' else []
    missing += ["观察范围仅覆盖两个日期。", "地点无距离测量依据。" if theft else "流水缺少跨账户唯一配对依据。"]
    return {"diagram":result.get("diagram"),"version":"1.0","turn_id":result.get('turn_id',messages[starts[-1]].get('info',{}).get('id','')),"title":NAMES[sid],"process":process,"conclusions":conclusions[:5],"evidence":evidence,"clues":clues,"missing":missing,"subject_ref":subject}
