"""Explicit self-service lifecycle; no arbitrary upstream forwarding."""
from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from .concurrency import blocking_endpoint
from .runtime_pool import public_status, start, stop, reject


def register_runtime(app):
    from .app import PREFIX, normal, body_fields
    from .idempotency import execute, key

    def supported():
        if not app.state.store.on_demand():
            reject("runtime_mode_unsupported", "当前部署由管理员管理助手启停")

    @app.get(PREFIX + "/me/runtime")
    @blocking_endpoint(app)
    def status(request: Request, user=Depends(normal)):
        supported()
        with app.state.store.read(snapshot=True) as db:
            return public_status(app.state.store, db, user["uid"])

    async def mutate(request, user, action):
        key(request)
        request.state.json_body = await request.json()
        fields = () if action == "start" else ("expected_state_version", "start_job_id")
        data = body_fields(request.state.json_body, fields)
        if action == "stop" and type(data.get("expected_state_version")) is not int:
            reject("runtime_state_required", "停止操作需要当前状态版本", 422)
        if "start_job_id" in data and not isinstance(data["start_job_id"], str):
            reject("runtime_start_invalid", "启动申请标识无效", 422)
        def operation():
            supported()
            with app.state.store.tx() as db:
                from .store import ident, now
                result = start(app.state.store, db, user["uid"]) if action == "start" else stop(app.state.store, db, user["uid"], **data)
                db.execute("INSERT INTO audit(id,actor,actor_role,action,target,result,created) VALUES(?,?,'user',?,?,'success',?)", (ident(), user["uid"], "runtime.self." + action, user["uid"], now()))
                return result
        result = await app.state.db_work.run(execute, request, user, operation)
        return JSONResponse(result, status_code=202 if result["accepted"] else 200)

    @app.post(PREFIX + "/me/runtime/start")
    async def start_runtime(request: Request, user=Depends(normal)):
        return await mutate(request, user, "start")

    @app.post(PREFIX + "/me/runtime/stop")
    async def stop_runtime(request: Request, user=Depends(normal)):
        return await mutate(request, user, "stop")
