import copy,json
import pytest
from test_trusted_results import enabled,v6
from test_task_spec import task_env
from test_multi_agent import multi,prepare,submit
from test_control import P,create_user,login_user
from test_controlled_answer import completed
from control import migrations_v10
from control.trusted_results import digest
from control.store import now
@pytest.fixture
def reviews(enabled):
    s,*_=enabled
    with s.tx() as db:migrations_v10.migrate(db,fresh=True,timestamp=now())
    return enabled

def test_reviews_owner_append_only_and_reports(reviews):
    s,uid,row,result=completed(reviews);client=reviews[3]
    path=P+'/sessions/ses_multi/runs/'+row['id']
    before=s.one('SELECT result_digest FROM run_results WHERE run_id=?',(row['id'],))['result_digest']
    assert client.get(path+'/reviews').json()['unreviewed']
    body={'result_digest':digest(result),'status':'consistent','note':'已核对来源 <script>bad()</script>','claim_ids':[result['claims'][0]['claim_id']]}
    headers={'Idempotency-Key':'review-first-001'}
    first=client.post(path+'/reviews',json=body,headers=headers)
    assert first.status_code==201,first.text
    assert client.post(path+'/reviews',json=body,headers=headers).json()==first.json()
    assert client.post(path+'/reviews',json={**body,'note':'不同'},headers=headers).status_code==409
    assert client.post(path+'/reviews',json={**body,'result_digest':'x'},headers={'Idempotency-Key':'review-wrong-digest'}).status_code==409
    assert client.post(path+'/reviews',json={**body,'claim_ids':['fake']},headers={'Idempotency-Key':'review-wrong-claim'}).status_code==422
    second=client.post(path+'/reviews',json={**body,'status':'needs_information','note':'补充核对','supersedes':first.json()['id']},headers={'Idempotency-Key':'review-second-001'})
    assert second.status_code==201,second.text
    assert client.get(path+'/reviews').json()['total']==2
    assert client.delete(path+'/reviews/'+first.json()['id']).status_code in (404,405)
    assert s.one('SELECT result_digest FROM run_results WHERE run_id=?',(row['id'],))['result_digest']==before
    report=client.get(path+'/report?format=html');assert report.status_code==200,report.text
    assert '人工复核意见' in report.text and '<script>bad()' not in report.text and '&lt;script&gt;' in report.text
    create_user(reviews[2],'review-other');other=login_user(reviews[1],'review-other')
    try:
        assert other.get(path+'/reviews').status_code==404
        assert other.post(path+'/reviews',json=body,headers={'Idempotency-Key':'review-other-001'}).status_code==404
    finally:other.__exit__(None,None,None)
    with s.read(snapshot=True) as db:migrations_v10.validate(db)


def test_v10_upgrade_requires_frozen_and_rolls_back(enabled,monkeypatch):
    s=enabled[0]
    monkeypatch.setenv('PX_ALLOW_V10_MIGRATION','1')
    with pytest.raises(ValueError,match='frozen'):
        with s.tx() as db:migrations_v10.migrate(db,fresh=False,timestamp=now())
    before=s.rows('SELECT id,username,password,role FROM users')
    with pytest.raises(RuntimeError):
        with s.tx() as db:
            migrations_v10.migrate(db,fresh=True,timestamp=now())
            raise RuntimeError('simulated interruption before commit')
    assert s.schema_version()==9 and not s.one("SELECT name FROM sqlite_master WHERE name='run_reviews'")
    with s.tx() as db:migrations_v10.migrate(db,fresh=True,timestamp=now())
    assert s.schema_version()==10 and s.rows('SELECT id,username,password,role FROM users')==before
    with s.read(snapshot=True) as db:migrations_v10.validate(db)
    with s.tx() as db:db.execute("UPDATE schema_migrations SET script_digest='wrong' WHERE migration_id=?",(migrations_v10.MIGRATION_ID,))
    with s.read(snapshot=True) as db:
        with pytest.raises(ValueError):migrations_v10.validate(db)
