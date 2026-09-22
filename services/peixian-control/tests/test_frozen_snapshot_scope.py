import copy
import pytest
from shared.task_scope import validate_target

def plan():
    return {'agent_task':{'schema_version':'task-spec-v3','target_refs':['DEMO-P1'],'target_mode':'scenario_subject','methods':['funds'],'query_mode':'new_query'},
        'task_target':{'status':'resolved','contract_version':'method-target-v2','target_refs':['DEMO-P1'],'target_mode':'scenario_subject','filter_fields':[]},
        'scenario':{'subject_ref':'DEMO-P1','records_snapshot_id':'DEMO-OLD-SNAPSHOT'},
        'methods':['funds'],'modules':['funds'],'records':{'funds':{'module':'funds','snapshot_id':'DEMO-OLD-SNAPSHOT'}}}

def test_historical_snapshot_does_not_require_current_fixture():
    validate_target(plan())

@pytest.mark.parametrize('mutation',['snapshot','module','missing','extra','empty','wrong_shape'])
def test_inconsistent_frozen_contract_rejected(mutation):
    value=plan()
    if mutation=='snapshot':value['records']['funds']['snapshot_id']='DEMO-OTHER'
    elif mutation=='module':value['records']['funds']['module']='night'
    elif mutation=='missing':value['records'].pop('funds')
    elif mutation=='extra':value['records']['night']={'module':'night','snapshot_id':'DEMO-OLD-SNAPSHOT'}
    elif mutation=='empty':value['scenario']['records_snapshot_id']=''
    else:value['records']['funds']=[]
    with pytest.raises(ValueError,match='task_records_snapshot_mismatch'):validate_target(value)

def test_pre_taskspec_historical_plan_is_not_reinterpreted():
    validate_target({'scenario':{},'records':{}})
