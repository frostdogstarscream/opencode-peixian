"""One lifespan and event loop for many isolated synthetic browser clients."""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from client_helpers import TestClient


def test_sibling_clients_share_lifespan_loop_but_not_cookie_jar():
    starts, stops = [], []

    @asynccontextmanager
    async def lifespan(app):
        starts.append(asyncio.get_running_loop())
        yield {"synthetic_state": "shared"}
        stops.append(asyncio.get_running_loop())

    app = FastAPI(lifespan=lifespan)

    @app.get("/")
    async def read(request: Request):
        assert asyncio.get_running_loop() is starts[0]
        return {"cookie": request.cookies.get("browser"), "state": request.state.synthetic_state}

    with TestClient(app) as canonical:
        canonical.cookies.set("browser", "administrator")
        with TestClient(app) as sibling:
            # login_user historically enters once and callers sometimes enter again.
            assert sibling.__enter__() is sibling
            sibling.cookies.set("browser", "ordinary-user")
            assert sibling.portal is canonical.portal
            assert sibling.get("/").json() == {"cookie": "ordinary-user", "state": "shared"}
            assert canonical.get("/").json()["cookie"] == "administrator"
        assert len(starts) == 1 and stops == []
        assert canonical.get("/").status_code == 200
        unentered = TestClient(app)
        assert unentered.get("/").json()["cookie"] is None
    assert len(starts) == len(stops) == 1
    assert unentered.is_closed and unentered.portal is None
    assert canonical.is_closed
