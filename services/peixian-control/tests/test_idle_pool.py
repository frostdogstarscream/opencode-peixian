import pytest
from control.idle_pool import candidates, submit
from control.store import now, ident
from control.orchestration import Orchestration
from control.worker_api import runtime_spec
from test_runtime_pool import pool, account, begin
from test_r2_orchestration import applying, observation, complete


@pytest.fixture
def idle(pool):
    s,args=pool
    s.pool_settings.update(idle_pause_enabled=True,idle_timeout_seconds=60,min_ready_seconds=0,resume_cooldown_seconds=0)
    with s.tx() as db: db.execute('UPDATE platform_state SET pool_policy_version=3,idle_pause_enabled=1')
    uid=account(s);begin(s,uid)
    engine=Orchestration(s)
    job=engine.claim(runtime_spec)['job'];applying(engine,job)
    engine.boot(job['id'],{'lease':job['lease'],'attempt':job['attempt'],'operation_id':ident(),'runtime_id':job['runtime_id'],'gateway_boot_id':'gateway','relay_boot_id':'relay'})
    complete(engine,job,ok=True,observation_id=observation(engine,job,running=True,boot='gateway'))
    with s.tx() as db: db.execute("UPDATE runtimes SET gate_policy='open' WHERE uid=?",(uid,))
    return s,engine,uid


def sample(s):
    c=candidates(s)['items'][0]
    return {'uid':c['uid'],'state_version':c['state_version'],'gateway_boot_id':c['gateway_boot_id'],
            'observed_at':now(),'idle_proof':{'complete':True,'sequence':4,'idle_seconds':61},'activity_count':0,'complete':True}


def test_candidate_is_conditional_deduplicated_and_does_not_release(idle):
    s,e,uid=idle;data=sample(s)
    result=submit(s,data); assert result['accepted']
    assert not submit(s,data)['accepted']
    assert s.one('SELECT reserved FROM runtimes WHERE uid=?',(uid,))['reserved']==1
    job=e.claim(runtime_spec)['job']
    assert job['reason']=='idle_timeout' and job['idle_activity_version']==4
    body={'lease':job['lease'],'attempt':job['attempt'],'operation_id':ident()}
    receipt=e.cancel_idle(job['id'],body)
    assert e.cancel_idle(job['id'],body)==receipt
    r=s.one('SELECT * FROM runtimes WHERE uid=?',(uid,))
    assert r['reserved']==1 and r['stop_reason']=='none'
    assert s.one('SELECT status FROM jobs WHERE id=?',(job['id'],))['status']=='cancelled'


@pytest.mark.parametrize('field,value',[('complete',False),('activity_count',1),('idle_proof',None),('idle_proof',{'complete':True,'sequence':4,'idle_seconds':59})])
def test_unknown_busy_or_short_idle_never_queues(idle,field,value):
    s,e,uid=idle;data=sample(s);data[field]=value
    assert not submit(s,data)['accepted']
    assert not s.rows("SELECT * FROM jobs WHERE reason='idle_timeout'")


def test_maintenance_and_disabled_policy_do_not_create_candidates(idle):
    s,e,uid=idle
    with s.tx() as db: db.execute("UPDATE platform_state SET maintenance_mode='frozen'")
    assert candidates(s)['items']==[]
    with s.tx() as db: db.execute("UPDATE platform_state SET maintenance_mode='normal',idle_pause_enabled=0")
    assert candidates(s)['items']==[]


def test_admin_pause_supersedes_automatic_cancellation(idle):
    from fastapi import HTTPException
    s,e,uid=idle;submit(s,sample(s));job=e.claim(runtime_spec)['job']
    s.queue(uid,'pause')
    with pytest.raises(HTTPException): e.cancel_idle(job['id'],{'lease':job['lease'],'attempt':job['attempt'],'operation_id':ident()})


def idle_observation(e, job, sequence=4):
    current=e.query(job['id'])['job']
    data={'observation_id':ident(),'runtime_id':job['runtime_id'],'job_id':job['id'],'attempt':job['attempt'],
          'lease':job['lease'],'state_version':current['state_version'],'host_boot_id':'synthetic-host',
          'gateway_boot_id':current['gateway_boot_id'],'gate_epoch':current['gate_epoch'],'observed_at':e.clock(),
          'components':dict.fromkeys(('agent','gateway','relay'),'running'),'mutation_state':'idle','complete':True,
          'accepting':False,'egress_closed':True,'activity_count':0,'applied_revision':job['revision'],
          'spec_digest':job['spec_digest'],'evidence_ref':ident(),
          'idle_proof':{'complete':True,'sequence':sequence,'idle_seconds':61}}
    e.observe(data)
    return data['observation_id']


def test_short_activity_after_gate_close_cancels_without_mutation(idle):
    from fastapi import HTTPException
    from test_r2_orchestration import phase
    s,e,uid=idle;submit(s,sample(s));job=e.claim(runtime_spec)['job']
    phase(e,job,'draining')
    phase(e,job,'closing',idle_observation(e,job))
    observed=idle_observation(e,job,sequence=6)
    with pytest.raises(HTTPException): phase(e,job,'applying',observed)
    e.cancel_idle(job['id'],{'lease':job['lease'],'attempt':job['attempt'],'operation_id':ident()})
    assert s.one('SELECT reserved FROM runtimes WHERE uid=?',(uid,))['reserved']==1


def test_idle_pause_requires_final_proof_and_cannot_cancel_after_applying(idle):
    from fastapi import HTTPException
    from test_r2_orchestration import phase
    s,e,uid=idle;submit(s,sample(s));job=e.claim(runtime_spec)['job']
    phase(e,job,'draining')
    phase(e,job,'closing',idle_observation(e,job))
    phase(e,job,'applying',idle_observation(e,job))
    with pytest.raises(HTTPException): e.cancel_idle(job['id'],{'lease':job['lease'],'attempt':job['attempt'],'operation_id':ident()})
    complete(e,job,ok=True,observation_id=observation(e,job))
    r=s.one('SELECT * FROM runtimes WHERE uid=?',(uid,))
    assert r['reserved']==0 and r['status']=='paused' and r['stop_reason']=='idle_timeout'


def test_idle_disabled_retires_only_queued_automatic_work(idle):
    s,e,uid=idle;submit(s,sample(s))
    with s.tx() as db: db.execute('UPDATE platform_state SET idle_pause_enabled=0')
    assert e.claim(runtime_spec)['job'] is None
    assert s.one('SELECT reserved,stop_reason FROM runtimes WHERE uid=?',(uid,))=={'reserved':1,'stop_reason':'none'}


def test_idle_protocol_requires_worker_capability(idle):
    from client_helpers import TestClient
    from control.app import create_app
    s,e,uid=idle
    headers={'X-Worker-Key':s.worker_key,'X-Peixian-Protocol':'2','X-Peixian-Runtime-Mode':'on_demand',
             'X-Peixian-Capabilities':'runtime_pool_v1,runtime_pool_wait_v1'}
    with TestClient(create_app(s)) as c:
        assert c.post('/internal/worker/scheduler/tick',headers=headers).status_code==409
        headers['X-Peixian-Capabilities']+=',idle_activity_v1'
        assert c.post('/internal/worker/scheduler/tick',headers=headers).status_code==200
