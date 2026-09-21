"""Additive contract for backend v6. Kept separate from historical contracts."""
def extend_schemas(result):
    from .openapi import obj,ref,array,STRING,BOOL,ID,nullable
    profile={'display_name':STRING,'police_no':STRING,'position':STRING,'department_id':nullable(ID),'department':nullable(ref('Department')),'last_login_at':nullable({'type':'string','format':'date-time'}),'system_role':{'type':'string','enum':['super_admin','admin','user']}}
    result['Department']=obj({'id':ID,'name':STRING,'code':STRING,'parent_id':nullable(ID),'sort_order':{'type':'integer'},'updated_at':{'type':'string','format':'date-time'},'children':array(ref('Department'))},('id','name','code','parent_id','sort_order'))
    result['DepartmentBody']=obj({k:v for k,v in result['Department']['properties'].items() if k in ('name','code','parent_id','sort_order')})
    result['DepartmentTree']=obj({'items':array(ref('Department')),'total':{'type':'integer'},'page':{'type':'integer'},'page_size':{'type':'integer'}},('items','total','page','page_size'))
    result['UserSummary']=obj({k:{'type':'integer'} for k in ('users','enabled','disabled','departments')},('users','enabled','disabled','departments'))
    for name in ('User','UserCreateBody','UserUpdateBody'):
        if name in result:result[name]['properties'].update(profile if name=='User' else {k:v for k,v in profile.items() if k in ('display_name','police_no','position','department_id')})
    fields={'provider':STRING,'context_length':nullable({'type':'integer','minimum':256,'maximum':2000000}),'access_mode':{'type':'string','enum':['api','local']},'supports_tools':BOOL}
    for name in ('AdminModel','ModelCreateBody','ModelUpdateBody'):
        if name in result:result[name]['properties'].update(fields)
    if 'AdminModel' in result:result['AdminModel']['properties'].update({'test_status':STRING,'updated_at':nullable({'type':'string','format':'date-time'})})
    result['ModelTestResult']=obj({'ok':BOOL,'message':STRING,'elapsed_ms':{'type':'integer'}},('ok','message','elapsed_ms'))
    if 'Health' in result and 'schema_version' in result['Health'].get('properties',{}):result['Health']['properties']['schema_version']={'type':'integer','enum':[4,5,6]}
    result['Error']['properties']['field_errors']={'type':'object','additionalProperties':STRING}
    integer={'type':'integer'}
    dt={'type':'string','format':'date-time'}
    def paginated(item):return obj({'items':array(ref(item)),'total':integer,'page':integer,'page_size':integer},('items','total','page','page_size'))
    result['Run']=obj({'id':ID,'session_id':ID,'status':{'type':'string','enum':['queued','running','cancelling','reconciling','completed','failed','cancelled']},'phase':STRING,'cancel_requested':BOOL,'model_id':ID,'message_id':nullable(ID),'user_message_id':ID,'parent_run_id':nullable(ID),'created_at':dt,'started_at':nullable(dt),'completed_at':nullable(dt),'updated_at':dt,'error':nullable(obj({'code':STRING,'message':STRING}))},('id','session_id','status','phase','created_at'))
    from .task_spec import SPEC_SCHEMA,CANDIDATE_SCHEMA
    result['TaskSpec']=SPEC_SCHEMA
    result['TaskCandidate']=CANDIDATE_SCHEMA
    result['RunTask']=obj({'run_id':ID,'task_spec':nullable(ref('TaskSpec')),'response':nullable(obj({'code':STRING,'message':STRING},('code','message')))},('run_id','task_spec','response'))
    result['RunAccepted']=obj({'accepted':{'const':True},'run_id':ID,'message_id':ID},('accepted','run_id','message_id'))
    result['RunEvent']=obj({'id':ID,'sequence':integer,'step_type':STRING,'name':STRING,'status':STRING,'started_at':nullable(dt),'completed_at':nullable(dt),'elapsed_ms':nullable(integer),'capability_id':nullable(ID),'input_summary':STRING,'output_summary':STRING,'record_count':integer,'evidence_refs':array(STRING),'error_message':nullable(STRING)},('id','sequence','step_type','name','status'))
    result['RunEvidence']=obj({**result['ScenarioEvidence']['properties'],'run_id':ID,'status':{'enum':['pending','empty','partial','complete','unavailable']}},('run_id','status','cards','summary'))
    result['Identity']['properties']['capabilities']['items']['enum'].extend(['departments.manage','invocations.read'])
    result['AnalysisResult']=obj({'schema':{'const':'peixian.analysis-result'},'version':{'const':'1.0'},'run_id':ID,'generated_at':dt,'intro':STRING,'process':result['ScenarioPresentation']['properties']['process'],'subjects':array({'type':'object'}),'conclusions':array(STRING),'evidence':result['ScenarioPresentation']['properties']['evidence'],'clues':result['ScenarioPresentation']['properties']['clues'],'next_steps':STRING,'conclusion_sources':array(obj({'text':STRING,'clue_id':STRING,'source_ids':array(STRING)})),'source_metadata':{'type':'object','additionalProperties':True},'presentation_version':STRING},('schema','version','run_id','process','subjects','conclusions','evidence','clues'))
    result['AnalysisResult']['properties']['diagram']={'anyOf':[result['ScenarioDiagram'],{'type':'null'}]}
    part=result['Message']['properties']['parts']['items']['properties']
    part['type']['enum'].append('analysis_result');part['data']=ref('AnalysisResult')
    result['Capability']=obj({'id':ID,'kind':{'enum':['personal_skill','plugin','official_skill']},'name':STRING,'description':STRING,'version':nullable({}),'category':STRING,'recommended':BOOL,'enabled':BOOL,'owned':BOOL,'scope':STRING,'available':BOOL,'unavailable_reason':nullable(STRING),'dependency_ids':array(ID)},('id','kind','name','available'))
    result['OfficialMethod']=obj({'id':STRING,'version':STRING,'state':{'enum':['draft','published','disabled']},'method':STRING,'dependency_ids':array(ID),'sha256':STRING},('id','version','state','method','dependency_ids','sha256'))
    result['Capability']['properties']['official_method']=nullable(ref('OfficialMethod'))
    for name in ('ScenarioEvidence','RunEvidence'):
        result[name]['properties'].update(processing_version=STRING,execution_methods=array(STRING),plugin_versions={'type':'object','additionalProperties':STRING})
    result['Invocation']=obj({'id':ID,'run_id':ID,'session_id':ID,'username':STRING,'display_name':nullable(STRING),'department_name':nullable(STRING),'model_id':ID,'model_name':nullable(STRING),'status':STRING,'query_summary':STRING,'created_at':dt,'duration_ms':nullable(integer),'record_count':integer,'skill_ids':array(ID),'plugin_ids':array(ID),'actual_plugin_ids':array(ID),'steps':array(ref('RunEvent'))},('id','run_id','status','query_summary','created_at'))
    for name in ('Run','RunEvent','Capability','Invocation'):result[name+'Page']=paginated(name)
    result['MessageBody']['properties'].update({'client_request_id':{'type':'string','format':'uuid','description':'新客户端必须发送。旧客户端省略时服务端生成，不具备客户端重试去重保证。'},'plugin_ids':array(ID,maxItems=5),'agent_id':{'type':'string','enum':['gambling-assistant'],'description':'可选。固定使用涉赌助手；与盗窃场景选择冲突时返回422。不增加任何授权。'},'mode':{'enum':['standard']}})
    result['RerunBody']=obj(dict(result['MessageBody']['properties']),('client_request_id',))
    for name in ('Skill','SkillCreateBody','SkillUpdateBody'):result[name]['properties']['dependency_ids']=array(ID,maxItems=20)
    fields={'name':STRING,'description':STRING,'content':STRING,'dependency_ids':array(ID),'input_schema':{'type':'object','additionalProperties':True},'default_rules':array(STRING)}
    result['SkillDraftBody']=obj(fields)
    result['SkillDraft']=obj({**fields,'id':ID,'session_id':nullable(ID),'source_type':STRING,'status':{'enum':['preparing','generating','ready','needs_review','failed','saved']},'run_id':nullable(ID),'saved_skill_id':nullable(ID),'scope':{'const':'personal'},'error':nullable(obj({'code':STRING,'message':STRING})),'created_at':dt,'updated_at':dt},('id','status','source_type','scope','created_at','updated_at'))
    result['DraftGenerateBody']=obj({'requirement':STRING,'session_id':ID,'model_id':ID,'client_request_id':{'type':'string','format':'uuid'}},('client_request_id',))
    result['DraftTestBody']=obj({'mode':{'enum':['validation','model']},'text':STRING,'model_id':ID,'client_request_id':{'type':'string','format':'uuid'}})
    result['DraftTestResult']=obj({'mode':{'enum':['validation','model']},'ok':BOOL,'field_errors':{'type':'object','additionalProperties':STRING},'model_executed':nullable(BOOL),'accepted':BOOL,'session_id':ID,'run_id':ID,'message_id':ID},('mode','model_executed'))
    result['EmptyBody']=obj({})
    result['DraftSaveResult']=obj({'skill_id':ID,'scope':{'const':'personal'},'enabled':BOOL,'job':ref('Job'),'already_saved':BOOL},('skill_id','scope','already_saved'))
    return result


def contracts():
    from .openapi import ref
    result = {
      ('get','/admin/users/summary'):(None,ref('UserSummary'),'查询可管理用户汇总','管理：账号','管理员仅统计普通用户；超管统计普通用户和管理员。'),
      ('get','/admin/departments/tree'):(None,ref('DepartmentTree'),'查询部门树','管理：账号','三角色中的两个管理角色可读。'),
      ('post','/admin/departments'):('DepartmentBody',ref('Department'),'创建部门','管理：账号','仅超级管理员；幂等写入。'),
      ('patch','/admin/departments/{did}'):('DepartmentBody',ref('Department'),'修改部门','管理：账号','仅超级管理员；禁止环。'),
      ('delete','/admin/departments/{did}'):(None,ref('Ok'),'删除空部门','管理：账号','仅超级管理员；非空返回409。'),
      ('post','/admin/models/test'):('ModelCreateBody',ref('ModelTestResult'),'保存前模型连接测试','管理：模型','不落模型配置；只验证连接和模型ID，不验证推理或工具能力。'),
      ('post','/admin/models/{mid}/test'):(None,ref('ModelTestResult'),'测试已保存模型','管理：模型','只验证连接和模型ID，返回真实耗时。'),
    }

    def add(method,path,body,out,title,tag='执行记录',desc='当前账号资源；不属于本人返回404。'):
        result[(method,path)]=(body,out,title,tag,desc)
    add('post','/sessions/{sid}/messages','MessageBody',ref('RunAccepted'),'提交消息并受理持久执行',desc='HTTP 202返回持久run_id和固定message_id；plugin_ids 是偏好；同 client_request_id 同内容返回首次受理，不自动重发未知执行。')
    add('get','/sessions/{sid}/context',None,{'type':'object','properties':{'scenario_id':{'type':['string','null']},'name':{'type':['string','null']},'source':{'type':'string'},'generation':{'type':['string','null']}}},'读取本人会话场景')
    add('delete','/sessions/{sid}/context',None,{'type':'object'},'清除本人会话场景',desc='需要 Idempotency-Key；执行未结束返回409；持久清除边界不删除历史。')
    add('get','/capabilities',None,ref('CapabilityPage'),'查询当前可用能力','能力目录')
    add('get','/sessions/{sid}/runs',None,ref('RunPage'),'查询会话执行记录')
    add('get','/sessions/{sid}/runs/{rid}',None,ref('Run'),'查询执行状态')
    add('get','/sessions/{sid}/runs/{rid}/task',None,ref('RunTask'),'读取本轮冻结任务',desc='仅本人可读；TaskSpec 为服务端生成，不接受客户端写入。PR-5 历史解释未执行；旧 Run 或普通聊天返回 null。')
    add('get','/sessions/{sid}/runs/{rid}/events',None,ref('RunEventPage'),'增量查询持久步骤')
    add('get','/sessions/{sid}/runs/{rid}/evidence',None,ref('RunEvidence'),'查询固定执行证据',desc='按本人账号/会话/Run鉴权读取已保存证据；旧插件卸载不删除历史证据，读取不重新取数。')
    add('post','/sessions/{sid}/runs/{rid}/abort',None,ref('Run'),'请求停止执行')
    add('post','/sessions/{sid}/runs/{rid}/rerun','RerunBody',ref('RunAccepted'),'明确创建关联重跑')
    add('get','/sessions/{sid}/runs/{rid}/report',None,{'type':'string'},'导出 Markdown 执行报告')
    add('get','/admin/invocations',None,ref('InvocationPage'),'查询脱敏调用元数据','调用审计')
    add('get','/admin/invocations/{iid}',None,ref('Invocation'),'查询脱敏调用详情','调用审计')
    add('get','/admin/invocations/export',None,{'type':'string'},'导出 UTF-8 BOM CSV','调用审计')
    for path in ('from-requirement','from-session'):
        add('post','/skill-drafts/'+path,'DraftGenerateBody',ref('SkillDraft'),'受理模型辅助草稿','技能草稿','新客户端提供请求标识；生成不调用工具，不发布技能。')
    add('get','/skill-drafts/{did}',None,ref('SkillDraft'),'查询本人草稿','技能草稿')
    add('patch','/skill-drafts/{did}','SkillDraftBody',ref('SkillDraft'),'编辑本人草稿','技能草稿')
    add('post','/skill-drafts/{did}/test','DraftTestBody',ref('DraftTestResult'),'检查或试运行草稿','技能草稿','validation不调用模型；model需要客户端请求标识并创建独立会话。')
    add('post','/skill-drafts/{did}/save','EmptyBody',ref('DraftSaveResult'),'明确保存为个人技能','技能草稿','默认停用，等待用户启用及配置生效；保存不能获得公共发布权限。')
    return result
