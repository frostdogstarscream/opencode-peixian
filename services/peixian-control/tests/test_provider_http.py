import asyncio,importlib.util,json,os,threading,subprocess
from pathlib import Path
from http.server import ThreadingHTTPServer
import httpx,pytest
from shared.theft_provider import CATALOG,request_spec,parse_response
from test_provider_flow import query
ROOT=Path(__file__).resolve().parents[3]
@pytest.fixture
def fixture_http():
 path=ROOT/'deploy/peixian/examples/theft_provider/service.py'
 spec=importlib.util.spec_from_file_location('provider_fixture',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 server=ThreadingHTTPServer(('127.0.0.1',0),m.Handler);server.token='isolated-synthetic-contract-key-only'
 thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
 yield f'http://127.0.0.1:{server.server_port}',server.token
 server.shutdown();thread.join();server.server_close()
@pytest.mark.parametrize('kind',CATALOG)
def test_real_js_plugin_http(fixture_http,kind):
 url,key=fixture_http;entry=ROOT/'deploy/peixian/examples/theft_provider'/kind/'entry.mjs';request=request_spec(kind,query(kind))
 script='''import plugin from ENTRY;
const seen=[];const platform={connections:{request:async(alias,input)=>{seen.push(input.path);const url=new URL(input.path,URLBASE);for(const [k,v] of Object.entries(input.query||{}))url.searchParams.set(k,v);const response=await fetch(url,{method:input.method,headers:{Authorization:AUTH,'Content-Type':'application/json'},...(input.json?{body:JSON.stringify(input.json)}:{})});return {status:response.status,data:await response.json()};}}};
const p=await plugin({},{},platform);let bypass=false;try{await p.tool[TOOL].execute({})}catch{bypass=true}
const output=JSON.parse(await p.tool[TOOL].execute({request:REQUEST}));console.log(JSON.stringify({output,bypass,seen}));'''
 for k,v in {'ENTRY':entry.as_uri(),'URLBASE':url,'AUTH':'Bearer '+key,'TOOL':'peixian_query_'+kind,'REQUEST':request}.items():script=script.replace(k,json.dumps(v))
 runner=os.environ.get('BUN_EXECUTABLE','bun');result=subprocess.run([runner,'-e',script],capture_output=True,text=True,timeout=15,check=True)
 data=json.loads(result.stdout);assert data['bypass'] and len(data['seen'])==1
 assert parse_response(kind,query(kind),data['output'])['records']
 with httpx.Client(trust_env=False) as c:
  assert c.get(url+'/health').status_code==401
  assert c.post(url+'/jq/search',json={'url':'http://elsewhere'},headers={'Authorization':'Bearer '+key}).status_code==400

def test_bad_fields_and_non_whole_days():
 from shared.theft_provider import fixture_response,ContractError,normalize_query
 p=fixture_response('tracks',query('tracks'));p['data']['points'][0]['deviceName']={'html':'bad'}
 with pytest.raises(ContractError):parse_response('tracks',query('tracks'),p)
 with pytest.raises(ContractError):normalize_query('warnings',{**query('warnings'),'start':'2026-09-20 12:00:00'})
 with pytest.raises(ContractError):normalize_query('captures',{**query('captures'),'subject':'DEMO-PERSON-001'})
 p=fixture_response('captures',{**query('captures'),'start':'2026-09-01 00:00:00','end':'2026-09-02 23:59:59'})
 assert p['data']['total']==0
