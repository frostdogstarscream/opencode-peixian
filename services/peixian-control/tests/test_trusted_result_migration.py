import json,sqlite3
from pathlib import Path
import pytest
from cryptography.fernet import Fernet
from control.store import Store
from control.schema import validate
from control import migrations_v9
from test_control import PASSWORD

@pytest.fixture
def original(tmp_path,monkeypatch):
 monkeypatch.setenv('PX_BACKEND_V6','1');monkeypatch.setenv('PX_TASK_CONTEXT_V1','1');monkeypatch.setenv('PX_TASK_CLARIFICATION_V1','1');monkeypatch.delenv('PX_TRUSTED_RESULT_V2',raising=False)
 for name,value in [('key',Fernet.generate_key()),('worker',b'x'*40),('admin',PASSWORD.encode())]:(tmp_path/name).write_bytes(value)
 args=(tmp_path/'db',tmp_path/'key',tmp_path/'worker',tmp_path/'admin');s=Store(*args)
 backup=tmp_path/'before.sqlite3'
 with sqlite3.connect(s.path) as source,sqlite3.connect(backup) as target:source.backup(target)
 return s,args,backup

def migrate(original,monkeypatch):
 s,args,_=original
 with s.tx() as db:db.execute("UPDATE platform_state SET maintenance_mode='frozen' WHERE id=1")
 monkeypatch.setenv('PX_TRUSTED_RESULT_V2','1');monkeypatch.setenv('PX_ALLOW_V9_MIGRATION','1')
 return Store(*args)

def test_upgrade_repeat_and_empty_target_restore(original,monkeypatch,tmp_path):
 s,args,backup=original;identity=s.one('SELECT id,password,role,auth_version FROM users')
 new=migrate(original,monkeypatch);assert new.schema_version()==9
 assert new.one('SELECT id,password,role,auth_version FROM users')==identity
 assert Store(*args).schema_version()==9
 with new.read() as db:validate(db)
 target=tmp_path/'restored';target.mkdir()
 with sqlite3.connect(backup) as old,sqlite3.connect(target/'control.sqlite3') as recovered:old.backup(recovered)
 monkeypatch.delenv('PX_TRUSTED_RESULT_V2')
 restored=Store(target,*args[1:]);assert restored.schema_version()==8
 assert restored.one('SELECT id,password,role,auth_version FROM users')==identity
 assert new.schema_version()==9

def test_unapproved_or_busy_upgrade_refused(original,monkeypatch):
 s,args,_=original;monkeypatch.setenv('PX_TRUSTED_RESULT_V2','1')
 with pytest.raises(ValueError,match='offline approval'):Store(*args)
 assert s.schema_version()==8
 with s.tx() as db:db.execute("UPDATE platform_state SET maintenance_mode='frozen' WHERE id=1")
 monkeypatch.setenv('PX_ALLOW_V9_MIGRATION','1')
 with s.tx() as db:
  db.execute("INSERT INTO jobs(id,uid,action,status,revision,created,updated) VALUES('pending','demo','provision','queued',1,0,0)")
 with pytest.raises(ValueError,match='responsibilities'):Store(*args)
 assert s.schema_version()==8


def test_injected_failure_rolls_back_ddl(original,monkeypatch):
 s,args,_=original
 monkeypatch.setattr(migrations_v9,'DDL',migrations_v9.DDL+['INVALID SQL'])
 with pytest.raises(sqlite3.OperationalError):migrate(original,monkeypatch)
 assert s.schema_version()==8 and not s.one("SELECT 1 FROM sqlite_master WHERE name='run_results'")

@pytest.mark.parametrize('change',['table','fingerprint','script'])
def test_v9_corruption_fails_closed(original,monkeypatch,change):
 s=migrate(original,monkeypatch)
 with s.tx() as db:
  if change=='table':db.execute('DROP TABLE run_results')
  else:db.execute('UPDATE schema_migrations SET '+('structure_digest' if change=='fingerprint' else 'script_digest')+"='bad' WHERE to_version=9")
 with pytest.raises(ValueError):Store(*original[1])
