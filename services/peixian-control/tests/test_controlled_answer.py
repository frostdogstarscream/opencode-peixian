import asyncio,copy,hashlib,json
from types import SimpleNamespace
import pytest
from test_alignment5 import vehicle
from test_trusted_results import enabled,v6
from test_task_spec import task_env
from test_multi_agent import multi,prepare,submit
from test_control import P,create_user,login_user
from control import business_runs as runs,trusted_results,controlled_answer as answer
from control.run_api import attach_results
from control.live_text import LiveTextCache
from control.trusted_report import render
from test_live_text import message_event,part_event,delta_event


def completed(env,legacy=False):
    s,uid,row,state,op,table=vehicle(env)
    state.save_table(uid,row['id'],1,op,table);state.finish(uid,row['id'],1,op)
    with s.tx() as db:
        frozen=s.decrypt(db.execute('SELECT request_ciphertext FROM business_runs WHERE id=?',(row['id'],)).fetchone()['request_ciphertext'])
        frozen['model_narrative']="I'll query the vehicle. 对象写错，42次同乘已经实施盗窃。"
        if legacy:frozen.pop('answer_policy_version',None)
        db.execute('UPDATE business_runs SET assistant_id=?,request_ciphertext=? WHERE id=?',('msg_answer',s.encrypt(frozen),row['id']))
    runs.set_state(s,row['id'],'completed','completed')
    row=runs.owned(s,uid,'ses_multi',row['id'])
    return s,uid,row,trusted_results.read(s,uid,'ses_multi',row['id'])


def test_answer_blocks_prose_in_messages_results_and_reports(enabled):
    s,uid,row,result=completed(enabled)
    assert result['answer']['version']==answer.VERSION
    assert result['answer']['items'] and len(result['answer']['items'])<=5
    assert result['narrative']['text'] is None and result['narrative']['status']=='conflicted'
    frozen=s.decrypt(row['request_ciphertext'])
    assert "I'll query" in frozen['model_narrative']
    assert frozen['effective_system_prompt_sha256']==hashlib.sha256(frozen['payload']['system'].encode()).hexdigest()
    native=[{'info':{'id':'msg_answer','role':'assistant','parentID':row['message_id'],'sessionID':'ses_multi'},'parts':[{'type':'text','text':frozen['model_narrative']},{'type':'reasoning','text':'secret reasoning'}]}]
    messages=attach_results(s,uid,native,'ses_multi')
    wire=json.dumps(messages,ensure_ascii=False)
    assert "I'll query" not in wire and 'secret reasoning' not in wire and '42次同乘' not in wire
    assert messages[0]['parts'][-1]['text']==answer.markdown(result['answer'])
    for format in ('md','html'):
        report=render(result,[],format)
        assert "I'll query" not in report and '42次同乘' not in report
        assert result['answer']['summary'] in report
    response=enabled[3].get(P+'/sessions/ses_multi/runs/'+row['id']+'/result')
    assert response.json()==result
    from control.openapi import build_openapi
    from test_openapi import validator
    validator(build_openapi(enabled[1]),'TrustedResultResponse').validate(result)
    assert trusted_results.read(s,uid,'ses_multi',row['id'])==result
    create_user(enabled[2],'answer-other');other=login_user(enabled[1],'answer-other')
    try:
        for suffix in ('result','report','claims'):
            assert other.get(P+'/sessions/ses_multi/runs/'+row['id']+'/'+suffix).status_code==404
    finally:other.__exit__(None,None,None)


def test_legacy_not_rewritten(enabled):
    s,uid,row,result=completed(enabled,legacy=True)
    assert 'answer' not in result and "I'll query" in result['narrative']['text']
    before=trusted_results.digest(result)
    assert "I'll query" in render(result,[],'md')
    assert trusted_results.digest(trusted_results.read(s,uid,'ses_multi',row['id']))==before


def test_history_answer_never_queries_and_binds_original_claims(enabled):
    s,uid,first,result=completed(enabled)
    request,task=prepare(enabled,'theft-assistant','继续解释刚才的结果')
    _,row,snap=submit(enabled,request,task)
    assert snap['answer_policy_version']==answer.VERSION and not snap.get('facts_plan')
    runs.set_state(s,row['id'],'completed','completed')
    value=trusted_results.read(s,uid,'ses_multi',row['id'])
    assert value['data_usage']['new_call_count']==0
    assert value['answer']['items'] and all(x['source_run_id']==first['id'] for x in value['answer']['items'])
    assert '没有重新查询' in value['answer']['summary']


def test_clarification_uses_controlled_reply_without_data(enabled):
    request,task=prepare(enabled,'theft-assistant','查询张三最近30天车辆记录')
    _,row,snap=submit(enabled,request,task)
    result=trusted_results.read(enabled[0],enabled[4]['uid'],'ses_multi',row['id'])
    assert result['answer']['status']=='needs_input' and not result['answer']['items']
    assert result['answer']['next_steps'] and result['data_usage']['queried'] is False


def test_ordinary_chat_unchanged(enabled):
    request,task=prepare(enabled,'theft-assistant','你好')
    _,_,snapshot=submit(enabled,request,task)
    assert 'answer_policy_version' not in snapshot


def test_cache_and_stream_never_publish_unverified_text(enabled):
    request,task=prepare(enabled,'theft-assistant','看看车辆记录');_,row,_=submit(enabled,request,task)
    cache=LiveTextCache();uid=enabled[4]['uid'];cache.acquire(uid,'stream')
    class Work:
        async def run(self,fn,*args):return fn(*args)
    app=SimpleNamespace(state=SimpleNamespace(db_work=Work(),store=enabled[0],live_text=cache))
    event=message_event(1,sid='ses_multi',mid='msg_stream')
    event['payload']['properties']['info']['parentID']=row['message_id']
    async def check():
        await answer.observe(app,uid,event,'stream')
        await answer.observe(app,uid,part_event(2,sid='ses_multi',mid='msg_stream',text="I'll query"),'stream')
        await answer.observe(app,uid,delta_event(3,' fabricated',sid='ses_multi',mid='msg_stream'),'stream')
    asyncio.run(check())
    assert not cache.parts
    from control.streams import change_notice
    assert 'query' not in json.dumps(change_notice(event))
    values=[{'info':{'id':'msg_stream','role':'assistant','parentID':row['message_id'],'time':{'created':row['created']*1000}},'parts':[{'type':'text','text':'BAD'}]},
      {'info':{'id':'old','role':'assistant','time':{'created':0}},'parts':[{'type':'text','text':'old text'}]}]
    rendered=attach_results(enabled[0],uid,values,'ses_multi')
    by_id={m['info']['id']:m for m in rendered}
    assert not by_id['msg_stream']['parts'] and by_id['old']['parts'][0]['text']=='old text'


@pytest.mark.parametrize('observation,expected',[('same_frame','同框'),('same_trip','明确同行'),('same_vehicle','明确同乘'),('unknown','无法判断')])
def test_relations_not_upgraded(observation,expected):
    c={'claim_id':'c','type':'fact','template_id':'portrait.record.v1','verification_status':'approved','source_run_id':'run','source_ids':['r'],
       'statement':'fabricated crime','protected_fields':{'record_id':'r','observation':observation,'subject_refs':['A'],'co_member_ref':'B'}}
    sentence=answer.text(c)
    assert expected in sentence and 'fabricated' not in sentence


@pytest.mark.parametrize('amount,expected',[(1,'0.01'),(123456789012345678,'1234567890123456.78'),(-1,'-0.01')])
def test_money_exact_and_unknown_kept(amount,expected):
    c={'type':'fact','template_id':'funds.record.v1','verification_status':'approved','source_ids':['r'],
       'protected_fields':{'record_id':'r','amount_minor':amount,'direction':'unknown','subject_refs':['A']}}
    assert expected+' 元' in answer.text(c) and '收支方向未明确' in answer.text(c)


@pytest.mark.parametrize('usage,status',[('unknown','unavailable'),('in_flight','unavailable'),('not_started','unavailable'),('rejected','unavailable')])
def test_unknown_never_zero(usage,status):
    value=answer.build({'data_usage':{'status':usage},'claims':[],'records':[],'missing':['来源未提供']},{'task_spec':{'query_mode':'new_query'}},{'status':'completed'})
    assert value['status']==status and not value['items'] and '零条' not in value['summary']


def test_synthetic_sources_and_text_escaped():
    value={'version':answer.VERSION,'summary':'<script>alert(1)</script>','items':[],'missing':['[x](javascript:evil)'],'next_steps':[]}
    assert '<script>' not in answer.markdown(value) and '[x]' not in answer.markdown(value)
    assert '不受支持' in answer.markdown({'version':'future'})


@pytest.mark.parametrize('state,execution,expected',[('confirmed','completed','ready'),('partial','completed','partial'),('confirmed','failed','partial'),('confirmed','cancelled','partial')])
def test_zero_record_and_terminal_states(state,execution,expected):
    claim={'claim_id':'c','source_run_id':'r','verification_status':'approved','type':'computed','template_id':'vehicle.summary.v1','source_ids':[],
           'protected_fields':{'record_count':0,'date_count':0,'night_count':0,'subject_refs':['A']}}
    value=answer.build({'data_usage':{'status':state},'claims':[claim],'records':[],'missing':[]},{'task_spec':{'query_mode':'new_query'}},{'status':execution})
    assert value['status']==expected and '本次范围内' in value['items'][0]['text']
    assert '没有发生' not in value['items'][0]['text']


def test_unbound_claim_and_unknown_template_rejected():
    c={'type':'fact','template_id':'vehicle.record.v1','verification_status':'approved','source_ids':['other'],'protected_fields':{'record_id':'r'}}
    assert answer.text(c) is None
    c.update(template_id='model.invented');assert answer.text(c) is None


def test_fixed_limitations_are_not_model_assertions():
    value=answer.build({'data_usage':{'status':'not_started'},'claims':[],'records':[],'missing':['同框不能推导为同行。','资料不足以判断是否实施盗窃。']},{'task_spec':{'query_mode':'new_query'}},{'status':'completed'})
    assert value['missing']==['同框不能推导为同行。','资料不足以判断是否实施盗窃。']
    assert value['status']=='unavailable'
