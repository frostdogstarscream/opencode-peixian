import json
import uuid
import httpx
from test_backend_v6 import v6
from test_business_runs import setup_run
from test_control import P,create_user,login_user
from control.skill_drafts import finalize
from control import business_runs as runs


def test_draft_generation_review_private_save_and_replay(v6):
    s,app,admin,client,user,data,payload,applied=setup_run(v6)
    client.portal.call(app.state.run_coordinator.close)
    old=app.state.http;calls=[]
    def transport(request):
        calls.append(request)
        if '/internal/runtime/runs/' in request.url.path:return httpx.Response(200,json={'protocol':'durable_run_v1','receipt':None})
        return httpx.Response(200,json={'id':'ses_draft','directory':'/workspace'})
    app.state.http=httpx.AsyncClient(transport=httpx.MockTransport(transport))
    try:
        body={'requirement':'整理夜间资料的方法，使用参数替代具体对象','model_id':data['model_id'],'client_request_id':str(uuid.uuid4())}
        response=client.post(P+'/skill-drafts/from-requirement',json=body)
        assert response.status_code==202,response.text
        draft=response.json();did=draft['id'];rid=draft['run_id']
        assert draft['status']=='generating' and rid
        snapshot=s.decrypt(s.one('SELECT request_ciphertext FROM business_runs WHERE id=?',(rid,))['request_ciphertext'])
        assert snapshot['payload']['tools']=={'*':False}
        assert client.post(P+'/skill-drafts/from-requirement',json=body).json()['id']==did
        assert len([x for x in calls if x.method=='POST' and x.url.path=='/session'])==1
        assert client.post(P+'/skill-drafts/from-requirement',json={**body,'requirement':'different'}).status_code==409
        candidate={'name':'资料核对方法','description':'通用方法','content':'按输入范围核对来源并展示缺口。','dependency_ids':[],'input_schema':{'type':'object'},'default_rules':['不得推断未提供事实']}
        runs.set_state(s,rid,'completed','completed')
        finalize(s,rid,[{'info':{'role':'assistant'},'parts':[{'type':'text','text':json.dumps(candidate,ensure_ascii=False)}]}])
        assert client.get(P+'/skill-drafts/'+did).json()['status']=='ready'
        invalid=client.patch(P+'/skill-drafts/'+did,json={'content':'来源DEMO-FND-001 张某'});assert invalid.status_code==422
        test=client.post(P+'/skill-drafts/'+did+'/test',json={}).json()
        assert test['ok'] and test['model_executed'] is False
        saved=client.post(P+'/skill-drafts/'+did+'/save',json={});assert saved.status_code==200,saved.text
        sid=saved.json()['skill_id'];assert s.one('SELECT enabled FROM skills WHERE id=?',(sid,))['enabled']==0
        again=client.post(P+'/skill-drafts/'+did+'/save',json={});assert again.json()['skill_id']==sid
        assert s.one('SELECT count(*) AS n FROM skills WHERE uid=?',(user['uid'],))['n']==1
        assert client.get(P+'/capabilities').json()['items'][0]['unavailable_reason']=='disabled'
        create_user(admin,'person-b');other=login_user(app,'person-b')
        try:assert other.get(P+'/skill-drafts/'+did).status_code==404
        finally:other.__exit__(None,None,None)
    finally:
        client.portal.call(app.state.http.aclose);app.state.http=old;client.__exit__(None,None,None)


def test_draft_model_output_with_facts_needs_edit_before_save(v6):
    s,app,admin,client,user,data,payload,applied=setup_run(v6)
    try:
        from control.store import now
        did=uuid.uuid4().hex
        accepted=runs.submit(s,user,'ses_draft',data,payload,applied,1);rid=accepted['run_id']
        with s.tx() as db:db.execute("INSERT INTO skill_drafts(id,uid,request_key,request_hash,source_type,status,content_ciphertext,run_id,created,updated) VALUES(?,?,?,?,'requirement','generating',?,?,?,?)",(did,user['uid'],str(uuid.uuid4()),'hash',s.encrypt({}),rid,now(),now()))
        runs.set_state(s,rid,'completed','completed')
        candidate={'name':'通用方法','content':'张某使用DEMO-CAL-001','description':'','dependency_ids':[],'input_schema':{},'default_rules':[]}
        finalize(s,rid,[{'info':{'role':'assistant'},'parts':[{'type':'text','text':json.dumps(candidate,ensure_ascii=False)}]}])
        assert client.get(P+'/skill-drafts/'+did).json()['status']=='needs_review'
        assert client.post(P+'/skill-drafts/'+did+'/save',json={}).status_code==409
        assert client.patch(P+'/skill-drafts/'+did,json={'content':'使用输入参数核对已有资料'}).status_code==200
        assert client.post(P+'/skill-drafts/'+did+'/save',json={}).status_code==200
    finally:client.__exit__(None,None,None)
