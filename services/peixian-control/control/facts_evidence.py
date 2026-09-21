"""Project only durable platform facts. Never accept similarly named model parts."""
import copy
from .scenario_evidence import project
from .scenario_facts import render_table
from .scenario_presentation import presentation
from .facts_runtime import LABELS

def evidence(snapshot, row):
    plan=snapshot.get('facts_plan');state=snapshot.get('facts_state',{})
    result=project([],False)
    result['turn_id']=row['message_id'];result['run_id']=row['id']
    if not plan:return result
    result['processing_version']=plan['coordinator_version']
    result['execution_methods']=plan['methods']
    if plan.get('registry'):result['registry_provenance']=copy.deepcopy(plan['registry'])
    result['plugin_versions']={p['id']:p['version'] for p in snapshot['plugins'] if p['id'] in plan['allowed_capabilities']}
    result['steps']=[{'label':'查询'+LABELS.get(module,'所选')+'资料','status':value['status']} for module,value in state.get('modules',{}).items()]
    table=state.get('table')
    if not table:
        result['status']='partial' if state.get('modules') else 'empty'
        result['missing']=['本轮尚未形成有效事实表；未取得资料不表示没有记录。']
        return result
    completed={m:v for m,v in state['modules'].items() if v['status']=='completed'}
    from shared.task_scope import scoped
    data={'scenarios':{table['scenario_id']:copy.deepcopy(plan['scenario'])},'records':{m:scoped(plan,m,plan['records'][m],'records') for m in completed}}
    data['scenarios'][table['scenario_id']]['required_modules']=[s['module'] for s in table['summary']]
    result=render_table(result,table,row.get('assistant_id') or '',state.get('checked'),data)
    provenance={p['record_id']:p for item in completed.values() for p in item['response'].get('provenance',[])}
    for card in result['cards']:
        if card['id'] in provenance:card['provenance']=provenance[card['id']]
    for module,value in state['modules'].items():
        if value['status']!='completed':result['missing'].append(LABELS.get(module,'所选')+'资料'+{'unknown':'结果尚未确认','rejected':'暂不可采用','cancelled':'已取消','pending':'正在获取'}.get(value['status'],'尚未取得')+'，不会自动重新查询。')
    # Renderer receives server events, not model-authored metadata or free text.
    import json
    trace=[{'code':m,'status':'completed' if v['status']=='completed' else 'failed','at':v.get('completed',v.get('started',state['compiled_at']))*1000} for m,v in state['modules'].items()]
    trace.sort(key=lambda v:v['at'])
    start=min([v['started'] for v in state['modules'].values() if 'started' in v] or [state['compiled_at']])*1000
    parts=[{'type':'tool','tool':'peixian_prepare_scenario_facts','state':{'input':{'scenario_id':table['scenario_id']},'status':'completed','time':{'start':start,'end':state['compiled_at']*1000},'output':json.dumps({'execution_trace':trace})}}]
    if state.get('checked'):
        at=state['checked_at']*1000
        parts.append({'type':'tool','tool':'peixian_check_scenario_summary','state':{'input':{'scenario_id':table['scenario_id']},'status':'completed','time':{'start':at,'end':at},'output':json.dumps({'execution_trace':[{'code':'check','status':'failed' if state['checked']['rejected'] else 'completed','at':at}]})}})
    messages=[{'info':{'role':'user','id':row['message_id']}},{'info':{'role':'assistant'},'parts':parts}]
    view=presentation(result,messages,frozen_data=data)
    if view:
        if view.get('diagram'):view['diagram']['run_id']=row['id']
        result['presentation']=view
    return result
