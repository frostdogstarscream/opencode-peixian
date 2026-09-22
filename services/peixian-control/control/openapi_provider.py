"""Versioned provider and owner-review frontend contract."""
def extend(s):
 from .openapi import obj,ref,array,STRING,BOOL,ID,nullable
 from shared.theft_provider import CATALOG
 kinds={'enum':list(CATALOG)}
 s['ProviderQuery']=obj({'start':STRING,'end':STRING,'subject':{'enum':['DEMO-PERSON-001','DEMO-PERSON-002']},'address':STRING,'center':{'enum':['DEMO-LOCATION-A','DEMO-LOCATION-B']},'radius_m':{'type':'integer','minimum':1,'maximum':5000},'page':{'type':'integer','minimum':1,'maximum':10000},'page_size':{'type':'integer','minimum':1,'maximum':100}})
 s['ProviderPreviewBody']=obj({'kind':kinds,'query':ref('ProviderQuery')},('kind','query'))
 s['ProviderPlan']=obj({'version':{'const':'theft-provider-contract-v1'},'kind':kinds,'query':ref('ProviderQuery'),'revision':{'type':'integer'},'generation':{},'expires':{'type':'integer'}},('version','kind','query','revision','generation','expires'))
 from shared.theft_provider_v2 import CATALOG as V2_CATALOG,VERSION as V2
 v2_query=obj({'lon':STRING,'lat':STRING,'radius_m':{'type':['number','string']},'start':STRING,'end':STRING,'start_date':STRING,'end_date':STRING,'track_types':array({'enum':[0,1,2]},minItems=1,maxItems=3,uniqueItems=True),'page':{'type':'integer','minimum':1},'page_size':{'type':'integer','minimum':1,'maximum':100}})
 s['ProviderPreviewBody']={'oneOf':[s['ProviderPreviewBody'],obj({'contract_version':{'const':V2},'kind':{'enum':list(V2_CATALOG)},'query':v2_query,'person_identity':{'type':'string','pattern':'^[0-9]{17}[0-9X]$'}},('contract_version','kind','query'))]}
 s['ProviderPreviewBody'].update(type='object',properties={'kind':{'enum':list(V2_CATALOG)},'query':{'type':'object'},'contract_version':{'const':V2},'person_identity':{'type':'string','writeOnly':True}})
 s['ProviderPlan']={'oneOf':[s['ProviderPlan'],obj({'version':{'const':V2},'token':STRING},('version','token'))]}
 s['ProviderConfirmation']=obj({'plan':ref('ProviderPlan'),'confirmation':STRING},('plan','confirmation'))
 s['ProviderPreview']=obj({**s['ProviderConfirmation']['properties'],'summary':STRING},('plan','confirmation','summary'))
 s['ProviderPreview']['properties'].update(data_environment={'enum':['synthetic','acceptance_real']},contract_version=STRING)
 s['ProviderCapabilities']=obj({'items':array(obj({'kind':kinds,'name':STRING,'plugin_id':ID,'available':BOOL},('kind','name','plugin_id','available'))),'data_environment':{'const':'synthetic'},'contract_version':STRING},('items','data_environment','contract_version'))
 s['ProviderCapabilities']['properties']['contract_versions']=array(STRING)
 s['ProviderCapabilities']['properties']['items']['items']['properties'].update(kind={'enum':list(V2_CATALOG)},reason=nullable(STRING),data_environment={'enum':['synthetic','acceptance_real']},contract_version=STRING)
 s['MessageBody']['properties']['provider_query']=ref('ProviderConfirmation')
 s['Health']['properties']['schema_version']['enum'].append(10)
 s['TaskSpec']['oneOf'].append(obj({'schema_version':{'const':'task-spec-v4'},'domain':{'const':'theft'},'agent_id':{'const':'theft-assistant'},'query_mode':{'enum':['new_query','explain_existing','clarify']},'methods':array(kinds,minItems=1,maxItems=1)},('schema_version','domain','agent_id','query_mode','methods'),extra=True))
 s['TaskSpec']['oneOf'][-1]['properties']['methods']['items']={'enum':list(V2_CATALOG)}
 status={'enum':['consistent','needs_information','inconsistent']}
 s['ReviewBody']=obj({'result_digest':STRING,'status':status,'note':{'type':'string','minLength':1,'maxLength':2000},'claim_ids':array(STRING,maxItems=100,uniqueItems=True),'supersedes':nullable(ID)},('result_digest','status','note'))
 s['Review']=obj({**s['ReviewBody']['properties'],'id':ID,'run_id':ID,'status_label':STRING,'reviewer':STRING,'created_at':STRING},('id','run_id','result_digest','status','note','claim_ids','reviewer','created_at','supersedes','status_label'))
 s['ReviewList']=obj({'items':array(ref('Review')),'result_digest':STRING,'unreviewed':BOOL,'total':{'type':'integer'},'page':{'type':'integer'},'page_size':{'type':'integer'}},('items','result_digest','unreviewed','total','page','page_size'))

def contracts():
 from .openapi import ref
 return {
 ('get','/theft-provider/capabilities'):(None,ref('ProviderCapabilities'),'可用资料查询','会话','只列当前账号授权且已生效能力；合成接口，不访问供应方。'),
 ('post','/sessions/{sid}/provider-query/preview'):('ProviderPreviewBody',ref('ProviderPreview'),'确认资料范围','会话','只检查范围，签名有效期600秒，绑定账号、会话、配置、清除边界；不调用模型和资料服务。'),
 ('get','/sessions/{sid}/runs/{rid}/reviews'):(None,ref('ReviewList'),'本人来源复核','会话','分页读取；跨账号404，不授予管理员读取正文权限。'),
 ('post','/sessions/{sid}/runs/{rid}/reviews'):('ReviewBody',ref('Review'),'追加来源复核','会话','Idempotency-Key必填。终态且结果摘要匹配；追加更正保留原记录，不修改可信事实。')}
