"""Two synthetic accounts and one real slot; no model or external service calls."""
import argparse
import asyncio
from contextlib import AsyncExitStack
import importlib.util
import json
from pathlib import Path
import secrets
import time

ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('sdk',ROOT.parents[1]/'services/peixian-control/examples/console_client.py')
sdk=importlib.util.module_from_spec(spec);spec.loader.exec_module(sdk)


async def run(root, repeat=False):
    cfg=json.loads((root/'platform.json').read_text())
    assert cfg['deployment_id']=='synthetic-pr7c-local' and cfg['public_url']=='https://127.0.0.1:19450'
    assert cfg['max_runtimes']==1 and cfg['runtime_pool']['idle_timeout_seconds']==60
    assert cfg['runtime_pool']['idle_pause_enabled'] is True
    private=root/'acceptance-private.json'
    assert private.exists() is repeat, 'Use a fresh namespace or explicitly repeat existing synthetic accounts'
    report={'status':'running','scope':'local_real_container_idle_smoke','checks':[]}
    def record(name,**values):
        report['checks'].append({'name':name,'status':'passed',**values})
        (root/'result.json').write_text(json.dumps(report,indent=2));print(name,flush=True)
    async with AsyncExitStack() as stack:
        async def client(): return await stack.enter_async_context(sdk.ConsoleClient(cfg['public_url'],ca_file=root/'tls/certificate.pem'))
        admin=await client()
        data=json.loads(private.read_text()) if repeat else None
        if data is None:
            password=(root/'data/secrets/console-admin.password').read_text().strip()
            await admin.login('admin',password);changed=secrets.token_urlsafe(24)
            await admin.change_password(password,changed);await admin.login('admin',changed)
            data={'admin_password':changed,'users':[]};private.write_text(json.dumps(data))
        else:
            await admin.login('admin',data['admin_password'])
        clients=[]
        for i in range(2):
            if repeat:
                c=await client();await c.login(data['users'][i]['username'],data['users'][i]['password'])
                state=await c.runtime_status();assert state['status']=='paused' and state['job'] is None
                clients.append(c)
                continue
            name='pr7c-local-'+str(i);pw=secrets.token_urlsafe(24)
            result=await admin.request('POST','/admin/users',json={'username':name,'password':pw})
            c=await client();await c.login(name,pw);changed=secrets.token_urlsafe(24)
            await c.change_password(pw,changed);await c.login(name,changed)
            clients.append(c);data['users'].append({'username':name,'password':changed,'id':result['user']['id']})
            private.write_text(json.dumps(data))
        a,b=clients
        async def until(c,state):
            async with asyncio.timeout(300):
                while True:
                    r=await c.runtime_status()
                    if (r['ready'] if state=='ready' else r['status']=='paused' and r['job'] is None): return r
                    await asyncio.sleep(1)
        await a.start_runtime();await until(a,'ready')
        session=await a.create_session('PR7C synthetic retained history')
        file=await a.request('POST','/files',files={'file':('idle.txt',b'PR7C synthetic marker','text/plain')})
        assert 'PR7C synthetic marker' in (await a.wait_for_file(file['id']))['text']
        data.update(session_id=session['id'],file_id=file['id']);private.write_text(json.dumps(data))
        since=time.monotonic()
        assert (await b.start_runtime())['job']['status']=='waiting_capacity'
        record('A_ready_with_file_B_waiting')
        paused=await until(a,'paused')
        elapsed=time.monotonic()-since
        assert paused['stop_reason']=='idle_timeout' and elapsed>=55
        record('A_automatic_idle_pause_after_threshold',elapsed_seconds=round(elapsed,2))
        await until(b,'ready')
        assert (await admin.request('GET','/admin/users'))['capacity']['reserved']==1
        record('B_promoted_after_real_idle_release_without_oversell')
        # Explicitly stop B, then return to A. No message is automatically submitted.
        state=await b.runtime_status();await b.stop_runtime(state['state_version']);await until(b,'paused')
        await a.start_runtime();await until(a,'ready')
        assert any(row['id']==session['id'] for row in await a.sessions())
        assert 'PR7C synthetic marker' in (await a.wait_for_file(file['id']))['text']
        record('explicit_resume_preserves_history_and_file')
        state=await a.runtime_status();await a.stop_runtime(state['state_version']);await until(a,'paused')
        record('all_synthetic_runtimes_stopped_data_retained')
    report['status']='passed';(root/'result.json').write_text(json.dumps(report,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--repeat',action='store_true')
    args=p.parse_args();asyncio.run(run(args.root.resolve(),args.repeat))
