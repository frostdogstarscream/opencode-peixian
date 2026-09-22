import copy
import uuid
import pytest
from fastapi import HTTPException
from test_analysis_tasks import task_provider,original,new_task
from test_provider_flow import provider,enabled,v6,task_env,multi
from test_multi_agent import prepare,submit
from test_provider_contract_v2 import response
from control import business_runs,trusted_results,task_report,run_reviews
from control.theft_provider_flow import preview
from control.theft_provider_state import ProviderState


def completed_task(env,monkeypatch):
    store=env[0];user=env[4];original(env,monkeypatch);tid=new_task(env)['analysis_task_id'];key=str(uuid.uuid4())
    signed=preview(store,user['uid'],'ses_multi',{'contract_version':'theft-provider-contract-v2','kind':'incidents','query':{'lon':'116.1','lat':'34.2','radius_m':500},'analysis_task_id':tid,'context_version':1,'step_request_id':key},env[-1],1)
    request,task=prepare(env,'theft-assistant','查询明确范围',client_request_id=key,provider_query={k:signed[k] for k in ('plan','confirmation')})
    _,row,_=submit(env,request,task);state=ProviderState(store);rid=row['id'];op=state.begin(user['uid'],rid,1)
    state.reserve(user['uid'],rid,1,op,'incidents');state.dispatch(user['uid'],rid,1,op,'incidents')
    state.complete(user['uid'],rid,1,op,'incidents','completed',response('incidents'));state.finish(user['uid'],rid,1,op)
    business_runs.set_state(store,rid,'completed','completed')
    return tid,rid,trusted_results.read(store,user['uid'],'ses_multi',rid)


def test_review_exact_record_corrections_and_readonly_export(task_provider,monkeypatch):
    env=task_provider;store=env[0];user=env[4];tid,rid,result=completed_task(env,monkeypatch)
    record=result['records'][0];ref={k:record[k] for k in ('record_id','snapshot_id')}
    body={'result_digest':trusted_results.digest(result),'status':'consistent','note':'来源核对 <script>alert(1)</script>','record_refs':[ref]}
    with pytest.raises(HTTPException):run_reviews.append(store,user,'ses_multi',rid,{**body,'record_refs':[]})
    with pytest.raises(HTTPException):run_reviews.append(store,user,'ses_multi',rid,{**body,'record_refs':[{**ref,'snapshot_id':'wrong'}]})
    first=run_reviews.append(store,user,'ses_multi',rid,body)
    before=task_report.snapshot(store,user['uid'],'ses_multi',tid)
    html=task_report.render(before,'html');md=task_report.render(before,'md')
    assert '<script>' not in html and '&lt;script&gt;' in html
    assert ref['record_id'] in html and ref['snapshot_id'] in md
    dispatch=copy.deepcopy(before['task']['budget'])
    next_body={**body,'note':'补充核对，保留原意见','status':'needs_information','supersedes':first['id']}
    with pytest.raises(HTTPException):run_reviews.append(store,user,'ses_multi',rid,{**next_body,'record_refs':[],'claim_ids':[result['claims'][0]['claim_id']]})
    second=run_reviews.append(store,user,'ses_multi',rid,next_body)
    after=task_report.snapshot(store,user['uid'],'ses_multi',tid)
    assert after['digest']!=before['digest'] and after['task']['budget']==dispatch
    assert len(after['runs'][0]['reviews'])==2 and second['supersedes']==first['id']
    assert trusted_results.digest(trusted_results.read(store,user['uid'],'ses_multi',rid))==body['result_digest']
    assert task_report.render(before,'html')==html
    with pytest.raises(HTTPException) as exc:task_report.snapshot(store,'other','ses_multi',tid)
    assert exc.value.status_code==404


def test_report_refuses_active_and_keeps_read_snapshot(task_provider,monkeypatch):
    env=task_provider;store=env[0];user=env[4];tid,rid,result=completed_task(env,monkeypatch)
    with store.read(snapshot=True) as db:
        view=task_report.ReadView(store,db)
        before=trusted_results.read(view,user['uid'],'ses_multi',rid)
        assert trusted_results.digest(before)==trusted_results.digest(result)
        with pytest.raises(AttributeError):view.tx()
    with store.tx() as db:db.execute("UPDATE business_runs SET status='reconciling' WHERE id=?",(rid,))
    with pytest.raises(HTTPException) as exc:task_report.snapshot(store,user['uid'],'ses_multi',tid)
    assert exc.value.status_code==409
