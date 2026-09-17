"""Synthetic local PR7A acceptance. Only the fixed isolated namespace is mutable."""
import argparse
import asyncio
from contextlib import AsyncExitStack
import importlib.util
import json
from pathlib import Path
import secrets
import subprocess
import time

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('sdk', ROOT.parents[1] / 'services/peixian-control/examples/console_client.py')
sdk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sdk)


async def run(args):
    root = args.root.resolve()
    restored = args.stage == 'restored'
    cfg = json.loads((root / ('restored.json' if restored else 'platform.json')).read_text())
    assert (cfg['deployment_id'], cfg['public_url']) == (('synthetic-pr7a-restored', 'https://127.0.0.1:19448') if restored else ('synthetic-pr7a-local', 'https://127.0.0.1:19447'))
    assert cfg['max_runtimes'] == 2 and cfg['runtime_pool']['capacity_wait_enabled'] is False
    report = {'status': 'running', 'scope': 'local_real_containers_synthetic_accounts', 'checks': []}
    def record(name):
        report['checks'].append({'name': name, 'status': 'passed'})
        args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(name, flush=True)
    def containers():
        return subprocess.check_output(['docker', 'ps', '-q', '--filter', 'label=peixian.deployment='+cfg['deployment_id'], '--filter', 'label=peixian.runtime_id'], text=True).splitlines()
    async with AsyncExitStack() as stack:
        async def client():
            return await stack.enter_async_context(sdk.ConsoleClient(cfg['public_url'], ca_file=root/('restored-data/tls/certificate.pem' if restored else 'tls/certificate.pem')))
        admin = await client()
        state_path = root/'acceptance-private.json'
        if args.stage == 'prepare':
            assert not state_path.exists(), 'existing test accounts preserved'
            password = (root/'data/secrets/console-admin.password').read_text().strip()
            await admin.login('admin', password)
            new = secrets.token_urlsafe(24)
            await admin.change_password(password, new)
            await admin.login('admin', new)
            data = {'admin_password': new, 'users': []}
            state_path.write_text(json.dumps(data))
            for i in range(5):
                password = secrets.token_urlsafe(24)
                result = await admin.request('POST', '/admin/users', json={'username': 'pr7-local-'+str(i), 'password': password})
                assert result['job'] is None
                c = await client()
                await c.login('pr7-local-'+str(i), password)
                changed = secrets.token_urlsafe(24)
                await c.change_password(password, changed)
                data['users'].append({'username': 'pr7-local-'+str(i), 'password': changed, 'id': result['user']['id']})
                state_path.write_text(json.dumps(data))
            users = await admin.request('GET', '/admin/users')
            assert users['capacity']['reserved'] == 0 and not containers()
            record('A01_five_accounts_zero_runtime_containers_and_reservations')
            report['status'] = 'passed'
            args.output.write_text(json.dumps(report, indent=2))
            return
        data = json.loads(state_path.read_text())
        await admin.login('admin', data['admin_password'])
        clients = []
        for u in data['users']:
            c = await client()
            await c.login(u['username'], u['password'])
            clients.append(c)
        async def ready(c, desired=None, timeout=240):
            async with asyncio.timeout(timeout):
                while True:
                    r = await c.runtime_status()
                    if r.get('ready') and (desired is None or r['revision'] == desired):
                        return r
                    await asyncio.sleep(1)
        async def stopped(c):
            async with asyncio.timeout(180):
                while True:
                    r = await c.runtime_status()
                    if r['status'] == 'paused' and r['job'] is None:
                        return r
                    await asyncio.sleep(1)
        if restored:
            assert not containers()
            c = clients[0]
            await c.start_runtime()
            await ready(c)
            assert any(s['id'] == data['session_id'] for s in await c.sessions())
            assert 'PR7 synthetic persistent marker' in (await c.wait_for_file(data['file_id']))['text']
            for other in clients[2:]:
                assert (await other.runtime_status())['status'] == 'unprovisioned'
            record('D05_restored_identical_account_session_file_and_three_metadata_accounts')
            state = await c.runtime_status()
            await c.stop_runtime(state['state_version'])
            await stopped(c)
            assert not containers()
            record('restored_runtime_explicit_start_stop')
        if args.stage == 'exercise':
            for c in clients[:2]:
                first = await c.start_runtime()
                second = await c.start_runtime()
                if first['job'] is not None:
                    assert first['job']['id'] == second['job']['id']
                else:
                    assert not first['accepted'] and not second['accepted']
                await ready(c)
            assert len(containers()) == 6
            users = await admin.request('GET', '/admin/users')
            assert users['capacity']['reserved'] == 2
            record('A02_A03_two_real_runtime_trios_and_deduplicated_start')
            for c in clients[2:]:
                try:
                    await c.start_runtime()
                    raise AssertionError('capacity not enforced')
                except sdk.ConsoleError as e:
                    assert e.status == 409
                assert (await c.runtime_status())['status'] == 'unprovisioned'
            assert len(containers()) == 6
            record('A01_remaining_three_metadata_only_capacity_rejected')
            c = clients[0]
            session = await c.create_session('PR7 synthetic persistent history')
            upload = await c.request('POST', '/files', files={'file': ('pr7-persistent.txt', b'PR7 synthetic persistent marker', 'text/plain')})
            parsed = await c.wait_for_file(upload['id'])
            assert 'PR7 synthetic persistent marker' in parsed['text']
            data.update(session_id=session['id'], file_id=upload['id'])
            state_path.write_text(json.dumps(data))
            old = await c.runtime_status()
            await c.stop_runtime(old['state_version'])
            await stopped(c)
            assert len(containers()) == 3
            assert (await clients[1].runtime_status())['ready']
            record('A07_stop_releases_only_own_slot_other_account_ready')
            await c.request('POST', '/skills', json={'name':'pr7-local-'+str(int(time.time())),'description':'Synthetic skill','content':'Summarize synthetic input only.','enabled':True})
            target = (await c.runtime_status())['desired']
            assert len(containers()) == 3
            await c.start_runtime()
            await ready(c, target)
            assert any(x['id'] == session['id'] for x in await c.sessions())
            assert 'PR7 synthetic persistent marker' in (await c.wait_for_file(upload['id']))['text']
            try:
                await c.stop_runtime(old['state_version'])
                raise AssertionError('stale stop accepted')
            except sdk.ConsoleError as e:
                assert e.status == 409
            record('A07_A08_restart_preserves_session_file_applies_skill_rejects_stale_stop')
            # Keep the synthetic environments stopped for backup; no deletion.
            for c in clients[:2]:
                r = await c.runtime_status()
                await c.stop_runtime(r['state_version'])
                await stopped(c)
            assert not containers()
            record('two_runtimes_stopped_volumes_retained')
        report['status'] = 'passed'
        args.output.write_text(json.dumps(report, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--stage', choices=('prepare','exercise','restored'), required=True)
    asyncio.run(run(p.parse_args()))
