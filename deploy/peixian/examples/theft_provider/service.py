"""Independent synthetic contract server. Refuses non-private listening addresses."""
import hmac,ipaddress,json,os
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from urllib.parse import urlsplit,parse_qs
from shared.theft_provider import CATALOG,ContractError,fixture_response,request_spec

def reverse(method,path,body):
    kind=next((k for k,(_,m,p) in CATALOG.items() if method==m and (path==p or '{subject}' in p and path.startswith(p.split('{')[0]))),None)
    if not kind:raise ContractError('not_found')
    def integer(key,default):
        try:return int(body.get(key,default))
        except (TypeError,ValueError):raise ContractError('invalid_request') from None
    q={'page':integer('pageNum',1),'page_size':integer('pageSize',20)}
    if kind in ('incidents','captures'):
        q.update(start=body.get('startTime'),end=body.get('endTime'))
        if kind=='incidents' and body.get('address'):q['address']=body['address']
        if 'lon' in body:
            if str(body.get('lat'))!='0.001' or str(body['lon']) not in ('0.001','0.002'):raise ContractError('synthetic_center_required')
            q['center']='DEMO-LOCATION-A' if str(body['lon'])=='0.001' else 'DEMO-LOCATION-B'
            from decimal import Decimal
            n=Decimal(str(body.get('scope')))*(1000 if kind=='incidents' else 1)
            if n!=int(n):raise ContractError('invalid_radius')
            q['radius_m']=int(n)
    elif kind=='tracks':q.update(subject=body.get('certificateNo'),start=body.get('beginTime'),end=body.get('endTime'))
    elif kind=='warnings':
        q.update(start=str(body.get('beginTime'))+' 00:00:00',end=str(body.get('endTime'))+' 23:59:59')
        if 'idCard' in body:q['subject']=body['idCard']
    else:q['subject']=path.rsplit('/',1)[-1]
    expected=request_spec(kind,q);wanted=expected.get('json',expected.get('query',{}))
    # No silent acceptance of unknown filters, writing APIs, or extra keys.
    if set(body)!=set(wanted) or any(str(body[k])!=str(v) for k,v in wanted.items()):raise ContractError('invalid_request')
    return kind,q
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def reply(self,status,value):
        raw=json.dumps(value,ensure_ascii=False).encode();self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def handle_query(self):
        if not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+self.server.token):return self.reply(401,{'error':'unauthorized'})
        url=urlsplit(self.path)
        if self.command=='GET' and url.path=='/health' and not url.query:return self.reply(200,{'ok':True,'synthetic':True})
        try:
            if self.command=='POST':
                length=int(self.headers.get('Content-Length','0'))
                if length<=0 or length>16384 or url.query or self.headers.get_content_type()!='application/json':raise ContractError('invalid_request')
                body=json.loads(self.rfile.read(length))
            else:
                params=parse_qs(url.query,keep_blank_values=True)
                if any(len(v)!=1 for v in params.values()):raise ContractError('invalid_request')
                body={k:v[0] for k,v in params.items()}
            if not isinstance(body,dict):raise ContractError('invalid_request')
            kind,q=reverse(self.command,url.path,body);return self.reply(200,fixture_response(kind,q))
        except (ValueError,TypeError,KeyError,ArithmeticError):return self.reply(400,{'error':'invalid_request'})
    do_GET=handle_query
    do_POST=handle_query
if __name__=='__main__':
    from pathlib import Path
    host=os.environ.get('THEFT_FIXTURE_HOST','127.0.0.1');port=int(os.environ.get('THEFT_FIXTURE_PORT','19463'))
    address=ipaddress.ip_address(host)
    if not address.is_private or address.is_unspecified:raise SystemExit('private bind required')
    token=Path(os.environ['THEFT_FIXTURE_KEY_FILE']).read_text().strip()
    if len(token)<32:raise SystemExit('invalid fixture credential')
    server=ThreadingHTTPServer((host,port),Handler);server.token=token;server.serve_forever()
