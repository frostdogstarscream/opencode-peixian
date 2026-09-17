"""Three synthetic accounts, two real slots, no paid models or external data."""
import argparse
import asyncio
from contextlib import AsyncExitStack
import importlib.util
import json
from pathlib import Path
import secrets
import subprocess

ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('sdk',ROOT.parents[1]/'services/peixian-control/examples/console_client.py')
sdk=importlib.util.module_from_spec(spec);spec.loader.exec_module(sdk)


async def run(args):
    root=args.root.resolve();cfg=json.loads((root/'platform.json').read_text())
    assert cfg['deployment_id']=='synthetic-pr7b-local' and cfg['public_url']=='https://127.0.0.1:19449'
    assert cfg['max_runtimes']==2 and cfg['runtime_pool']['capacity_wait_enabled'] is True
    report={'status':'running','checks':[],'scope':'local_synthetic_real_containers_no_load'}
    def record(name):
        report['checks'].append({'name':name,'status':'passed'})
        args.output.write_text(json.dumps(report,indent=2));print(name,flush=True)
    state=root/'acceptance-private.json'
    async with AsyncExitStack() as stack:
        async def client(): return await stack.enter_async_context(sdk.ConsoleClient(cfg['public_url'],ca_file=root/'tls/certificate.pem'))
        admin=await client()
        if args.stage=='prepare':
            assert not state.exists()
            pw=(root/'data/secrets/console-admin.password').read_text().strip()
            await admin.login('admin',pw);new=secrets.token_urlsafe(24)
            await admin.change_password(pw,new);await admin.login('admin',new)
            data={'admin_password':new,'users':[]}
            state.write_text(json.dumps(data))
            for i in range(3):
                pw=secrets.token_urlsafe(24);name='pr7b-local-'+str(i)
                result=await admin.request('POST','/admin/users',json={'username':name,'password':pw})
                c=await client();await c.login(name,pw);new=secrets.token_urlsafe(24)
                await c.change_password(pw,new);await c.login(name,new)
                started=await c.start_runtime()
                data['users'].append({'username':name,'password':new,'id':result['user']['id'],'job_id':started['job']['id']})
                state.write_text(json.dumps(data))
                assert started['job']['status']==('queued' if i<2 else 'waiting_capacity')
            record('three_persistent_start_requests_two_reserved_one_waiting')
        else:
            data=json.loads(state.read_text());await admin.login('admin',data['admin_password'])
            clients=[]
            for u in data['users']:
                c=await client();await c.login(u['username'],u['password']);clients.append(c)
            if args.stage=='queue':
                for i,client in enumerate(clients):
                    result=await client.start_runtime()
                    assert result['job']['status']==('queued' if i<2 else 'waiting_capacity')
                    data['users'][i]['job_id']=result['job']['id']
                state.write_text(json.dumps(data))
                record('existing_synthetic_accounts_requeued_without_new_data')
                report['status']='passed';args.output.write_text(json.dumps(report,indent=2));return
            a,b,c=clients
            async def until(client,status):
                async with asyncio.timeout(240):
                    while True:
                        r=await client.runtime_status()
                        if (r['ready'] if status=='ready' else r['status']=='paused' and r['job'] is None): return r
                        await asyncio.sleep(1)
            waiting=await c.runtime_status()
            assert waiting['job']['id']==data['users'][2]['job_id'] and waiting['job']['status']=='waiting_capacity'
            assert waiting['waiting']['approximate_position']==1
            record('waiting_identity_and_fifo_survive_control_restart')
            await until(a,'ready');await until(b,'ready')
            assert (await c.runtime_status())['job']['status']=='waiting_capacity'
            record('A_B_real_runtime_ready_C_still_waiting')
            session=await a.create_session('PR7B retained A history')
            file=await a.request('POST','/files',files={'file':('pr7b.txt',b'PR7B retained synthetic marker','text/plain')})
            assert 'PR7B retained synthetic marker' in (await a.wait_for_file(file['id']))['text']
            r=await a.runtime_status();await a.stop_runtime(r['state_version']);await until(a,'paused')
            await until(c,'ready')
            assert (await b.runtime_status())['ready']
            users=await admin.request('GET','/admin/users');assert users['capacity']['reserved']==2
            record('A_confirmed_stop_promotes_C_without_interrupting_B_or_overselling')
            # Returning A queues behind current allocations; cancelling does not stop B/C.
            request=await a.start_runtime();assert request['job']['status']=='waiting_capacity'
            await a.stop_runtime(request['runtime']['state_version'],start_job_id=request['job']['id'])
            assert (await a.runtime_status())['job'] is None
            record('returning_A_wait_can_cancel_without_new_allocation')
            for client in (b,c):
                r=await client.runtime_status();await client.stop_runtime(r['state_version']);await until(client,'paused')
            await a.start_runtime();await until(a,'ready')
            assert any(s['id']==session['id'] for s in await a.sessions())
            assert 'PR7B retained synthetic marker' in (await a.wait_for_file(file['id']))['text']
            r=await a.runtime_status();await a.stop_runtime(r['state_version']);await until(a,'paused')
            record('A_history_and_file_preserved_after_capacity_transfer_and_restart')
        report['status']='passed';args.output.write_text(json.dumps(report,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--stage',choices=('prepare','queue','exercise'),required=True)
    asyncio.run(run(p.parse_args()))
