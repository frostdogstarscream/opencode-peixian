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


def test_gateway_control_plugin_http_compile_claim_and_historical_read(facts,chain,v6,tmp_path):
    store,uid,rid,_=facts;_,_,control=v6
    _,calls,_,url=chain
    row=store.one('SELECT * FROM business_runs WHERE id=?',(rid,))
    runtime=store.one('SELECT * FROM runtimes WHERE uid=?',(uid,))
    private=store.decrypt(runtime['spec']);runtime_key=private['runtime_key']
    applied={'plugins':[{'id':capability('night'),'version':'1.0.0','manifest':{'tools':[tool('night')]}}],
             'skills':[{'id':'night-skill','content':(PLUGINS/'skills/night/SKILL.md').read_text()}]}
    plan=build(applied,{'scenario_id':'DEMO-CASE-GAMBLING','effective_skill_ids':['night-skill']},{})
    with store.tx() as db:
        snapshot=store.decrypt(row['request_ciphertext']);snapshot['facts_plan']=plan
        db.execute('UPDATE business_runs SET request_ciphertext=? WHERE id=?',(store.encrypt(snapshot),rid))
    managed=tmp_path/'managed';managed.mkdir()
    folder=managed/'plugins'/capability('night')/'1.0.0';folder.mkdir(parents=True)
    shutil.copyfile(PLUGINS/'night/entry.mjs',folder/'entry.mjs')
    (managed/'platform-facts').mkdir();shutil.copyfile(ROOT/'deploy/peixian/platform-facts/engine.mjs',managed/'platform-facts/engine.mjs')
    # Transport adapter changes only the fixed test relay hostname; request_data
    # and exchange still run over HTTP in chain's policy server.
    (managed/'platform-client.mjs').write_text("export function createPlatform(){return {connections:{request:async(alias,input)=>{const r=await fetch("+json.dumps(url+'/night')+",{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(input)});if(!r.ok)throw new Error('denied');return r.json();}}};}")
    (managed/'plugin-tests.json').write_text(json.dumps({capability('night'):{'entry':str(folder/'entry.mjs'),'options':{},'platform_connections':{}}}))
    (tmp_path/'workspace').mkdir();(tmp_path/'files').mkdir()
    settings=Settings(tmp_path/'workspace',tmp_path/'files',managed,'synthetic-gateway-token','synthetic-agent-password',require_linux=False,
                      runtime_id=runtime['id'],revision=1,runtime_key=runtime_key)
    async def transport(request):
        if request.url.host=='control':
            reply=await asyncio.to_thread(control.post,request.url.path,headers={'X-Runtime-Key':request.headers['X-Runtime-Key']},json=json.loads(request.content))
            return httpx.Response(reply.status_code,json=reply.json())
        assert request.method=='GET' and request.url.path=='/session/ses_facts/message/msg_assistant'
        return httpx.Response(200,json={'info':{'id':'msg_assistant','sessionID':'ses_facts','parentID':row['message_id'],'role':'assistant'},'parts':[]})
    app=create_app(settings,transport=httpx.MockTransport(transport))
    token=hmac.new(settings.token.encode(),b'facts-agent-v1',hashlib.sha256).hexdigest()
    with TestClient(app) as client:
        gate=AdmissionGate(runtime['id'],1,clock=lambda:0);gate.mode='open';gate.deadline=4;gate.scopes={'intake':True,'egress':True}
        app.state.admission=gate;app.state.runtime_management=SimpleNamespace(gate=gate)
        body={'session_id':'ses_facts','message_id':'msg_assistant','tool':'peixian_prepare_scenario_facts','args':{'scenario_id':'DEMO-CASE-GAMBLING','methods':['night']}}
        assert client.post('/internal/facts/execute',json=body).status_code==401
        assert client.get('/health',headers={'X-Facts-Key':token}).status_code==401
        direct=client.post('/internal/facts/execute',json={**body,'tool':tool('night'),'args':{}},headers={'X-Facts-Key':token})
        assert direct.status_code==200,direct.text
        assert direct.json()['facts_table']['facts'] and calls==['night']
        persisted=store.decrypt(store.one('SELECT request_ciphertext FROM business_runs WHERE id=?',(rid,))['request_ciphertext'])
        assert persisted['facts_state']['table']['facts']
        reply=client.post('/internal/facts/execute',json=body,headers={'X-Facts-Key':token})
        assert reply.status_code==200,reply.text
        table=reply.json();assert table['data_status']=='complete' and table['summary'][0]['module']=='night'
        assert calls==['night']
        again=client.post('/internal/facts/execute',json=body,headers={'X-Facts-Key':token})
        assert again.status_code==200 and again.json()==table and calls==['night']
        claims=[{k:f[k] for k in ('fact_id','statement','source_ids')} for f in table['facts'][:3]]
        check={**body,'tool':'peixian_check_scenario_summary','args':{'scenario_id':'DEMO-CASE-GAMBLING','claims':claims}}
        checked=client.post('/internal/facts/execute',json=check,headers={'X-Facts-Key':token})
        assert checked.status_code==200,checked.text
        assert len(checked.json()['approved'])==len(claims) and calls==['night']
        forbidden={**body,'tool':tool('funds'),'args':{}}
        assert client.post('/internal/facts/execute',json=forbidden,headers={'X-Facts-Key':token}).status_code==409
        assert calls==['night'] and not gate.activities
    current=store.one('SELECT * FROM business_runs WHERE id=?',(rid,))
    projected=evidence(store.decrypt(current['request_ciphertext']),current)
    assert projected['cards'] and projected['summary_check']=='checked'
    assert projected['presentation']['evidence']
    assert any(c.get('provenance',{}).get('evidence_id') for c in projected['cards'])
    with store.tx() as db:
        db.execute('UPDATE business_runs SET evidence_ciphertext=? WHERE id=?',(store.encrypt(projected),rid))
        db.execute('DELETE FROM installs WHERE uid=?',(uid,));db.execute('DELETE FROM grants WHERE uid=?',(uid,))
    saved=read_evidence(store,store.one('SELECT * FROM business_runs WHERE id=?',(rid,)))
    assert saved['cards']==projected['cards'] and calls==['night']
