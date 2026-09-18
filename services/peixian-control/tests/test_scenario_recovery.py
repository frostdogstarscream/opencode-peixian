import pytest
from fastapi import HTTPException
from test_runtime_pool import pool, account, begin
from control.store import now


@pytest.mark.parametrize("proof,newer,passes", [("stopped",False,True),("unknown",False,False),("stopped",True,False)])
def test_resume_closes_only_older_recovery_after_verified_pause(pool, proof, newer, passes):
    s, _ = pool
    uid = account(s)
    old = begin(s, uid)["job"]["id"]
    with s.tx() as db:
        db.execute("UPDATE jobs SET status='failed',phase='finished',recovery_required=1,attempts=1 WHERE id=?", (old,))
        db.execute("INSERT INTO jobs(id,uid,action,status,phase,revision,created,updated) VALUES('verified-pause',?,'pause','succeeded','finished',1,?,?)", (uid,now(),now()))
        if newer:
            db.execute("INSERT INTO jobs(id,uid,action,status,phase,revision,recovery_required,created,updated) VALUES('new-failure',?,'apply','failed','finished',1,1,?,?)", (uid,now(),now()))
        db.execute("UPDATE runtimes SET status='paused',revision=1,reserved=0,recovery_required=0,gate_policy='closed' WHERE uid=?", (uid,))
        runtime = db.execute("SELECT id,state_version,gate_epoch FROM runtimes WHERE uid=?", (uid,)).fetchone()
        db.execute("INSERT INTO runtime_observations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", ('observation',runtime['id'],None,None,runtime['state_version'],'host','absent',runtime['gate_epoch'],now(),now()+60,1,'{}','idle',0,0,None,1,None,'evidence',proof,'hash',now()))
    if passes:
        assert begin(s, uid, admin=True)["accepted"]
        row=s.one("SELECT status,recovery_required FROM jobs WHERE id=?", (old,))
        assert row["status"] == "failed" and row["recovery_required"] == 0
    else:
        with pytest.raises(HTTPException): begin(s, uid, admin=True)
        assert s.one("SELECT recovery_required FROM jobs WHERE id=?", (old,))["recovery_required"] == 1
