"""Validate frozen synthetic evaluation observations, never call a model."""
import argparse,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
THRESHOLDS={'query_mode_accuracy':.97,'intent_accuracy':.95,'method_exact_match':.95,'agent_isolation':1,'history_zero_query':1,'clarification_zero_query':1,'plan_escape_blocking':1,'claim_source_coverage':1,'protected_fields_integrity':1,'unknown_not_zero':1,'relationship_integrity':1,'covered_conflict_detection':1}

def expected_metrics(case):
    category=case['category'];op=case.get('operation');change=case.get('change')
    if category=='routing':return {'query_mode_accuracy','intent_accuracy','method_exact_match','candidate_mode_accuracy'}
    if category=='narrative':return {'narrative_contract'}|({'covered_conflict_detection'} if case['expected_status']=='conflicted' else set())
    if category=='usage':return {'data_usage_accuracy','unknown_not_zero'}
    if category=='claim':return {'claim_source_coverage','protected_fields_integrity','relationship_integrity','result_stability'}|({'unknown_not_zero'} if change=='unknown' else {'covered_conflict_detection'} if change=='narrative' else set())
    if category=='security':return {'plan_escape_blocking'}|({'agent_isolation'} if change in ('task_agent','task_domain','profile_hash') else set())
    return {({'missing_history':'history_zero_query','history':'history_zero_query','chain':'history_zero_query','reset':'history_zero_query','disabled_capability':'unpublished_zero_query','disabled_rule':'unpublished_zero_query','cas':'context_cas','replay':'request_idempotency','other_session':'resource_isolation','other_account':'resource_isolation','profile':'historical_scope','generation':'historical_scope','client_task':'client_forgery_blocking'}).get(op,'clarification_zero_query')}

def summarize(observations,split='all'):
    manifest=json.loads((ROOT/'specs/stage2-pr9a-evaluation-set.json').read_text())
    path=ROOT/'specs/stage2-pr9a-evaluation-cases.jsonl'
    if hashlib.sha256(path.read_bytes()).hexdigest()!=manifest['sha256']:raise ValueError('evaluation_set_changed')
    cases=[json.loads(line) for line in path.read_text().splitlines()];selected={x['id']:x for x in cases if split=='all' or x['split']==split}
    got={};exit_codes=[]
    for report in observations:
        if (report.get('schema')!='peixian.evaluation-observations' or report.get('version')!='1.0'
            or type(report.get('model_requests')) is not int or report['model_requests']!=0
            or type(report.get('pytest_exit_code')) is not int):raise ValueError('invalid_observation_contract')
        exit_codes.append(report['pytest_exit_code'])
        for identity,item in report['cases'].items():
            if identity in got or identity not in selected:raise ValueError('duplicate_or_unexpected_case')
            if item['split']!=selected[identity]['split'] or item['category']!=selected[identity]['category']:raise ValueError('case_identity_mismatch')
            if not item['error'] and set(item['metrics'])!=expected_metrics(selected[identity]):raise ValueError('missing_or_unexpected_metric')
            got[identity]=item
    if set(got)!=set(selected):raise ValueError('incomplete_evaluation')
    metrics={};groups={}
    for identity,item in got.items():
        for key,value in item['metrics'].items():
            if type(value) is not bool:raise ValueError('invalid_metric')
            for target in (metrics,groups.setdefault(item['split'],{})):
                count=target.setdefault(key,{'passed':0,'total':0});count['total']+=1;count['passed']+=int(value)
    for target in [metrics,*groups.values()]:
        for key,count in target.items():
            count['rate']=count['passed']/count['total'];count['threshold']=THRESHOLDS.get(key,1);count['passed_gate']=count['rate']>=count['threshold']
    passed=all(x==0 for x in exit_codes) and not any(x['error'] for x in got.values()) and all(x['passed_gate'] for x in metrics.values()) and all(x['passed_gate'] for group in groups.values() for x in group.values())
    if split=='all':passed &= set(THRESHOLDS)<=set(metrics)
    return {'schema':'peixian.evaluation-report','version':'1.0','status':'passed' if passed else 'failed','scope':split,'cases':len(got),'dataset_sha256':manifest['sha256'],'model_requests':0,'real_data':False,'metrics':metrics,'by_split':groups,'errors':[k for k,v in got.items() if v['error']],'limits':manifest['known_limits']}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('observations',nargs='+',type=Path);parser.add_argument('--split',choices=['all','development','fixed','challenge'],default='all');parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    if args.output.exists():raise SystemExit('existing_report_preserved')
    report=summarize([json.loads(p.read_text()) for p in args.observations],args.split);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False));raise SystemExit(0 if report['status']=='passed' else 1)
if __name__=='__main__':main()
