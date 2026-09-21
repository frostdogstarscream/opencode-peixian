"""Bounded entities from this generation's trusted data, never assistant prose."""
import re
from . import task_context
from .scenario_versions import DATA151
VERSION='entity-projection-v1'
TARGET_VERSION='method-target-v2'
TYPES={'gambling-assistant':{'person','account'},'theft-assistant':{'person','vehicle'}}

def entities(store,uid,sid,profile):
    context=task_context.ensure(store,uid,sid,profile)
    projection=task_context.source(store,uid,sid,profile,context)
    scene=DATA151['scenarios'][profile.data['default_scenario_id']]
    output={('person',scene['subject_ref']):{'type':'person','ref':scene['subject_ref'],'display':scene['subject_ref'],'source_data_run_id':None,'source_ids':[]}}
    if projection:
        row=store.one('SELECT request_ciphertext FROM business_runs WHERE id=? AND uid=? AND session_id=?',(projection['source_data_run_id'],uid,sid))
        snap=store.decrypt(row['request_ciphertext']);sources={x for f in projection['claims'] for x in f['source_ids']}
        for module,part in snap['facts_state']['modules'].items():
            if part['status']!='completed':continue
            fields={'funds':{'member_ref':'person','group_ref':'account','counterparty_ref':'account'},'vehicle':{'member_ref':'person','group_ref':'vehicle'},'portrait':{'member_ref':'person','co_member_ref':'person'},'night':{'group_ref':'person'}}.get(module,{})
            for record in part['response'].get('items',[]):
                if record['record_id'] not in sources:continue
                for field,kind in fields.items():
                    value=record.get(field)
                    if kind not in TYPES[profile.id] or not isinstance(value,str) or not value or len(value)>120:continue
                    entity=output.setdefault((kind,value),{'type':kind,'ref':value,'display':value,'source_data_run_id':projection['source_data_run_id'],'source_ids':[]})
                    entity['source_data_run_id']=projection['source_data_run_id'];entity['source_ids'].append(record['record_id'])
    values=sorted(output.values(),key=lambda x:(x['type'],x['ref']))
    for entity in values:entity['source_ids']=sorted(set(entity['source_ids']))
    return {'schema':VERSION,'agent_id':profile.id,'agent_profile_sha256':profile.profile_sha256,'generation':context['generation'],'source_data_run_id':projection['source_data_run_id'] if projection else None,'entities':values}

def supported(entity,methods,profile):
    from .task_targets import CONTRACTS
    subject=DATA151['scenarios'][profile.data['default_scenario_id']]['subject_ref']
    if entity['type']=='vehicle':return profile.id=='theft-assistant' and methods==['vehicles']
    if entity['type']!='person':return False
    mode='scenario_subject' if entity['ref']==subject else 'record_filter'
    return all(mode in CONTRACTS[m]['supported_target_modes'] for m in methods)

def target(entity,methods,profile):
    if not supported(entity,methods,profile):return {'status':'unsupported','target_refs':[],'reason':'unsupported_target_scope'}
    subject=DATA151['scenarios'][profile.data['default_scenario_id']]['subject_ref']
    mode='scenario_subject' if entity['type']=='person' and entity['ref']==subject else 'record_filter'
    return {'status':'resolved','target_refs':[entity['ref']],'entity_type':entity['type'],'target_mode':mode,'contract_version':TARGET_VERSION,'agent_target_profile':profile.data['target_contract_profile'],'filter_fields':(['group_ref'] if entity['type']=='vehicle' else ['member_ref']) if mode=='record_filter' else [],'entity_projection':VERSION,'source_data_run_id':entity['source_data_run_id'],'source_ids':entity['source_ids']}

def resolve(store,uid,sid,text,methods,profile,confirmed=None):
    projection=entities(store,uid,sid,profile);values=projection['entities']
    if confirmed:
        match=next((e for e in values if e['type']==confirmed['type'] and e['ref']==confirmed['ref']),None)
        return target(match,methods,profile) if match else {'status':'missing','target_refs':[],'reason':'target_missing'}
    kind='vehicle' if re.search('那辆车|这辆车|该车|哪辆车',text) else 'account' if re.search('这个账户|该账户|那个账户',text) else 'person' if re.search('这个人|那个人|他|她|这两个人|两人',text) else None
    matches=[e for e in values if e['ref'] in text]
    # Long account/vehicle labels can contain a person's name; keep the longest explicit match.
    matches=[e for e in matches if not any(e['ref']!=x['ref'] and e['ref'] in x['ref'] for x in matches)]
    if not kind and not matches:return None
    residual=text
    for label in sorted([e['ref'] for e in matches],key=len,reverse=True):residual=residual.replace(label,'')
    words=('查看','看看','核对','查询','查一下','整理','分析','请','帮我','那辆车','这辆车','该车','哪辆车','这个账户','那个账户','该账户','这个人','那个人','这两个人','他们','她们','他','她','两人','资金往来','资金','流水','收支','转账','同行','同框','共现','夜间活动','夜间','活动','车辆','车牌','卡口','过车','驾乘','记录','资料','情况','明细','的','与','和')
    for word in sorted(words,key=len,reverse=True):residual=residual.replace(word,'')
    if re.search(r'[\w\u4e00-\u9fff]',residual):return {'status':'unsupported','target_refs':[],'reason':'unsupported_target_scope'}

    if kind and kind not in TYPES[profile.id]:return {'status':'unsupported','target_refs':[],'reason':'unsupported_target_scope'}
    choices=matches or [e for e in values if e['type']==kind]
    if not choices:return {'status':'missing','target_refs':[],'reason':'target_missing'}
    if re.search('这两个人|他们|她们|两人',text) or (matches and len(matches)>1):return {'status':'unsupported','target_refs':[],'reason':'unsupported_target_scope'}
    if any(not supported(e,methods,profile) for e in choices):return {'status':'unsupported','target_refs':[],'reason':'unsupported_target_scope'}
    if len(choices)==1:return target(choices[0],methods,profile)
    if len(choices)>20:return {'status':'missing','target_refs':[],'reason':'target_candidates_exceed_limit'}
    return {'status':'ambiguous','target_refs':[],'reason':'target_confirmation_required','options':choices,'requested_methods':methods,'projection':{k:v for k,v in projection.items() if k!='entities'}}
