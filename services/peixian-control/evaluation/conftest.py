import sys,json,hashlib
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"tests"))
from test_control import context
from test_task_spec import task_env
from test_multi_agent import multi
from test_trusted_results import v6,enabled
OBSERVATIONS={}
def pytest_addoption(parser):
    parser.addoption('--evaluation-split',default='all',choices=['all','development','fixed','challenge'])
    parser.addoption('--evaluation-output',default=None)
def pytest_generate_tests(metafunc):
    if 'case' not in metafunc.fixturenames:return
    manifest=json.loads((ROOT/'specs/stage2-pr9a-evaluation-set.json').read_text())
    path=ROOT/'specs/stage2-pr9a-evaluation-cases.jsonl'
    assert hashlib.sha256(path.read_bytes()).hexdigest()==manifest['sha256'],'frozen evaluation set changed'
    cases=[json.loads(x) for x in path.read_text().splitlines()]
    assert len(cases)==300 and len({x['id'] for x in cases})==300
    assert {k:sum(x['split']==k for x in cases) for k in manifest['splits']}==manifest['splits']
    split=metafunc.config.getoption('--evaluation-split')
    metafunc.parametrize('case',[x for x in cases if split=='all' or x['split']==split],ids=lambda x:x['id'])
def pytest_sessionfinish(session,exitstatus):
    path=session.config.getoption('--evaluation-output')
    if not path:return
    value={'schema':'peixian.evaluation-observations','version':'1.0','pytest_exit_code':int(exitstatus),'split':session.config.getoption('--evaluation-split'),'cases':OBSERVATIONS,'model_requests':0}
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
