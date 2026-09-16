from copy import deepcopy
import json

import pytest

from control.live_text import LiveTextCache


class Clock:
    now = 0.0
    def __call__(self):
        return self.now


def event(number, kind, properties, directory="/workspace"):
    return {"directory": directory, "payload": {"id": "evt_" + str(number),
                                               "type": kind, "properties": properties}}


def message_event(number, *, sid="session", mid="message", role="assistant", done=False):
    info = {"id": mid, "sessionID": sid, "role": role, "time": {"created": 1}}
    if done:
        info["time"]["completed"] = 2
    return event(number, "message.updated", {"sessionID": sid, "info": info})


def part_event(number, *, sid="session", mid="message", pid="part", text="", kind="text", done=False, synthetic=False):
    part = {"id": pid, "messageID": mid, "sessionID": sid, "type": kind, "text": text, "time": {"start": 1}}
    if done:
        part["time"]["end"] = 2
    if synthetic:
        part["synthetic"] = True
    return event(number, "message.part.updated", {"sessionID": sid, "part": part, "time": 1})


def delta_event(number, text, *, sid="session", mid="message", pid="part", field="text"):
    return event(number, "message.part.delta", {"sessionID": sid, "messageID": mid, "partID": pid,
                                               "field": field, "delta": text})


def native(*, sid="session", mid="message", pid="part", text="", role="assistant", kind="text", done=False, synthetic=False):
    info = {"id": mid, "sessionID": sid, "role": role, "time": {"created": 1}}
    part = part_event(0, sid=sid, mid=mid, pid=pid, text=text, kind=kind, done=done, synthetic=synthetic)["payload"]["properties"]["part"]
    return [{"info": info, "parts": [part]}]


def seed(cache, uid="account", stream="owner", *, sid="session", mid="message", pid="part", start=1):
    assert cache.acquire(uid, stream)
    assert cache.observe(uid, message_event(start, sid=sid, mid=mid), stream)
    assert cache.observe(uid, part_event(start + 1, sid=sid, mid=mid, pid=pid), stream)


def rendered(cache, uid="account", *, sid="session", mid="message", pid="part"):
    return cache.overlay(uid, sid, native(sid=sid, mid=mid, pid=pid))[0]["parts"][0]["text"]


def test_order_dedup_and_authoritative_part_update():
    cache = LiveTextCache()
    seed(cache)
    assert cache.observe("account", delta_event(20, "first"), "owner")
    assert not cache.observe("account", delta_event(20, "first"), "owner")
    # IDs are never sorted; current owner wire order is the only order contract.
    assert cache.observe("account", delta_event(19, " second"), "owner")
    assert rendered(cache) == "first second"
    assert cache.observe("account", part_event(21, text="canonical"), "owner")
    assert cache.observe("account", delta_event(22, " tail"), "owner")
    original = native()
    assert cache.overlay("account", "session", original)[0]["parts"][0]["text"] == "canonical tail"
    assert original[0]["parts"][0]["text"] == ""


def test_eviction_requests_only_affected_owner_to_resync():
    cache = LiveTextCache(max_part_bytes=4)
    seed(cache, "account-a", "stream-a")
    seed(cache, "account-b", "stream-b")
    assert not cache.observe("account-a", delta_event(3, "oversized private content"), "stream-a")
    assert not cache.take_resync("account-a", "stream-b")
    assert not cache.take_resync("account-b", "stream-b")
    assert cache.take_resync("account-a", "stream-a")
    assert not cache.take_resync("account-a", "stream-a")
    assert cache.stats()["evictions"]["part_bytes"] == 1
    assert "account-a" not in json.dumps(cache.stats()) and "private content" not in json.dumps(cache.stats())
    assert cache.overlay("account-a", "session", native(text="authoritative complete text"))[0]["parts"][0]["text"] == "authoritative complete text"


def test_cross_account_capacity_eviction_and_expiry_are_bounded():
    clock = Clock()
    cache = LiveTextCache(max_parts=1, ttl_seconds=2, owner_ttl_seconds=5, clock=clock)
    seed(cache, "account-a")
    seed(cache, "account-b")
    assert cache.take_resync("account-a", "owner")
    assert not cache.take_resync("account-b", "owner")
    clock.now = 3
    stats = cache.stats()
    assert stats["evictions"]["part_capacity"] == 1
    assert stats["evictions"]["part_ttl"] == 1
    assert cache.take_resync("account-b", "owner")
    clock.now = 6
    assert cache.stats()["owners"] == cache.stats()["resync_pending"] == 0
    assert cache.stats()["evictions"]["owner_ttl"] == 2


def test_released_owner_does_not_leave_pending_resync():
    cache = LiveTextCache(max_part_bytes=1)
    seed(cache)
    cache.observe("account", delta_event(3, "large"), "owner")
    cache.release("account", "owner")
    assert cache.stats()["resync_pending"] == 0


def test_account_session_message_and_part_boundaries():
    cache = LiveTextCache()
    seed(cache, "account-a")
    seed(cache, "account-b")
    cache.observe("account-a", delta_event(3, "alpha"), "owner")
    cache.observe("account-b", delta_event(3, "beta"), "owner")
    assert rendered(cache, "account-a") == "alpha"
    assert rendered(cache, "account-b") == "beta"
    assert rendered(cache, "unknown") == ""
    assert rendered(cache, "account-a", sid="other") == ""
    assert rendered(cache, "account-a", mid="other") == ""
    assert rendered(cache, "account-a", pid="other") == ""
    assert cache.overlay("account-a", "session", []) == []
    empty_parts = [{"info": native()[0]["info"], "parts": []}]
    assert cache.overlay("account-a", "session", empty_parts) == empty_parts


def test_single_stream_owner_and_handover_clear_incomplete_text():
    clock = Clock()
    cache = LiveTextCache(clock=clock, owner_ttl_seconds=10)
    seed(cache)
    assert not cache.acquire("account", "second-browser")
    assert not cache.observe("account", delta_event(3, "wrong-order"), "second-browser")
    assert cache.observe("account", delta_event(3, "first-owner"), "owner")
    cache.release("account", "second-browser")
    assert rendered(cache) == "first-owner"
    cache.release("account", "owner")
    assert rendered(cache) == ""
    assert cache.acquire("account", "second-browser")
    assert not cache.observe("account", delta_event(4, "missing-prefix"), "second-browser")
    assert rendered(cache) == ""
    seed(cache, stream="second-browser", start=10)
    cache.observe("account", delta_event(12, "fresh"), "second-browser")
    clock.now = 11
    assert cache.acquire("account", "third-browser")
    assert rendered(cache) == ""
    assert not cache.observe("account", delta_event(13, "late-old-owner"), "second-browser")


@pytest.mark.parametrize("kind,synthetic,role", [
    ("reasoning", False, "assistant"), ("tool", False, "assistant"),
    ("text", True, "assistant"), ("text", False, "user"),
])
def test_reasoning_tool_synthetic_user_and_unknown_delta_never_cached(kind, synthetic, role):
    cache = LiveTextCache()
    assert cache.acquire("account", "owner")
    assert not cache.observe("account", delta_event(1, "unknown payload"), "owner")
    cache.observe("account", message_event(2, role=role), "owner")
    cache.observe("account", part_event(3, kind=kind, synthetic=synthetic, text="private fixture"), "owner")
    assert not cache.observe("account", delta_event(4, "private tail"), "owner")
    assert cache.stats()["text_bytes"] == 0
    assert rendered(cache) == ""
    assert "private fixture" not in repr(cache.__dict__)
    assert "private tail" not in repr(cache.__dict__)


def test_bad_envelopes_wrong_workspace_and_fields_are_ignored():
    cache = LiveTextCache()
    seed(cache)
    cases = [None, {}, {"payload": {"type": "server.connected"}},
             event(3, "message.part.delta", {}, directory="/other"),
             delta_event(4, "ignored", field="reasoning"), delta_event(5, {"arbitrary": "payload"})]
    no_id = delta_event(6, "ignored")
    no_id["payload"].pop("id")
    cases.append(no_id)
    for value in cases:
        assert not cache.observe("account", value, "owner")
    assert rendered(cache) == ""
    mismatch = part_event(7)
    mismatch["payload"]["properties"]["part"]["sessionID"] = "different"
    assert not cache.observe("account", mismatch, "owner")


def test_native_completed_parts_messages_and_abort_are_authoritative():
    cache = LiveTextCache()
    seed(cache)
    cache.observe("account", delta_event(3, "unfinished"), "owner")
    saved = native(text="final native text", done=True)
    assert cache.overlay("account", "session", saved) == saved
    assert cache.stats()["parts"] == 0
    seed(cache, start=10)
    cache.observe("account", delta_event(12, "unfinished"), "owner")
    assert not cache.observe("account", part_event(13, text="done", done=True), "owner")
    assert rendered(cache) == ""
    seed(cache, start=20)
    cache.observe("account", delta_event(22, "unfinished"), "owner")
    cache.observe("account", message_event(23, done=True), "owner")
    assert cache.stats()["parts"] == 0
    assert not cache.observe("account", delta_event(24, "late"), "owner")
    seed(cache, start=30)
    cache.observe("account", delta_event(32, "unfinished"), "owner")
    aborted = native()
    aborted[0]["info"]["error"] = {"name": "MessageAbortedError"}
    assert cache.overlay("account", "session", aborted) == aborted
    assert cache.stats()["parts"] == 0


def test_native_text_never_regresses_or_gets_overridden_by_nonmatching_cache():
    cache = LiveTextCache()
    seed(cache)
    cache.observe("account", delta_event(3, "short"), "owner")
    for text in ("longer authoritative text", "other"):
        saved = native(text=text)
        assert cache.overlay("account", "session", saved) == saved
    assert cache.stats()["parts"] == 0


def test_utf8_byte_limits_drop_oversized_part_without_publishing_truncation():
    cache = LiveTextCache(max_part_bytes=7)
    seed(cache)
    cache.observe("account", delta_event(3, "中文"), "owner")
    assert cache.stats()["text_bytes"] == 6
    assert rendered(cache) == "中文"
    assert not cache.observe("account", delta_event(4, "字"), "owner")
    assert rendered(cache) == ""
    assert cache.stats()["text_bytes"] == 0
    assert not cache.observe("account", delta_event(5, "suffix"), "owner")


def test_total_account_part_message_and_event_bounds():
    cache = LiveTextCache(max_part_bytes=8, max_total_bytes=10, max_account_bytes=8,
                          max_parts=2, max_messages=2, max_seen_events=3, max_owners=2)
    seed(cache, "one")
    cache.observe("one", delta_event(3, "123456"), "owner")
    seed(cache, "two")
    cache.observe("two", delta_event(3, "123456"), "owner")
    assert cache.stats()["text_bytes"] <= 10
    assert not cache.acquire("three", "owner")
    for number in range(10, 25):
        cache.observe("two", message_event(number, mid="message-" + str(number)), "owner")
    state = cache.stats()
    assert state["parts"] <= 2 and state["messages"] <= 2 and state["seen_events"] <= 3
    assert state["owners"] <= 2 and state["maximum_account_bytes"] <= 8


def test_ttl_expires_text_even_when_connection_heartbeats_continue():
    clock = Clock()
    cache = LiveTextCache(clock=clock, ttl_seconds=5, owner_ttl_seconds=20)
    seed(cache)
    cache.observe("account", delta_event(3, "transient"), "owner")
    clock.now = 4
    assert cache.acquire("account", "owner")
    assert rendered(cache) == "transient"
    clock.now = 6
    assert cache.acquire("account", "owner")
    assert rendered(cache) == ""
    assert cache.stats()["text_bytes"] == 0
    assert cache.stats()["seen_events"] == 0
