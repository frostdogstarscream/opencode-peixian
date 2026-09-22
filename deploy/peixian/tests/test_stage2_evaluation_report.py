"""Evaluation evidence must be complete and fail closed, not just exit zero."""
import copy,importlib.util,json
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('stage2_evaluation',ROOT/'deploy/peixian/evaluate-stage2.py')
evaluation=importlib.util.module_from_spec(spec);spec.loader.exec_module(evaluation)

def observations():
    cases=[json.loads(x) for x in (ROOT/'specs/stage2-pr9a-evaluation-cases.jsonl').read_text().splitlines()]
    return {'schema':'peixian.evaluation-observations','version':'1.0','model_requests':0,'pytest_exit_code':0,'cases':{c['id']:{'split':c['split'],'category':c['category'],'error':None,'metrics':{k:True for k in evaluation.expected_metrics(c)}} for c in cases}}

def test_complete_gate():
    value=evaluation.summarize([observations()])
    assert value['status']=='passed' and value['cases']==300

@pytest.mark.parametrize('mutation,code',[('missing','incomplete_evaluation'),('duplicate','duplicate_or_unexpected_case'),('metric','missing_or_unexpected_metric'),('identity','case_identity_mismatch'),('boolean','invalid_metric')])
def test_invalid_receipt(mutation,code):
    receipt=observations();key=next(iter(receipt['cases']));entry=receipt['cases'][key];inputs=[receipt]
    if mutation=='missing':receipt['cases'].pop(key)
    if mutation=='duplicate':inputs.append(copy.deepcopy(receipt))
    if mutation=='metric':entry['metrics'].pop(next(iter(entry['metrics'])))
    if mutation=='identity':entry['split']='other'
    if mutation=='boolean':entry['metrics'][next(iter(entry['metrics']))]=1
    with pytest.raises(ValueError,match=code):evaluation.summarize(inputs)

@pytest.mark.parametrize('mutation',['exit','error','quality','split'])
def test_failed_gate(mutation):
    receipt=observations()
    if mutation=='exit':receipt['pytest_exit_code']=1
    elif mutation=='error':next(iter(receipt['cases'].values()))['error']='test_failed'
    elif mutation=='quality':
        for row in receipt['cases'].values():
            if 'query_mode_accuracy' in row['metrics']:row['metrics']['query_mode_accuracy']=False
    else:
        # Overall rate can pass while the smaller challenge split does not.
        row=next(x for x in receipt['cases'].values() if x['split']=='challenge' and 'query_mode_accuracy' in x['metrics'])
        row['metrics']['query_mode_accuracy']=False
    assert evaluation.summarize([receipt])['status']=='failed'

@pytest.mark.parametrize('key,value',[('schema','other'),('version','2'),('model_requests',1),('model_requests',False),('pytest_exit_code',False)])
def test_observation_contract(key,value):
    receipt=observations();receipt[key]=value
    with pytest.raises(ValueError,match='invalid_observation_contract'):evaluation.summarize([receipt])
