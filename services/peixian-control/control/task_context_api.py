from fastapi import Depends,Request
from . import task_context
from .backend_contract import error

def register(app):
    from .app import PREFIX,normal,session_owned,current_authority
    from .agents import runtime as agents
    def profile(store,uid,sid,requested=None):
        row=store.one('SELECT agent_id FROM session_task_contexts WHERE uid=? AND session_id=?',(uid,sid)) if store.schema_version()>=7 else None
        if not row:
            prior=store.one('SELECT request_ciphertext FROM business_runs WHERE uid=? AND session_id=? ORDER BY rowid LIMIT 1',(uid,sid))
            if prior:requested=agents.frozen_identity(store.decrypt(prior['request_ciphertext']))
        value=agents.select(uid,{'agent_id':requested or (row['agent_id'] if row else 'gambling-assistant')})
        agents.session(store,uid,sid,value);return value
    async def owned_session(sid,request,user):
        s=app.state.store
        if s.schema_version()<7:error('task_context_not_enabled','当前部署尚未启用多轮上下文。',409)
        local=await app.state.db_work.run(s.one,'SELECT 1 FROM business_runs WHERE uid=? AND session_id=?',(user['uid'],sid))
        if local:return
        other=await app.state.db_work.run(s.one,'SELECT 1 FROM business_runs WHERE session_id=?',(sid,))
        if other:error('session_not_found','会话不存在',404)
        await session_owned(request,user,sid)
    @app.get(PREFIX+'/sessions/{sid}/task-context')
    async def get_context(sid:str,request:Request,agent_id:str|None=None,user=Depends(normal)):
        await owned_session(sid,request,user)
        def read():
            s=app.state.store;p=profile(s,user['uid'],sid,agent_id)
            return task_context.public(task_context.ensure(s,user['uid'],sid,p))
        return await app.state.db_work.run(read)
    @app.delete(PREFIX+'/sessions/{sid}/task-context')
    async def clear_context(sid:str,request:Request,user=Depends(normal)):
        await owned_session(sid,request,user)
        def clear():
            from .idempotency import execute
            def operation():
                s=app.state.store
                with s.tx() as db:
                    current_authority(db,user)
                    return task_context.reset(s,user['uid'],sid,profile(s,user['uid'],sid))
            return execute(request,user,operation)
        return await app.state.db_work.run(clear)
    @app.get(PREFIX+'/sessions/{sid}/runs/{rid}/source')
    async def source(sid:str,rid:str,request:Request,user=Depends(normal)):
        return await app.state.db_work.run(task_context.source_info,app.state.store,user['uid'],sid,rid)
