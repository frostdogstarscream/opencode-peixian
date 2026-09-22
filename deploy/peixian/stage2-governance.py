"""Render and verify Stage2 release rules; this tool never contacts GitHub."""
import argparse,json,re,hashlib,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]

def require(ok,code):
    if not ok:raise ValueError(code)

def contract(root=ROOT):return json.loads((Path(root)/'specs/stage2-pr9b-governance.json').read_text())

def ruleset(root=ROOT):
    c=contract(root)
    return {'name':'Peixian Stage2 protected release','target':'branch','enforcement':'active','bypass_actors':[],
        'conditions':{'ref_name':{'include':['refs/heads/'+c['release_branch']],'exclude':[]}},
        'rules':[{'type':'deletion'},{'type':'non_fast_forward'},
            {'type':'pull_request','parameters':{'dismiss_stale_reviews_on_push':True,'require_code_owner_review':True,'require_last_push_approval':True,'required_approving_review_count':c['review_required'],'required_review_thread_resolution':True}},
            {'type':'required_status_checks','parameters':{'strict_required_status_checks_policy':True,'required_status_checks':[{'context':name,'integration_id':c['github_actions_app_id']} for name in c['required_checks']]}}]}

def verify_rules(value,root=ROOT):
    expected=ruleset(root)
    for key in ('target','enforcement','bypass_actors','conditions'):require(value.get(key)==expected[key],'ruleset_'+key)
    actual={r['type']:r for r in value.get('rules',[])}
    require(set(actual)=={r['type'] for r in expected['rules']},'ruleset_rules')
    for rule in expected['rules']:
        params=actual[rule['type']].get('parameters',{})
        for key,setting in rule.get('parameters',{}).items():
            if key=='required_status_checks':require(sorted(params.get(key,[]),key=lambda x:x['context'])==sorted(setting,key=lambda x:x['context']),'required_checks')
            else:require(params.get(key)==setting,'ruleset_'+key)
    return True

def check_source(root=ROOT):
    root=Path(root);c=contract(root);text=(root/'.github/workflows/peixian-stage2-release-governance.yml').read_text()
    require(set(re.findall(r"github.head_ref == '([^']+)'",text))=={'codex/stage2-release-governance-v1','codex/stage2-ab-closeout-v1','codex/stage2-release'} and 'startsWith(github.head_ref' not in text,'workflow_branch_scope')
    actual=dict(re.findall(r'- \{name: ([^,]+), job: ([^}]+)\}',text))
    require(set(actual)==set(c['required_checks']),'workflow_check_set')
    require(all(v==('frontend' if k=='Frontend Build' else 'evaluation' if k=='Evaluation' else 'core') for k,v in actual.items()),'workflow_coverage')
    require("if: always()" in text and "if result!='success':raise SystemExit" in text,'failed_suite_gate')
    owners=(root/'.github/CODEOWNERS').read_text()
    for pattern in ('/services/peixian-control/control/agents/','/services/peixian-control/control/developer_registry/','/services/peixian-control/control/task_*','/services/peixian-control/control/clarifications.py','/services/peixian-control/control/entity_projection.py','/services/peixian-control/control/facts_*','/services/peixian-control/control/migrations_*','/services/peixian-control/gateway/','/specs/stage2-*','/deploy/peixian/'):
        require(pattern+' @'+c['code_owner'] in owners,'code_owner_missing')
    for role in ('Control','Gateway','Agent'):
        docker=(root/'deploy/peixian'/('Stage2.'+role+'.Dockerfile')).read_text()
        require('ARG BASE_IMAGE' in docker and '${SOURCE_REVISION}' in docker,'image_identity')
    verify_rules(ruleset(root),root)
    historical=['services/peixian-control/control/migrations_v'+str(v)+'.py' for v in range(4,10)]+['specs/stage2-pr5*','specs/stage2-pr6*','specs/stage2-pr7*','specs/stage2-pr8*','specs/stage2-pr9a*']
    require(not subprocess.check_output(['git','diff','--name-only',c['baseline'],'--',*historical],cwd=root,text=True).strip(),'historical_drift')
    release=json.loads((root/'specs/stage2-pr9b-release.json').read_text())
    require(release.get('baseline')==c['baseline'] and release.get('stage')=='pr9b','release_baseline')
    require(release.get('deployment_performed') is False and release.get('real_data_accessed') is False and type(release.get('model_requests')) is int and release['model_requests']==0,'release_scope')
    require(release.get('status') in ('pending','completed'),'release_status')
    if release['status']=='completed':
        revision=release['implementation_revision'];ci=release['github_ci'];require(re.fullmatch('[0-9a-f]{40}',revision) is not None,'release_revision')
        require(ci.get('executed') is True and ci.get('head_sha')==revision and ci.get('conclusion')=='success' and set(ci.get('required_checks',[]))==set(c['required_checks']),'ci_receipt')
        verify_rules(release['ruleset'],root)
        mpath=root/'specs/stage2-pr9b-artifact-manifest.json';require(hashlib.sha256(mpath.read_bytes()).hexdigest()==release['artifact_manifest_sha256'],'artifact_manifest_digest')
        m=json.loads(mpath.read_text());require(m.get('source_revision')==revision and m.get('tag')==c['candidate_tag'] and m.get('source_matches_commit') is True,'artifact_identity')
        require(set(m.get('images',{}))=={'control','gateway','agent'} and all(x['source_revision']==revision for x in m['images'].values()),'matched_images')
        paths=['specs/stage2-pr9b-governance.json','packages','services','deploy/peixian','.github/CODEOWNERS','.github/workflows/peixian-stage2-release-governance.yml']
        require(subprocess.run(['git','merge-base','--is-ancestor',revision,'HEAD'],cwd=root,capture_output=True).returncode==0,'revision_ancestry')
        require(not subprocess.check_output(['git','diff','--name-only',revision,'--',*paths],cwd=root,text=True).strip(),'closed_source_drift')
        require(not subprocess.check_output(['git','ls-files','--others','--exclude-standard','--',*paths],cwd=root,text=True).strip(),'untracked_release_source')
    return True

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--check-source',action='store_true');p.add_argument('--render-rules',type=Path);p.add_argument('--verify-rules',type=Path);a=p.parse_args()
    if a.check_source:check_source();print('Stage2 governance source verified')
    if a.render_rules:
        if a.render_rules.exists():p.error('existing rules file preserved')
        a.render_rules.write_text(json.dumps(ruleset(),indent=2)+'\n')
    if a.verify_rules:verify_rules(json.loads(a.verify_rules.read_text()));print('Stage2 GitHub rules readback verified')
