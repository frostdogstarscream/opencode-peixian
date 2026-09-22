import pytest
from fastapi import HTTPException
from test_provider_flow import provider, enabled, v6, task_env, multi, accept
from control.theft_provider_state import ProviderState
from control import business_runs, trusted_results


@pytest.mark.parametrize('status', ['completed','unknown','cancelled'])
def test_reserved_is_not_sent_and_rejection_is_not_unknown(provider,status):
    s=provider[0];uid=provider[4]['uid'];_,_,row,_=accept(provider)
    st=ProviderState(s);op=st.begin(uid,row['id'],1)
    st.reserve(uid,row['id'],1,op,'incidents')
    pending=st.read(uid,row['id'],1)['state']['modules']['incidents']
    assert pending['dispatch_attempts']==0 and not pending['may_have_sent']
    if status!='cancelled':
        st.dispatch(uid,row['id'],1,op,'incidents')
        with pytest.raises(HTTPException):st.dispatch(uid,row['id'],1,op,'incidents')
    actual=st.complete(uid,row['id'],1,op,'incidents',status,{'code':500} if status=='completed' else None)
    expected='rejected' if status=='completed' else status
    assert actual==expected
    st.finish(uid,row['id'],1,op)
    business_runs.set_state(s,row['id'],'completed','completed')
    result=trusted_results.read(s,uid,'ses_multi',row['id'])
    assert result['data_usage']['status']==expected
    module=result['data_usage']['modules'][0]
    assert module['reservation_count']==1
    assert module['dispatch_attempts']==int(status!='cancelled')
    assert module['response_count']==int(status=='completed')
    assert result['records']==[]
