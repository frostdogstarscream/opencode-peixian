import copy
import json
import pytest
from control.scenario_evidence import project
from control.scenario_facts import TABLES, PREPARE
from control.scenario_diagram import compile_pages, label


def values(scenario="DEMO-CASE-THEFT", partial=False):
    table=next(t for t in TABLES if t['scenario_id']==scenario and (t['data_status']=='partial' if partial else t['data_status']=='complete'))
    return [{'info':{'role':'user','id':'request'}},{'info':{'role':'assistant','id':'tool-message'},'parts':[{'type':'tool','tool':PREPARE,'state':{'status':'completed','input':{'scenario_id':scenario},'output':json.dumps(table)}}]}]


@pytest.mark.parametrize('scenario',['DEMO-CASE-THEFT','DEMO-CASE-GAMBLING'])
def test_canonical_diagram(scenario):
    result=project(values(scenario),True);d=result['diagram']
    assert d['status']=='ready' and d['total_nodes']>0
    cards={c['id'] for c in result['cards']}
    for page in d['pages']:
        ns={n['id']:n for n in page['nodes']}
        assert len(ns)<=20 and page['mermaid'].startswith('flowchart TB')
        for n in ns.values():assert n['source_ids'][0] in cards and n['message_id']=='tool-message'
        for edge in page['edges']:assert ns[edge['from']]['time']<ns[edge['to']]['time']
    nodes=[n for p in d['pages'] for n in p['nodes']]
    if scenario.endswith('THEFT'):
        assert '无法判断' in next(n for n in nodes if n['source_ids'][0]=='DEMO-NGT-001')['event']
        assert '独行' in next(n for n in nodes if n['source_ids'][0]=='DEMO-NGT-007')['event']
        assert d['case_window'] and d['case_source_ids']
    else:
        funds=[n for n in nodes if n['category']=='funds'];assert len(funds)==3
        assert next(n for n in funds if n['source_ids'][0]=='DEMO-FND-001')['event']=='收入 128.00 元'
        assert all(not n['time'] for n in nodes if n['category']=='lookup')


@pytest.mark.parametrize('kind',['forged','snapshot','incomplete','revoked','next_turn'])
def test_untrusted_result_no_diagram(kind):
    v=values();state=v[1]['parts'][0]['state'];data=json.loads(state['output'])
    if kind=='forged':data['facts'][0]['statement']='forged'
    if kind=='snapshot':data['records_snapshot_id']='other'
    state['output']=json.dumps(data)
    if kind=='incomplete':state['status']='running'
    if kind=='next_turn':v.append({'info':{'role':'user','id':'new'}})
    assert not project(v,kind!='revoked').get('diagram')


def test_paging_equal_time_unknown_and_safe_labels():
    nodes=[{'id':'n'+str(i),'group':'日期','time':'2026-09-14T22:00:00+08:00','subject':'对象甲','event':'同框'} for i in range(41)]
    nodes[-1]['time']=None;nodes[-1]['group']='时间未明确'
    pages=compile_pages(nodes)
    assert [len(p['nodes']) for p in pages]==[20,20,1]
    assert all(not p['edges'] for p in pages)
    assert len({n['number'] for p in pages for n in p['nodes']})==41
    assert '<' not in label('<script>"%%{init}-->()')


def test_partial_empty_has_no_invented_events():
    v=values(partial=True);d=project(v,True)['diagram']
    assert d['status'] in ('partial','empty')
    assert d['missing']


@pytest.mark.parametrize("scenario", ["DEMO-CASE-THEFT", "DEMO-CASE-GAMBLING"])
def test_v14_exact_snapshot_registry(scenario):
    from control.scenario_presentation import presentation
    table=next(t for t in TABLES if t["scenario_id"]==scenario and t["scenario_snapshot_id"]=="demo1003" and t["data_status"]=="complete")
    v=values(scenario);v[1]["parts"][0]["state"]["output"]=json.dumps(table)
    result=project(v,True);d=result["diagram"];p=presentation(result,v)
    assert d["status"]=="ready"
    assert d["records_snapshot_id"]=="demo1001" and d["scenario_snapshot_id"]=="demo1003"
    assert p["subject_ref"]=="林晓舟"
    nodes=[n for page in d["pages"] for n in page["nodes"]]
    assert all(n["source_ids"][0].startswith("demo") for n in nodes)
    if scenario.endswith("THEFT"):
        assert d["case_source_ids"]==["demo54","demo60"]
        assert "独行" in next(n for n in nodes if n["source_ids"][0]=="demo35")["event"]
        assert any("东津巷18号" in note for n in nodes for note in n["notes"])
        assert p["evidence"][-1]["value"]==1
    forged=copy.deepcopy(table);forged["records_snapshot_id"]="DEMO-SNAPSHOT-20260918-01"
    v[1]["parts"][0]["state"]["output"]=json.dumps(forged)
    assert not project(v,True).get("diagram")
