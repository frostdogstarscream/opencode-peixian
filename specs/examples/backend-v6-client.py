"""No automatic write retries. Supply API URL, token and model through environment."""
import json, os, time, uuid
import httpx

base=os.environ['AGENT_BASE_URL'].rstrip('/')+'/api/console/v1'
with httpx.Client(base_url=base,headers={'Authorization':'Bearer '+os.environ['AGENT_TOKEN']},timeout=30) as client:
    def request(method,path,**kwargs):
        result=client.request(method,path,**kwargs)
        result.raise_for_status()
        return result
    session=request('POST','/sessions',json={'title':'DEMO backend contract'}).json()['id']
    body={'text':'Return a brief synthetic test response.','model_id':os.environ['AGENT_MODEL_ID'],'client_request_id':str(uuid.uuid4()),'mode':'standard','skill_ids':[],'plugin_ids':[],'file_ids':[]}
    # On timeout, keep body/client_request_id and query session Runs. Do not create a fresh request automatically.
    accepted=request('POST',f'/sessions/{session}/messages',json=body).json()
    run=accepted['run_id'];path=f'/sessions/{session}/runs/{run}'
    for _ in range(120):
        state=request('GET',path).json()
        print(state['status'])
        if state['status'] in ('completed','failed','cancelled'):break
        time.sleep(1)
    else:
        print('Still active or reconciling; no retry or rerun was sent.')
        raise SystemExit(2)
    steps=request('GET',path+'/events',params={'after':0,'page_size':100}).json()
    print(json.dumps(steps,ensure_ascii=False))
    report=request('GET',path+'/report')
    with open('demo-run-report.md','wb') as file:file.write(report.content)
    # Explicit stop: request('POST',path+'/abort'); then GET until termination is confirmed.
    # SSE: GET /events?session_id=... with timeout=None; consume event: change and GET current state.
