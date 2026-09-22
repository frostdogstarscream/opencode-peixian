import copy,importlib.util
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('governance',ROOT/'deploy/peixian/stage2-governance.py');g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)

def test_source_contract():
    if (ROOT/'specs/stage2-pr9c-release.json').exists():
        # New source must NOT validate as the already closed PR-9B candidate.
        # CI independently executes the original checker at its immutable commit.
        with pytest.raises(ValueError,match='closed_source_drift'):g.check_source(ROOT)
    else:assert g.check_source(ROOT)
def test_generated_rules():assert g.verify_rules(g.ruleset())
@pytest.mark.parametrize('kind',['inactive','bypass','branch','exclude','review','owner','push','conversation','stale','checks','app','strict','force'])
def test_protection_cannot_weaken(kind):
    r=g.ruleset();rules={x['type']:x for x in r['rules']};p=rules['pull_request']['parameters'];s=rules['required_status_checks']['parameters']
    if kind=='inactive':r['enforcement']='evaluate'
    elif kind=='bypass':r['bypass_actors']=[{'actor_type':'RepositoryRole','actor_id':5,'bypass_mode':'always'}]
    elif kind=='branch':r['conditions']['ref_name']['include']=['refs/heads/other']
    elif kind=='exclude':r['conditions']['ref_name']['exclude']=['*']
    elif kind=='review':p['required_approving_review_count']=0
    elif kind=='owner':p['require_code_owner_review']=False
    elif kind=='push':p['require_last_push_approval']=False
    elif kind=='conversation':p['required_review_thread_resolution']=False
    elif kind=='stale':p['dismiss_stale_reviews_on_push']=False
    elif kind=='checks':s['required_status_checks'].pop()
    elif kind=='app':s['required_status_checks'][0]['integration_id']=None
    elif kind=='strict':s['strict_required_status_checks_policy']=False
    else:r['rules']=[x for x in r['rules'] if x['type']!='non_fast_forward']
    with pytest.raises(ValueError):g.verify_rules(r)
