"""Exercise the actual console GET route with the integrated transient overlay."""
import httpx

from test_control import context, create_user, login_user, P
from test_live_text import seed, delta_event, native


def test_messages_overlay_remains_owner_checked_and_publicly_filtered(context, monkeypatch):
    store, app, administrator = context
    owner = create_user(administrator, "owner-a")
    create_user(administrator, "owner-b")
    saved = native()

    async def fake_upstream(request, user, method, path, **kwargs):
        assert method == "GET"
        if path == "/session/session":
            if user["uid"] != owner["id"]:
                return httpx.Response(404, json={"message": "not found"})
            return httpx.Response(200, json={"id": "session", "directory": "/workspace"})
        assert user["uid"] == owner["id"] and path == "/session/session/message"
        return httpx.Response(200, json=saved)

    monkeypatch.setattr("control.app.upstream", fake_upstream)
    first = login_user(app, "owner-a")
    other = login_user(app, "owner-b")
    cache = app.state.live_text
    seed(cache, owner["id"])
    assert cache.observe(owner["id"], delta_event(3, "synthetic live answer"), "owner")
    try:
        response = first.get(P + "/sessions/session/messages")
        assert response.status_code == 200
        answer = response.json()["items"][0]
        assert answer["parts"][0]["text"] == "synthetic live answer"
        assert "completed" not in answer["info"]["time"]
        response = other.get(P + "/sessions/session/messages")
        assert response.status_code == 404
        assert "synthetic live answer" not in response.text

        saved[:] = native(text="saved final answer", done=True)
        response = first.get(P + "/sessions/session/messages")
        assert response.json()["items"][0]["parts"][0]["text"] == "saved final answer"
        assert cache.stats()["parts"] == 0

        seed(cache, owner["id"], start=10)
        cache.observe(owner["id"], delta_event(12, "must not replace tool"), "owner")
        saved[:] = native(kind="tool")
        saved[0]["parts"][0]["tool"] = "unknown"
        saved[0]["parts"][0]["state"] = {"status": "completed", "input": {"password": "synthetic-private"}}
        response = first.get(P + "/sessions/session/messages")
        assert "must not replace tool" not in response.text
        assert "synthetic-private" not in response.text
        assert response.json()["items"][0]["parts"][0]["type"] == "tool"
    finally:
        first.__exit__(None, None, None)
        other.__exit__(None, None, None)
