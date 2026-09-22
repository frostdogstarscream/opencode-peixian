import importlib.util,json,sqlite3
from pathlib import Path
import pytest
from test_context_migration import original
ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('migration_drill',ROOT/'deploy/peixian/stage2-migration-drill.py');tool=importlib.util.module_from_spec(spec);spec.loader.exec_module(tool)

def test_v6_full_chain_preserves_original_and_restores(original,tmp_path):
 s,args,_=original;before=tool.inventory(s.path)
 receipt=tool.drill(s.path,tmp_path/'rehearsal',*args[1:])
 assert receipt['target_schema']==9 and receipt['protected_content_unchanged']
 assert receipt['runtime_restore_executed'] is False and tool.inventory(s.path)==before
 assert tool.inventory(tmp_path/'rehearsal/restored-before/control.sqlite3')==before
 assert tool.inventory(tmp_path/'rehearsal/restored-after/control.sqlite3')['schema']==9

@pytest.mark.parametrize('kind',['existing','inside','symlink'])
def test_rehearsal_rejects_unsafe_destination(original,tmp_path,kind):
 s,args,_=original;target=tmp_path/'target'
 if kind=='existing':target.mkdir();(target/'marker').write_text('keep')
 elif kind=='inside':target=s.root/'nested'
 else:target.symlink_to(s.root,target_is_directory=True)
 before=tool.inventory(s.path)
 with pytest.raises(ValueError):tool.drill(s.path,target,*args[1:])
 assert tool.inventory(s.path)==before
 if kind=='existing':assert (target/'marker').read_text()=='keep'

def test_busy_copy_is_not_silently_resolved(original,tmp_path):
 s,args,_=original
 with s.tx() as db:db.execute("INSERT INTO jobs(id,uid,action,status,revision,created,updated) VALUES('pending','demo','provision','queued',1,0,0)")
 with pytest.raises(ValueError,match='unresolved_jobs'):tool.drill(s.path,tmp_path/'busy',*args[1:])
 assert s.one("SELECT status FROM jobs WHERE id='pending'")['status']=='queued'

def test_copy_never_overwrites(original,tmp_path):
 target=tmp_path/'keep.sqlite3';target.write_bytes(b'keep')
 with pytest.raises(ValueError,match='restore_target_exists'):tool.copy_database(original[0].path,target)
 assert target.read_bytes()==b'keep'
