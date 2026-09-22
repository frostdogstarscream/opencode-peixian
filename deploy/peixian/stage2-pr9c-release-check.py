"""PR-9C closeout consistency; pending never means live acceptance."""
import json,subprocess,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
REQUIRED={'first_stage_online','backup','restore','migration','old_image_rejection','a_gambling','a_theft','b_gambling','b_theft','historical_zero_query','clarification_zero_query','disabled_capability','unknown','gateway_restart','report','narrative_conflict','legacy','account_isolation','frontend'}

def check(root=ROOT):
 r=Path(root);v=json.loads((r/'specs/stage2-pr9c-release.json').read_text())
 assert v['stage']=='pr9c' and v['baseline']=='71e7c7a15d1215e017a6b5b451d3aa3e6d9ad1a6'
 assert v['status'] in ('pending','completed') and v['real_data_accessed'] is False and v['load_test_performed'] is False
 assert type(v['model_requests']) is int and 0<=v['model_requests']<=40
 assert v['candidate_tag']=='stage2-dual-agent-v1.0.0-rc2'
 assert subprocess.run(['git','merge-base','--is-ancestor',v['baseline'],'HEAD'],cwd=r,capture_output=True).returncode==0
 if v['status']=='completed':
  assert v['deployment_performed'] is True and set(v['gates'])==REQUIRED
  assert all(x.get('status')=='passed' and x.get('evidence') for x in v['gates'].values())
  assert v['schema_version']==9 and v['github_ci']['conclusion']=='success'
  assert re.fullmatch('[0-9a-f]{40}',v['implementation_revision'])
  assert v['github_ci']['head_sha']==v['implementation_revision']
  assert not subprocess.check_output(['git','diff','--name-only',v['implementation_revision'],'--','packages','services','deploy/peixian','.github/workflows/peixian-stage2-release-governance.yml'],cwd=r,text=True).strip()
 return v['status']
if __name__=='__main__':print('PR-9C source contract: '+check())
