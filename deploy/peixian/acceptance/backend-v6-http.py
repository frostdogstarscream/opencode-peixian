import json,time,uuid,httpx,os
from pathlib import Path
root=Path(os.environ['BACKEND_V6_FIXTURE_ROOT']);base=os.environ['BACKEND_V6_BASE_URL'].rstrip('/')+'/api/console/v1'
accounts=json.loads((root/'test-accounts.json').read_text());ids=json.loads((root/'test-ids.json').read_text());evidence={}
from contextlib import contextmanager
@contextmanager
def client(name):
 c=httpx.Client(verify=str(root/'tls/certificate.pem'),timeout=30,headers={'Origin':os.environ['BACKEND_V6_BASE_URL'].rstrip('/')})
 response=c.post(base+'/auth/login',json={'username':name,'password':accounts[name]});assert response.status_code==200,response.text
 value=response.json();c.headers['X-CSRF-Token']=value['csrf_token']
 if value['user']['must_change_password']:
  new=accounts[name]+'-changed';result=c.post(base+'/me/password',json={'current_password':accounts[name],'password':new});assert result.status_code==200
  accounts[name]=new;(root/'test-accounts.json').write_text(json.dumps(accounts))
 try:yield c
 finally:c.close()
def call(c,method,path,body=None):
 response=c.request(method,base+path,json=body,headers={'Idempotency-Key':uuid.uuid4().hex})
 assert response.status_code<400,(path,response.status_code,response.text[:160]);return response

def wait(c,sid,rid):
 for _ in range(80):
  value=call(c,'GET','/sessions/'+sid+'/runs/'+rid).json()
  if value['status'] in ('completed','failed','cancelled'):return value
  time.sleep(.5)
 return value
with client('test-a') as a:
 sid=call(a,'POST','/sessions',{'title':'接口确定性验收'}).json()['id']
 body={'text':'请返回简短的接口验证结果。','model_id':ids['model'],'client_request_id':str(uuid.uuid4()),'plugin_ids':[],'skill_ids':[],'file_ids':[],'mode':'standard'}
 accepted=call(a,'POST','/sessions/'+sid+'/messages',body);assert accepted.status_code==202
 rid=accepted.json()['run_id'];result=wait(a,sid,rid);evidence['run']=result['status'];print('run',result['status'],result.get('error'),flush=True)
 assert result['status']=='completed'
 repeated=call(a,'POST','/sessions/'+sid+'/messages',body).json();assert repeated==accepted.json()
 assert a.post(base+'/sessions/'+sid+'/messages',json={**body,'text':'different'}).status_code==409
 evidence['idempotency']='passed'
 steps=call(a,'GET','/sessions/'+sid+'/runs/'+rid+'/events').json();assert len(steps['items'])>=2;evidence['steps']=steps['total']
 report=call(a,'GET','/sessions/'+sid+'/runs/'+rid+'/report');assert 'text/markdown' in report.headers['Content-Type'];assert '.md' in report.headers['Content-Disposition'];evidence['report']='passed'
 with client('test-b') as b:
  for suffix in ('','/events','/evidence','/report'):assert b.get(base+'/sessions/'+sid+'/runs/'+rid+suffix).status_code==404
 evidence['cross_account']='passed'
 again=call(a,'POST','/sessions/'+sid+'/runs/'+rid+'/rerun',{'client_request_id':str(uuid.uuid4())}).json();assert again['run_id']!=rid
 result=wait(a,sid,again['run_id']);assert result['status']=='completed' and result['parent_run_id']==rid;evidence['rerun']='passed'
 draft=call(a,'POST','/skill-drafts/from-requirement',{'requirement':'形成资料核对方法，只处理输入参数与来源引用。','model_id':ids['model'],'client_request_id':str(uuid.uuid4())}).json()
 for _ in range(80):
  draft=call(a,'GET','/skill-drafts/'+draft['id']).json()
  if draft['status'] not in ('generating','preparing'):break
  time.sleep(.5)
 print('draft',draft['status'],flush=True);assert draft['status']=='ready'
 checked=call(a,'POST','/skill-drafts/'+draft['id']+'/test',{}).json();assert checked['ok'] and not checked['model_executed']
 call(a,'PATCH','/skill-drafts/'+draft['id'],{'name':'接口技能-'+uuid.uuid4().hex[:8]})
 saved=call(a,'POST','/skill-drafts/'+draft['id']+'/save',{}).json();assert saved['scope']=='personal' and saved['enabled'] is False;evidence['draft']='passed'
with client('test-manager') as manager:
 rows=call(manager,'GET','/admin/invocations').json();assert rows['total']>=3
 assert '请返回简短' not in json.dumps(rows,ensure_ascii=False)
 detail=call(manager,'GET','/admin/invocations/'+rows['items'][0]['id']).json();assert isinstance(detail['steps'],list)
 exported=call(manager,'GET','/admin/invocations/export');assert exported.content.startswith(b'\xef\xbb\xbf')
 assert manager.post(base+'/admin/departments',json={'name':'Forbidden','code':'forbidden'},headers={'Idempotency-Key':uuid.uuid4().hex}).status_code==403
 evidence['admin_metadata']='passed'
evidence.update(paid_model_requests=0,model_type='controlled-http-service',run_id=rid,session_id=sid)
(root/'http-evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2));print(json.dumps(evidence,ensure_ascii=False))
