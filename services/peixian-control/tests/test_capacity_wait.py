"""Persistent capacity queue tests against real isolated SQLite transactions."""
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi import HTTPException
from control.store import Store
from control.runtime_pool import start, stop, scheduler_tick, promote_waiters, public_status
from control.schema import validate
from test_runtime_pool import pool, account, begin


@pytest.fixture
def waiting(pool):
    s, args = pool
    # Empty synthetic database, explicit offline policy transition.
    with s.tx() as db:
        db.execute("UPDATE platform_state SET capacity_wait_enabled=1,pool_policy_version=2 WHERE id=1")
        validate(db)
    return s, args


def cancel(s, uid):
    with s.tx() as db:
        return stop(s, db, uid, expected_state_version=public_status(s,db,uid)['state_version'])


def test_waiting_fifo_deduplication_restart_and_release(waiting):
    s, args = waiting
    users = [account(s, str(i)) for i in range(5)]
    results = [begin(s, uid) for uid in users]
    assert [r['job']['status'] for r in results] == ['queued','queued','waiting_capacity','waiting_capacity','waiting_capacity']
    expiry = s.one('SELECT capacity_expires_at FROM jobs WHERE id=?',(results[2]['job']['id'],))
    assert begin(s,users[2])['job']['id'] == results[2]['job']['id']
    assert s.one('SELECT capacity_expires_at FROM jobs WHERE id=?',(results[2]['job']['id'],)) == expiry
    restarted = Store(*args, runtime_mode='on_demand')
    cancel(restarted, users[0])
    assert s.one('SELECT status FROM jobs WHERE id=?',(results[2]['job']['id'],))['status']=='queued'
    assert s.one('SELECT status FROM jobs WHERE id=?',(results[3]['job']['id'],))['status']=='waiting_capacity'
    assert s.one('SELECT count(*) n FROM runtimes WHERE reserved=1')['n']==2
    assert not s.rows('SELECT * FROM job_attempts')


def test_competing_last_slot_and_stop_promotion_race(waiting):
    s,_=waiting
    users=[account(s,str(i)) for i in range(4)]
    begin(s,users[0])
    with ThreadPoolExecutor(max_workers=3) as w:
        results=list(w.map(lambda u: begin(s,u),users[1:]))
    assert sum(r['job']['status']=='queued' for r in results)==1
    with ThreadPoolExecutor(max_workers=2) as w:
        list(w.map(lambda u: cancel(s,u),users[:2]))
    scheduler_tick(s)
    assert s.one('SELECT sum(reserved) n FROM runtimes')['n']<=2
    assert not s.rows("SELECT uid FROM jobs WHERE status IN ('waiting_capacity','queued','running') AND action IN ('resume','provision') GROUP BY uid HAVING count(*)>1")


def test_expiration_does_not_renew_or_allocate(waiting):
    s,_=waiting
    users=[account(s,str(i)) for i in range(3)]
    result=[begin(s,u) for u in users][-1]
    job=s.one('SELECT * FROM jobs WHERE id=?',(result['job']['id'],))
    with s.tx() as db:
        promote_waiters(s,db,timestamp=job['capacity_expires_at'])
    assert s.one('SELECT error FROM jobs WHERE id=?',(job['id'],))['error']=='capacity_wait_expired'
    assert not s.one('SELECT reserved FROM runtimes WHERE uid=?',(users[-1],))['reserved']
    newer=begin(s,users[-1])
    assert newer['job']['id'] != job['id']


@pytest.mark.parametrize('mode',['frozen','repair_only'])
def test_maintenance_does_not_promote(waiting,mode):
    s,_=waiting
    users=[account(s,str(i)) for i in range(3)]
    jobs=[begin(s,u)['job']['id'] for u in users]
    with s.tx() as db:
        db.execute('UPDATE platform_state SET maintenance_mode=? WHERE id=1',(mode,))
    cancel(s,users[0]); scheduler_tick(s)
    assert s.one('SELECT status FROM jobs WHERE id=?',(jobs[2],))['status']=='waiting_capacity'


def test_pause_disable_cancel_and_queue_limit(waiting):
    s,_=waiting
    s.pool_settings['max_waiting_requests']=1
    users=[account(s,str(i)) for i in range(4)]
    jobs=[begin(s,u)['job']['id'] for u in users[:3]]
    with pytest.raises(HTTPException) as e: begin(s,users[3])
    assert e.value.status_code==429
    s.update_user(users[2], {'active':False})
    assert s.one('SELECT status FROM jobs WHERE id=?',(jobs[2],))['status']=='cancelled'
    begin(s,users[3])
    s.queue(users[3],'pause')
    assert s.user(users[3])['runtime']['manual_stop_reason']=='admin'
    cancel(s,users[0]); scheduler_tick(s)
    assert not s.one('SELECT reserved FROM runtimes WHERE uid=?',(users[3],))['reserved']


def test_no_barging_after_missed_release_and_unknown_blocks(waiting):
    s,_=waiting
    users=[account(s,str(i)) for i in range(4)]
    jobs=[begin(s,u)['job']['id'] for u in users[:3]]
    # Model a committed confirmed release whose notification was lost.
    with s.tx() as db:
        db.execute("UPDATE jobs SET status='cancelled' WHERE id=?",(jobs[0],))
        db.execute('UPDATE runtimes SET reserved=0 WHERE uid=?',(users[0],))
    fourth=begin(s,users[3])
    assert s.one('SELECT status FROM jobs WHERE id=?',(jobs[2],))['status']=='queued'
    assert fourth['job']['status']=='waiting_capacity'
    with s.tx() as db: db.execute('UPDATE platform_state SET capacity_healthy=0 WHERE id=1')
    cancel(s,users[1]); scheduler_tick(s)
    assert s.one('SELECT status FROM jobs WHERE id=?',(fourth['job']['id'],))['status']=='waiting_capacity'


def test_policy_downgrade_rejected_and_historical_migration_unchanged(waiting):
    s,args=waiting
    with pytest.raises(ValueError): Store(*args,runtime_mode='on_demand',runtime_pool={'capacity_wait_enabled':False})
    from control.migrations_v5 import validate as old_validate
    with s.read() as db:
        validate(db)
        with pytest.raises(ValueError): old_validate(db)


def test_offline_disable_keeps_waiters_cancellable_and_expirable(waiting, monkeypatch):
    s,args=waiting
    users=[account(s,str(i)) for i in range(5)]
    jobs=[begin(s,u)['job']['id'] for u in users[:4]]
    with s.tx() as db:
        db.execute("UPDATE platform_state SET maintenance_mode='frozen' WHERE id=1")
    cancel(s,users[0]); cancel(s,users[1])
    monkeypatch.setenv('PX_ALLOW_POOL_POLICY_CHANGE','1')
    disabled=Store(*args,runtime_mode='on_demand',runtime_pool={'capacity_wait_enabled':False})
    assert disabled.maintenance_status()['pool_policy_version']==2
    with disabled.tx() as db:
        db.execute("UPDATE platform_state SET maintenance_mode='normal' WHERE id=1")
        assert public_status(disabled,db,users[2])['waiting']
        validate(db)
    scheduler_tick(disabled)
    assert disabled.one('SELECT sum(reserved) n FROM runtimes')['n']==0
    assert begin(disabled,users[2])['job']['id']==jobs[2]
    with pytest.raises(HTTPException) as e: begin(disabled,users[4])
    assert e.value.detail['code']=='runtime_wait_disabled'
    cancel(disabled,users[2])
    with disabled.tx() as db:
        db.execute('UPDATE jobs SET capacity_expires_at=1 WHERE id=?',(jobs[3],))
    scheduler_tick(disabled)
    assert disabled.one('SELECT error FROM jobs WHERE id=?',(jobs[3],))['error']=='capacity_wait_expired'
    assert begin(disabled,users[4])['job']['status']=='queued'
    assert Store(*args,runtime_mode='on_demand',runtime_pool={'capacity_wait_enabled':False}).maintenance_status()['pool_policy_version']==2


def test_waiting_old_worker_rejected_before_attempt(waiting):
    from client_helpers import TestClient
    from control.app import create_app
    s,_=waiting
    begin(s,account(s))
    headers={'X-Worker-Key':s.worker_key,'X-Peixian-Protocol':'2','X-Peixian-Runtime-Mode':'on_demand','X-Peixian-Capabilities':'runtime_pool_v1'}
    with TestClient(create_app(s)) as c:
        assert c.post('/internal/worker/claim',headers=headers).status_code==409
        assert not s.rows('SELECT * FROM job_attempts')
        headers['X-Peixian-Capabilities'] += ',runtime_pool_wait_v1'
        assert c.post('/internal/worker/claim',headers=headers).status_code==200


def test_expired_waiter_never_promoted_beyond_cleanup_batch(waiting):
    s,_=waiting
    s.pool_settings['scheduler_batch']=1
    users=[account(s,str(i)) for i in range(5)]
    jobs=[begin(s,u)['job']['id'] for u in users]
    with s.tx() as db:
        db.execute("UPDATE jobs SET capacity_expires_at=1 WHERE status='waiting_capacity'")
    cancel(s,users[0])
    for _ in range(5): scheduler_tick(s)
    assert not s.rows("SELECT * FROM jobs WHERE id IN (?,?,?) AND status<>'cancelled'",tuple(jobs[2:]))


def test_security_repair_keeps_slot_with_waiter_and_duplicate_receipt(waiting, monkeypatch):
    from control.orchestration import Orchestration
    from control.worker_api import runtime_spec
    from control.runtime_security import block_runtime
    from control.store import ident
    from test_r2_orchestration import applying, observation, complete
    monkeypatch.setenv('MAX_RUNTIMES','1')
    s,_=waiting
    a,b=account(s,'a'),account(s,'b')
    begin(s,a)
    engine=Orchestration(s)
    job=engine.claim(runtime_spec)['job']; applying(engine,job)
    engine.boot(job['id'],{'lease':job['lease'],'attempt':job['attempt'],'operation_id':ident(),'runtime_id':job['runtime_id'],'gateway_boot_id':'gateway','relay_boot_id':'relay'})
    complete(engine,job,ok=True,observation_id=observation(engine,job,running=True,boot='gateway'))
    waiter=begin(s,b)['job']['id']
    with s.tx() as db: block_runtime(s,db,a)
    s.queue(a,'pause',reason='security')
    pause=engine.claim(runtime_spec)['job']; applying(engine,pause)
    payload={'lease':pause['lease'],'attempt':pause['attempt'],'operation_id':ident(),'ok':True,'observation_id':observation(engine,pause)}
    receipt=engine.complete(pause['id'],payload)
    assert engine.complete(pause['id'],payload)==receipt
    assert s.one('SELECT sum(reserved) n FROM runtimes')['n']==1
    assert s.one('SELECT reserved FROM runtimes WHERE uid=?',(a,))['reserved']==1
    assert s.one('SELECT status FROM jobs WHERE id=?',(waiter,))['status']=='waiting_capacity'
    assert not s.rows('SELECT * FROM capacity_release_receipts')


def test_scheduler_recovers_after_real_sqlite_lock(waiting):
    import asyncio
    import sqlite3
    from types import SimpleNamespace
    from control.concurrency import WorkPool
    from control.runtime_pool import scheduler_loop
    s,_=waiting
    users=[account(s,str(i)) for i in range(3)]
    jobs=[begin(s,u)['job']['id'] for u in users]
    s.busy_timeout_ms=5
    s.pool_settings['scheduler_tick_seconds']=.01
    async def run():
        external=sqlite3.connect(s.path,isolation_level=None)
        external.execute('BEGIN IMMEDIATE')
        external.execute('UPDATE runtimes SET reserved=0 WHERE uid=?',(users[0],))
        external.execute("UPDATE jobs SET status='cancelled' WHERE id=?",(jobs[0],))
        app=SimpleNamespace(state=SimpleNamespace(store=s,pool_stop=asyncio.Event(),db_work=WorkPool(1,1,1,'test-pool')))
        task=asyncio.create_task(scheduler_loop(app))
        try:
            async with asyncio.timeout(3):
                while not getattr(app.state,'pool_failures',0): await asyncio.sleep(.005)
            external.commit()
            async with asyncio.timeout(3):
                while s.one('SELECT status FROM jobs WHERE id=?',(jobs[2],))['status']!='queued': await asyncio.sleep(.005)
            assert not task.done()
        finally:
            external.close();app.state.pool_stop.set();await task;await app.state.db_work.close()
    asyncio.run(run())


def test_thousand_metadata_accounts_do_not_require_gateway_observations(waiting):
    from control.orchestration import Orchestration
    from control.runtime_pool import inventory_targets, record_inventory
    from control.store import now
    s,_=waiting
    password=s.passwords.hash('synthetic-only-password')
    for i in range(1000): s.create_user_prehashed('metadata-'+str(i),password)
    assert Orchestration(s).reconcile_candidates()['items']==[]
    with s.tx() as db:
        db.execute("UPDATE platform_state SET capacity_healthy=0,freeze_reason='runtime_observation_unknown'")
        targets=inventory_targets(db)
    assert len(targets['items'])==1000
    assert record_inventory(s,{'host_boot_id':'synthetic-host','observed_at':now(),'registry_digest':targets['registry_digest'],'complete':True,'resources':[]})['capacity_healthy']
