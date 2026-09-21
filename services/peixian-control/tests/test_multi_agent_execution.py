"""Gateway/Control protocol + real Bun plugin/compiler + actual HTTP fixture service.

Only the Agent message identity read is synthetic. No model or live account is used.
"""
import asyncio
import copy
import hashlib
import hmac
import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from fastapi.testclient import TestClient
import httpx
import pytest
from test_backend_v6 import v6
from test_facts_runtime import facts
from test_seven_http_contract import chain,ROOT,PLUGINS
from control.facts_plan import build
from control.facts_runtime import capability,tool
from control.facts_evidence import evidence
from control.run_api import evidence as read_evidence
from gateway.app import create_app
from gateway.settings import Settings
from gateway.admission import AdmissionGate


from test_multi_agent import multi,prepare,submit
from test_task_spec import task_env

@pytest.mark.parametrize('method,text,modules',[
    ('vehicles','看看车辆记录',['vehicle']),
    ('theft','综合核对盗窃时空资料',['night','portrait','vehicle'])])
@pytest.mark.parametrize('gateway_restart',[False,True])
def test_theft_profile_real_plugin_http_and_control(multi,chain,tmp_path,method,text,modules,gateway_restart):
    store,_,control,_,user,_,_,applied=multi;uid=user['uid']
    request,task=prepare(multi,text=text)
    receipt,row,snapshot=submit(multi,request,task);rid=row['id'];plan=snapshot['facts_plan']
    assert plan['modules']==modules
    _,calls,_,url=chain
    runtime=store.one('SELECT * FROM runtimes WHERE uid=?',(uid,))
    runtime_key=store.decrypt(runtime['spec'])['runtime_key']
    managed=tmp_path/'managed';managed.mkdir()
    specs={}
    for module in modules:
        folder=managed/'plugins'/capability(module)/'1.0.0';folder.mkdir(parents=True)
        shutil.copyfile(PLUGINS/module/'entry.mjs',folder/'entry.mjs')
        specs[capability(module)]={'entry':str(folder/'entry.mjs'),'options':{},'platform_connections':{}}
    (managed/'platform-facts').mkdir();shutil.copyfile(ROOT/'deploy/peixian/platform-facts/engine.mjs',managed/'platform-facts/engine.mjs')
    # Transport adapter changes only the fixed test relay hostname; request_data
    # and exchange still run over HTTP in chain's policy server.
    (managed/'platform-client.mjs').write_text("export function createPlatform(){return {connections:{request:async(alias,input)=>{const r=await fetch("+json.dumps(url+'/')+"+input.json.module,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(input)});if(!r.ok)throw new Error('denied');return r.json();}}};}")
    (managed/'plugin-tests.json').write_text(json.dumps(specs))
    (tmp_path/'workspace').mkdir();(tmp_path/'files').mkdir()
    settings=Settings(tmp_path/'workspace',tmp_path/'files',managed,'synthetic-gateway-token','synthetic-agent-password',require_linux=False,
                      runtime_id=runtime['id'],revision=1,runtime_key=runtime_key)
    async def transport(request):
        if request.url.host=='control':
            reply=await asyncio.to_thread(control.post,request.url.path,headers={'X-Runtime-Key':request.headers['X-Runtime-Key']},json=json.loads(request.content))
            return httpx.Response(reply.status_code,json=reply.json())
        assert request.method=='GET' and request.url.path=='/session/ses_multi/message/msg_assistant'
        return httpx.Response(200,json={'info':{'id':'msg_assistant','sessionID':'ses_multi','parentID':row['message_id'],'role':'assistant'},'parts':[]})
    app=create_app(settings,transport=httpx.MockTransport(transport))
    token=hmac.new(settings.token.encode(),b'facts-agent-v1',hashlib.sha256).hexdigest()
    with TestClient(app) as client:
        gate=AdmissionGate(runtime['id'],1,clock=lambda:0);gate.mode='open';gate.deadline=4;gate.scopes={'intake':True,'egress':True}
        app.state.admission=gate;app.state.runtime_management=SimpleNamespace(gate=gate)
        if gateway_restart:
            with store.tx() as db:db.execute("UPDATE runtimes SET gateway_boot_id='old-gateway' WHERE uid=?",(uid,))
            headers={'X-Runtime-Key':runtime_key}
            old_identity={'runtime_id':runtime['id'],'revision':1,'gateway_boot_id':'old-gateway'}
            begun=control.post('/internal/runtime/facts',json={**old_identity,'action':'begin','session_id':'ses_multi','message_id':row['message_id']},headers=headers)
            assert begun.status_code==200,begun.text
            owner={**old_identity,'run_id':rid,'operation':begun.json()['operation']}
            assert control.post('/internal/runtime/facts',json={**owner,'action':'reserve','module':modules[0]},headers=headers).json()['reserved']
            # Missing/forged boot IDs never reclaim an existing operation.
            for boot in ('forged-gateway',''):
                denied=control.post('/internal/runtime/facts',json={**old_identity,'gateway_boot_id':boot,'action':'begin','session_id':'ses_multi','message_id':row['message_id']},headers=headers)
                assert denied.status_code in (409,422)
        with store.tx() as db:db.execute('UPDATE runtimes SET gateway_boot_id=? WHERE uid=?',(gate.boot_id,uid))
        body={'session_id':'ses_multi','message_id':'msg_assistant','tool':'peixian_prepare_scenario_facts','args':{'scenario_id':'DEMO-CASE-THEFT','methods':plan['methods']}}
        assert client.post('/internal/facts/execute',json=body).status_code==401
        assert client.get('/health',headers={'X-Facts-Key':token}).status_code==401
        if gateway_restart:
            stale=control.post('/internal/runtime/facts',json={**owner,'action':'finish'},headers=headers)
            assert stale.status_code==409
            recovered=client.post('/internal/facts/execute',json=body,headers={'X-Facts-Key':token})
            assert recovered.status_code==200,recovered.text
            assert recovered.json()['data_status']=='partial'
            assert calls==modules[1:]  # the reserved query is never sent again
            current=store.one('SELECT * FROM business_runs WHERE id=?',(rid,))
            snapshot=store.decrypt(current['request_ciphertext'])
            assert snapshot['facts_state']['modules'][modules[0]]['status']=='unknown'
            assert snapshot['facts_state']['operation'] is None
            assert snapshot['facts_state']['table']==recovered.json()
            projected=evidence(snapshot,current)
            assert projected['status']!='complete'
            again=client.post('/internal/facts/execute',json=body,headers={'X-Facts-Key':token})
            assert again.status_code==200 and calls==modules[1:]
            return
        direct=client.post('/internal/facts/execute',json={**body,'tool':tool(modules[0]),'args':{}},headers={'X-Facts-Key':token})
        assert direct.status_code==200,direct.text
        assert direct.json()['facts_table']['facts'] and calls==[modules[0]]
        if method=='funds':
            assert direct.json()['items'] and all(r['member_ref']=='赵衡' for r in direct.json()['items'])
            assert direct.json()['source_returned_count']>direct.json()['returned_count']
            assert direct.json()['facts_table']['subject_ref']=='赵衡'
        if method=='relations':assert direct.json()['facts_table']['data_status']!='complete'
        persisted=store.decrypt(store.one('SELECT request_ciphertext FROM business_runs WHERE id=?',(rid,))['request_ciphertext'])
        assert persisted['facts_state']['table']['facts']
        reply=client.post('/internal/facts/execute',json=body,headers={'X-Facts-Key':token})
        assert reply.status_code==200,reply.text
        table=reply.json();assert table['data_status']=='complete' and table['summary'][0]['module']==modules[0]
        assert calls==modules
        again=client.post('/internal/facts/execute',json=body,headers={'X-Facts-Key':token})
        assert again.status_code==200 and again.json()==table and calls==modules
        claims=[{k:f[k] for k in ('fact_id','statement','source_ids')} for f in table['facts'][:3]]
        check={**body,'tool':'peixian_check_scenario_summary','args':{'scenario_id':'DEMO-CASE-THEFT','claims':claims}}
        checked=client.post('/internal/facts/execute',json=check,headers={'X-Facts-Key':token})
        assert checked.status_code==200,checked.text
        assert len(checked.json()['approved'])==len(claims) and calls==modules
        forbidden={**body,'tool':tool('night' if method=='funds' else 'funds'),'args':{}}
        assert client.post('/internal/facts/execute',json=forbidden,headers={'X-Facts-Key':token}).status_code==409
        assert calls==modules and not gate.activities
    current=store.one('SELECT * FROM business_runs WHERE id=?',(rid,))
    projected=evidence(store.decrypt(current['request_ciphertext']),current)
    assert projected['cards'] and projected['summary_check']=='checked'
    if method=='funds':
        allowed={r['record_id'] for r in plan['records']['funds']['records'] if r['member_ref']=='赵衡'}
        assert all(set(card.get('source_ids',[]))<=allowed for card in projected['cards'])
        assert all(set(node['source_ids'])<=allowed for page in (projected['presentation'].get('diagram') or {}).get('pages',[]) for node in page['nodes'])
    assert projected['presentation']['evidence']
    assert any(c.get('provenance',{}).get('evidence_id') for c in projected['cards'])
    with store.tx() as db:
        db.execute('UPDATE business_runs SET evidence_ciphertext=? WHERE id=?',(store.encrypt(projected),rid))
        db.execute('DELETE FROM installs WHERE uid=?',(uid,));db.execute('DELETE FROM grants WHERE uid=?',(uid,))
    saved=read_evidence(store,store.one('SELECT * FROM business_runs WHERE id=?',(rid,)))
    assert saved['cards']==projected['cards'] and calls==modules
