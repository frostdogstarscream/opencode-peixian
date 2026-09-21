import copy
import pytest
from test_trusted_results import v6, enabled, finish, test_compiled_facts_roundtrip as compile_fixture
from test_multi_agent import multi
from test_task_spec import task_env
from test_control import context
from control import trusted_results as results
from control.trusted_narrative import review

@pytest.mark.parametrize('status',['not_started','confirmed','unknown','partial'])
def test_history_statement_requires_actual_historical_usage(status):
    value=review('本次使用历史可信结果，未重新查询。',[],{'status':status})
    assert value['status']=='conflicted'
    assert any(x['code']=='data_usage_conflict' for x in value['conflicts'])

def test_historical_phrase_accepted_only_with_history_receipt():
    assert review('本次使用历史可信结果，未重新查询。',[],{'status':'historical_evidence'})['status']=='verified'

def test_projection_rechecks_frozen_task_target_and_identity(enabled):
    compile_fixture(enabled,'gambling-assistant','看看资金')
    s=enabled[0];row=s.one('SELECT * FROM business_runs ORDER BY created DESC LIMIT 1')
    original=s.decrypt(row['request_ciphertext']);events=s.rows('SELECT * FROM run_events WHERE run_id=?',(row['id'],))
    assert any(c['type']=='fact' for c in results.build(row,original,events)['claims'])
    for key,value in [('target_refs',['DEMO-OTHER']),('agent_id','theft-assistant'),('domain','theft')]:
        changed=copy.deepcopy(original);changed['task_spec'][key]=value
        result=results.build(row,changed,events)
        assert not any(c['type']!='gap' for c in result['claims']),key
        assert result['data_usage']['status']=='rejected'

def test_read_rejects_wrong_environment_even_with_valid_digest(enabled):
    from fastapi import HTTPException
    row,_=finish(enabled);s=enabled[0]
    value=results.read(s,enabled[4]['uid'],'ses_multi',row['id'])
    value['data_environment']='production'
    with s.tx() as db:db.execute('UPDATE run_results SET result_ciphertext=?,result_digest=? WHERE run_id=?',(s.encrypt(value),results.digest(value),row['id']))
    with pytest.raises(HTTPException) as exc:results.read(s,enabled[4]['uid'],'ses_multi',row['id'])
    assert exc.value.detail['code']=='result_integrity_failed'
