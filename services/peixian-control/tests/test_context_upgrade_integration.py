"""Joint v6 -> v7 -> v8 upgrade with real encrypted history and empty-target restore."""
import sqlite3
from pathlib import Path
from test_backend_v6 import v6
from test_task_spec import task_env
from test_multi_agent import multi
from test_task_context import complete_data
from control.store import Store
from control import task_context
from control.agents.registry import require
from control.schema import validate


def backup(source,path):
    with sqlite3.connect(source) as old,sqlite3.connect(path) as dest:old.backup(dest)


def test_existing_run_context_upgrade_restore(multi,tmp_path,monkeypatch):
    s=multi[0];assert s.schema_version()==6
    rid=complete_data(multi);uid=multi[4]['uid']
    original=s.one('SELECT * FROM business_runs WHERE id=?',(rid,))
    identity=s.one('SELECT id,password,role,auth_version FROM users WHERE id=?',(uid,))
    # This fixture has no Docker worker; explicitly close its synthetic provision job.
    with s.tx() as db:
        db.execute("UPDATE jobs SET status='completed',recovery_required=0")
        db.execute("UPDATE job_attempts SET outcome='completed' WHERE outcome IS NULL")
        db.execute("UPDATE platform_state SET maintenance_mode='frozen' WHERE id=1")
    before6=tmp_path/'before6.sqlite3';backup(s.path,before6)
    args=(tmp_path/'db',tmp_path/'key',tmp_path/'worker',tmp_path/'admin')
    monkeypatch.setenv('PX_TASK_CONTEXT_V1','1');monkeypatch.setenv('PX_ALLOW_V7_MIGRATION','1')
    s7=Store(*args);assert s7.schema_version()==7
    ctx=task_context.ensure(s7,uid,'ses_multi',require('gambling-assistant'))
    assert ctx['last_data_run_id']==rid
    assert s7.one('SELECT * FROM business_runs WHERE id=?',(rid,))==original
    before7=tmp_path/'before7.sqlite3';backup(s7.path,before7)
    monkeypatch.setenv('PX_TASK_CLARIFICATION_V1','1');monkeypatch.setenv('PX_ALLOW_V8_MIGRATION','1')
    s8=Store(*args);assert s8.schema_version()==8
    assert task_context.ensure(s8,uid,'ses_multi',require('gambling-assistant'))==ctx
    assert s8.one('SELECT * FROM business_runs WHERE id=?',(rid,))==original
    with s8.read() as db:validate(db)
    for version,source in ((7,before7),(6,before6)):
        target=tmp_path/('restore'+str(version));target.mkdir();backup(source,target/'control.sqlite3')
        monkeypatch.delenv('PX_TASK_CLARIFICATION_V1',raising=False)
        if version==6:monkeypatch.delenv('PX_TASK_CONTEXT_V1',raising=False)
        restored=Store(target,*args[1:]);assert restored.schema_version()==version
        assert restored.one('SELECT id,password,role,auth_version FROM users WHERE id=?',(uid,))==identity
        assert restored.one('SELECT * FROM business_runs WHERE id=?',(rid,))==original
        if version==7:assert task_context.ensure(restored,uid,'ses_multi',require('gambling-assistant'))==ctx
    assert s8.schema_version()==8
