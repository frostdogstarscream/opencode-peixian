import hashlib,importlib.util,json
from pathlib import Path
import pytest
from test_backend_v6 import v6
from test_business_runs import setup_run
from control.seven_migration import publish,migrate,rollback,archive,state,OLD
from control.facts_runtime import MODULES,capability
from control.official_methods import BY_ID,identify
from control.store import encode
ROOT=Path(__file__).resolve().parents[3]

@pytest.fixture
def migration(v6,tmp_path):
    s,app,c,client,user,data,payload,applied=setup_run(v6)
    c.portal.call(app.state.run_coordinator.close)
    uid=user['uid'];manifest={'id':OLD,'version':'1.5.1','tools':[]}
    conf={'name':'demo','base_url':'http://127.0.0.1:19462','auth_type':'bearer','header_name':'','allowed_methods':['GET','POST'],'allowed_paths':['/health','/v1/demo/records/query'],'timeout_seconds':10,'max_response_bytes':1048576,'enabled':True}
    content=BY_ID['peixian.method.gambling']['content']
    with s.tx() as db:
        db.execute('INSERT INTO plugins VALUES(?,?,?,?,?,?,?,1)',(OLD,'1.5.1','old','',encode(manifest),'not-used','f'*64))
        db.execute('INSERT INTO connections VALUES(?,?,?,1)',('source',encode(conf),s.encrypt('synthetic-service-token')))
        db.execute('INSERT INTO plugin_connections VALUES(?,?,?,?)',(OLD,'1.5.1','peixian_records','source'))
        db.execute("INSERT INTO grants VALUES(?,'plugin',?)",(uid,OLD))
        db.execute('INSERT INTO installs VALUES(?,?,?,1,?,NULL)',(uid,OLD,'1.5.1',s.encrypt({})))
        db.execute("INSERT INTO skills VALUES(?,?,?,?,?,1,1,'[]')",('original',uid,'Original','','personal edited text'))
        db.execute("INSERT INTO skills VALUES(?,?,?,?,?,1,1,'[]')",('official',uid,'Official','',content))
    spec=importlib.util.spec_from_file_location('pack',ROOT/'deploy/peixian/examples/seven_data_plugins/package.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    packages=tmp_path/'packages';mod.build(packages)
    ready(s,uid)
    yield s,uid,packages,tmp_path/'receipt.enc'
    client.__exit__(None,None,None)

def ready(s,uid):
    with s.tx() as db:
        db.execute("UPDATE jobs SET status='completed',phase='finished',recovery_required=0 WHERE uid=?",(uid,))
        db.execute("UPDATE runtimes SET status='ready',revision=desired,gate_policy='open' WHERE uid=?",(uid,))

def test_publish_migrate_rollback_preserves_history_and_personal_content(migration):
    s,uid,packages,receipt=migration
    first=publish(s,packages);assert len(first)==7 and publish(s,packages)==first
    with s.read() as db:before=state(db,uid)
    result=migrate(s,uid,receipt);assert result['status']=='queued'
    assert migrate(s,uid,receipt)['status']=='already_applied'
    assert s.one("SELECT content FROM skills WHERE id='original'")['content']=='personal edited text'
    assert {r['plugin'] for r in s.rows('SELECT plugin FROM installs WHERE uid=?',(uid,))}=={capability(m) for m in MODULES}
    assert len(s.rows("SELECT * FROM skill_profiles WHERE source_type='official_v3'"))==6
    ready(s,uid)
    reverted=rollback(s,uid,receipt);assert reverted['status']=='queued'
    with s.read() as db:assert state(db,uid)==before
    assert rollback(s,uid,receipt)['status']=='already_rolled_back'

def test_rollback_refuses_new_personal_edits(migration):
    s,uid,packages,receipt=migration;publish(s,packages);migrate(s,uid,receipt);ready(s,uid)
    with s.tx() as db:db.execute("UPDATE skills SET content='new work' WHERE id='original'")
    with pytest.raises(ValueError,match='configuration_changed'):rollback(s,uid,receipt)
    assert s.one("SELECT content FROM skills WHERE id='original'")['content']=='new work'

def test_archive_requires_all_accounts_migrated_and_keeps_packages(migration):
    s,uid,packages,receipt=migration;publish(s,packages)
    with pytest.raises(ValueError,match='legacy_accounts'):archive(s)
    migrate(s,uid,receipt);ready(s,uid);assert archive(s)['status']=='archived'
    assert s.one('SELECT enabled FROM plugins WHERE id=?',(OLD,))['enabled']==0
    assert s.one('SELECT version FROM plugins WHERE id=?',(OLD,))['version']=='1.5.1'
    assert all(json.loads(x['config'])['enabled'] for x in s.rows("SELECT config FROM connections WHERE id<>'source'"))

def test_official_published_manifest_and_dependencies_are_consistent():
    for value in BY_ID.values():
        assert identify(value['content']) is value
        assert value['state']=='published'
        assert (ROOT/'deploy/peixian/examples/seven_data_plugins/skills'/value['method']/'SKILL.md').read_text()==value['content']
        assert all(x.startswith('peixian-records-') for x in value['dependency_ids'])
