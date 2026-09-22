"""Provider operation uses fixed Gateway code and existing egress admission."""
import asyncio,contextlib
import httpx
from fastapi import HTTPException
from .plugin_test import specification
async def execute(request,app,value,rpc,parent,process):
    if value['args']!={}:raise HTTPException(422,'查询条件已冻结，请勿传入新条件。')
    config=app.state.settings;gate=app.state.runtime_management.gate
    admitted=await rpc('provider_begin',session_id=value['session_id'],message_id=parent)
    identity={'run_id':admitted['run_id'],'operation':admitted['operation']};plan=admitted['plan']
    async def call(action,**fields):return await rpc('provider_'+action,**identity,**fields)
    try:
        if value['tool']!=plan['tool_id']:raise HTTPException(409,'工具不在已确认范围内。')
        kind=plan['kind'];await call('authorize',module=kind)
        if (await call('reserve',module=kind))['reserved']:
            spec=specification(config.managed_root,plan['plugin_id'])
            gate.require_egress()
            if await request.is_disconnected():
                await call('complete',module=kind,status='cancelled')
                raise asyncio.CancelledError()
            await call('dispatch',module=kind)
            task=asyncio.create_task(process({**spec,'action':'invoke','tool':plan['tool_id'],'args':{'request':plan['request']}}))
            try:
                while not task.done():
                    done,_=await asyncio.wait({task},timeout=0.5)
                    if done:break
                    gate.require_egress();await call('authorize',module=kind)
                    if await request.is_disconnected():raise asyncio.CancelledError()
                response=await task
                await call('complete',module=kind,status='completed',response=response)
            except (ValueError,httpx.HTTPError,TimeoutError):await call('complete',module=kind,status='unknown')
            finally:
                if not task.done():task.cancel()
                await asyncio.gather(task,return_exceptions=True)
        item=(await call('read'))['state']['modules'].get(kind,{})
        if item.get('status')!='completed':raise HTTPException(409,'资料结果尚未确认，本轮不会重试。')
        return item['response']
    finally:
        with contextlib.suppress(httpx.HTTPError,HTTPException):await call('finish')
