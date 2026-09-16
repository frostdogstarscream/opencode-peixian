import asyncio
import json

from fastapi import HTTPException
import pytest

from gateway.admission import AdmissionGate, ActivityMiddleware


def command(gate, epoch, action="open", **changes):
    return {"protocol_version": 2, "runtime_id": gate.runtime_id, "boot_id": gate.boot_id,
            "gate_epoch": epoch, "state_version": epoch, "owner": "job:synthetic:1",
            "operation_id": "operation-" + str(epoch), "action": action, "reason": "normal", "revision": 1, **changes}


async def permit(gate, epoch=1, *, started=None, ttl=4, **changes):
    identity = {"protocol_version": 2, "runtime_id": gate.runtime_id, "gateway_boot_id": gate.boot_id}
    value = {**identity, "nonce": "synthetic", "gate_epoch": epoch, "state_version": epoch,
             "authorization_version": epoch, "owner": "job:synthetic:1", "revision": 1,
             "intake": True, "egress": True, "ttl_seconds": ttl, **changes}
    return await gate.permit(value, started=gate.clock() if started is None else started, nonce="synthetic", identity=identity)


def test_permit_never_opens_default_closed_and_late_response_cannot_extend_authority():
    async def scenario():
        clock = [10.0]
        gate = AdmissionGate("runtime", 1, clock=lambda: clock[0])
        await permit(gate, started=10)
        assert gate.mode == "closed"
        with pytest.raises(HTTPException):
            await gate.admit("upload")
        await gate.command(command(gate, 1))
        clock[0] = 15
        assert not await permit(gate, started=10)
        with pytest.raises(HTTPException):
            await gate.admit("upload")
    asyncio.run(scenario())


def test_close_and_admission_share_one_boundary_and_receipts_do_not_reopen():
    async def scenario():
        gate = AdmissionGate("runtime", 1)
        await permit(gate, 1)
        await gate.command(command(gate, 1))
        first = await gate.admit("upload")
        old = command(gate, 2, "drain")
        recorded = await gate.command(old)
        with pytest.raises(HTTPException):
            await gate.admit("download")
        assert gate.snapshot()["activity"]["total"] == 1
        await gate.command(command(gate, 3, "close"))
        assert await gate.command(old) == recorded
        assert gate.mode == "closed"
        gate.finish(first)
        assert gate.snapshot()["activity"]["idle"]
    asyncio.run(scenario())


def test_new_authority_epoch_requires_an_explicit_new_intake_open():
    async def scenario():
        gate = AdmissionGate("runtime", 1)
        await permit(gate, 1)
        await gate.command(command(gate, 1))
        await permit(gate, 2)
        with pytest.raises(HTTPException):
            await gate.admit("upload")
        await gate.command(command(gate, 2))
        gate.finish(await gate.admit("upload"))
    asyncio.run(scenario())


def test_stale_boot_epoch_owner_and_conflicting_operation_rejected():
    async def scenario():
        gate = AdmissionGate("runtime", 1)
        await permit(gate, 3)
        with pytest.raises(HTTPException):
            await gate.command(command(gate, 1, boot_id="old"))
        with pytest.raises(HTTPException):
            await gate.command(command(gate, 1, owner="another-owner"))
        await gate.command(command(gate, 2, "close"))
        for data in (command(gate, 1), command(gate, 2, "open")):
            with pytest.raises(HTTPException):
                await gate.command(data)
    asyncio.run(scenario())


def test_normal_draining_allows_continuation_but_security_permit_does_not():
    async def scenario():
        gate = AdmissionGate("runtime", 1)
        await permit(gate, 2)
        await gate.command(command(gate, 1, "drain"))
        activity = await gate.admit("receiving", continuation=True)
        gate.finish(activity)
        await permit(gate, 2, intake=False, egress=False)
        with pytest.raises(HTTPException):
            await gate.admit("receiving", continuation=True)
    asyncio.run(scenario())


def test_expired_open_is_latched_even_if_renewal_beats_the_watchdog():
    async def scenario():
        clock = [10.0]
        gate = AdmissionGate("runtime", 1, clock=lambda: clock[0])
        await permit(gate)
        old_open = command(gate, 1)
        await gate.command(old_open)
        clock[0] = 15
        await permit(gate)
        assert gate.valid("egress")
        assert gate.mode == "closed" and gate.needs_reconcile
        assert gate.needs_reconcile_epoch == 1
        await gate.command(old_open)
        assert gate.mode == "closed" and gate.needs_reconcile
        with pytest.raises(HTTPException):
            await gate.admit("upload")
        await permit(gate, 2)
        await gate.command(command(gate, 2))
        assert gate.mode == "open" and not gate.needs_reconcile
    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["draining", "closed"])
def test_expiration_does_not_replace_existing_lifecycle_responsibility(mode):
    async def scenario():
        clock = [10.0]
        gate = AdmissionGate("runtime", 1, clock=lambda: clock[0])
        await permit(gate)
        await gate.command(command(gate, 1, "drain" if mode == "draining" else "close"))
        clock[0] = 15
        assert not await gate.expire()
        assert gate.mode == mode and not gate.needs_reconcile
    asyncio.run(scenario())


def test_denied_scope_does_not_create_a_second_ttl_recovery_intent():
    async def scenario():
        clock = [10.0]
        gate = AdmissionGate("runtime", 1, clock=lambda: clock[0])
        await permit(gate)
        await gate.command(command(gate, 1))
        await permit(gate, intake=False, egress=False)
        clock[0] = 15
        assert not await gate.expire()
        assert not gate.needs_reconcile
    asyncio.run(scenario())


def test_restarted_pending_journal_is_unknown_until_correlated_native_receipt(tmp_path):
    journal = tmp_path / "activity" / "pending.json"
    gate = AdmissionGate("runtime", 1, journal=journal)
    identity = gate.register("pending_start", resource="session_synthetic")
    assert "pending_start" not in journal.read_text()
    recovered = AdmissionGate("runtime", 1, journal=journal)
    assert recovered.boot_id != gate.boot_id
    assert recovered.snapshot()["activity"]["unknown"]
    recovered.finish(identity)
    assert recovered.snapshot()["activity"]["idle"]
    assert json.loads(journal.read_text()) == {}


def test_stale_partial_observations_never_become_idle():
    clock = [0]
    gate = AdmissionGate("runtime", 1, clock=lambda: clock[0])
    gate.source("native", {}, complete=False)
    assert not gate.snapshot()["activity"]["idle"]
    gate.source("native", {})
    assert gate.snapshot()["activity"]["idle"]
    clock[0] = 4
    assert gate.snapshot()["activity"]["unknown"]


def test_cancelled_before_response_start_releases_reservation():
    async def scenario():
        from types import SimpleNamespace
        gate = AdmissionGate("runtime", 1)
        await permit(gate)
        await gate.command(command(gate, 1))
        entered = asyncio.Event()
        async def downstream(scope, receive, send):
            entered.set()
            await asyncio.Future()
        middleware = ActivityMiddleware(downstream, SimpleNamespace(state=SimpleNamespace(admission=gate)))
        task = asyncio.create_task(middleware({"type": "http", "path": "/files", "method": "POST"}, None, None))
        await entered.wait()
        assert gate.snapshot()["activity"]["counts"] == {"upload": 1}
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert gate.snapshot()["activity"]["idle"]
    asyncio.run(scenario())


@pytest.mark.parametrize("change", [{"nonce": "old"}, {"ttl_seconds": 5}, {"revision": 2}, {"egress": "true"}, {"authorization_version": True}])
def test_malformed_permit_rejected_without_extending_deadline(change):
    async def scenario():
        gate = AdmissionGate("runtime", 1)
        with pytest.raises(ValueError):
            await permit(gate, **change)
        assert gate.deadline == 0
    asyncio.run(scenario())
