"""N3 operation outcomes use synthetic HTTP and private temporary journals."""
import json
from types import SimpleNamespace

import httpx
import pytest

from test_orchestration_worker import worker


def job():
    return {"id": "a" * 32, "attempt": 1, "lease": "synthetic-private-lease",
            "action": "apply", "phase": "applying", "state_version": 3, "gate_epoch": 2}


@pytest.mark.parametrize("code", ["worker_phase_conflict", "worker_lease_expired", "worker_observation_expired",
                                  "worker_observation_superseded", "worker_state_changed", "worker_receipt_conflict"])
def test_definite_rejection_is_not_reported_as_unknown_or_retried(tmp_path, capsys, code):
    calls = []
    def dispatch(request):
        calls.append(request)
        if request.method == "POST":
            return httpx.Response(409, headers={"X-Peixian-Worker-Code": code}, json={"message": "private-secret"})
        return httpx.Response(200, json={"receipt": None})
    with httpx.Client(transport=httpx.MockTransport(dispatch), base_url="http://synthetic") as client:
        runner = worker.Worker(client, SimpleNamespace(root=tmp_path))
        with pytest.raises(worker.runtime.RuntimeFailure) as error:
            runner.operation(job(), "complete", {"ok": True, "observation_id": "observation"})
    assert error.value.code == code
    assert [r.method for r in calls] == ["POST", "GET"]
    journal = json.loads(next((tmp_path / "receipts").rglob("*.json")).read_text())
    assert journal["status"] == "rejected"
    logs = capsys.readouterr().out
    assert code in logs and "operation_id" in logs and "attempt" in logs
    assert "private-secret" not in logs and "synthetic-private-lease" not in logs


def test_query_failure_keeps_unknown_journal_and_original_failure(tmp_path):
    def dispatch(request):
        if request.method == "POST":
            raise httpx.ReadError("private payload", request=request)
        return httpx.Response(503)
    with httpx.Client(transport=httpx.MockTransport(dispatch), base_url="http://synthetic") as client:
        with pytest.raises(worker.runtime.RuntimeFailure) as error:
            worker.Worker(client, SimpleNamespace(root=tmp_path)).operation(job(), "complete", {"ok": True})
    assert error.value.code == "worker_operation_outcome_unknown"
    value = json.loads(next((tmp_path / "receipts").rglob("*.json")).read_text())
    assert value["status"] == "unknown"
    assert value["failure_code"] == "worker_transport_failure"
    assert value["query_code"] == "worker_overloaded"


def test_invalid_receipt_is_not_persisted_as_recorded(tmp_path):
    def dispatch(request):
        body = json.loads(request.content)
        return httpx.Response(200, json={"receipt_status": "recorded", "job_id": job()["id"],
            "attempt": 1, "operation_id": body["operation_id"], "phase_after_commit": "finished",
            "state_version": "invalid", "gate_epoch": 3})
    with httpx.Client(transport=httpx.MockTransport(dispatch), base_url="http://synthetic") as client:
        with pytest.raises(worker.runtime.RuntimeFailure):
            worker.Worker(client, SimpleNamespace(root=tmp_path)).operation(job(), "complete", {"ok": True})
    value = json.loads(next((tmp_path / "receipts").rglob("*.json")).read_text())
    assert value["status"] != "recorded"



@pytest.mark.parametrize("final_status", [503, 409])
def test_uncertain_first_request_never_becomes_false_definite_rejection(tmp_path, final_status):
    posts = []
    def dispatch(request):
        if request.method == "GET":
            return httpx.Response(200, json={"receipt": None})
        posts.append(json.loads(request.content))
        if len(posts) == 1:
            raise httpx.ReadError("lost", request=request)
        return httpx.Response(final_status, headers={"X-Peixian-Worker-Code": "worker_lease_expired"})
    with httpx.Client(transport=httpx.MockTransport(dispatch), base_url="http://synthetic") as client:
        with pytest.raises(worker.runtime.RuntimeFailure) as error:
            worker.Worker(client, SimpleNamespace(root=tmp_path)).operation(job(), "complete", {"ok": True})
    assert error.value.code == "worker_operation_outcome_unknown"
    assert len(posts) == 2 and posts[0] == posts[1]
    value = json.loads(next((tmp_path / "receipts").rglob("*.json")).read_text())
    assert value["status"] == "unknown"


def test_arbitrary_remote_error_is_not_logged(tmp_path, capsys):
    def dispatch(request):
        if request.method == "GET":
            return httpx.Response(200, json={"receipt": None})
        return httpx.Response(409, headers={"X-Peixian-Worker-Code": "raw-secret-example"}, json={"message": "raw-secret-example"})
    with httpx.Client(transport=httpx.MockTransport(dispatch), base_url="http://synthetic") as client:
        with pytest.raises(worker.runtime.RuntimeFailure) as error:
            worker.Worker(client, SimpleNamespace(root=tmp_path)).operation(job(), "phase", {"phase": "applying"})
    assert error.value.code == "worker_rejected"
    assert "raw-secret-example" not in capsys.readouterr().out


@pytest.mark.parametrize("conflict", [True, False])
def test_conflicting_receipt_never_updates_local_state(tmp_path, conflict):
    current = job()
    def dispatch(request):
        if request.method == "POST":
            body = json.loads(request.content)
            dispatch.receipt = {"receipt_status": "recorded", "job_id": current["id"],
                "attempt": 1, "operation_id": body["operation_id"], "phase_after_commit": "finished",
                "state_version": 100, "gate_epoch": 100, "request_hash": "0" * 64}
            if conflict:
                return httpx.Response(409, headers={"X-Peixian-Worker-Code": "worker_receipt_conflict"})
            return httpx.Response(200, json=dispatch.receipt)
        return httpx.Response(200, json={"receipt": dispatch.receipt})
    with httpx.Client(transport=httpx.MockTransport(dispatch), base_url="http://synthetic") as client:
        with pytest.raises(worker.runtime.RuntimeFailure):
            worker.Worker(client, SimpleNamespace(root=tmp_path)).operation(current, "complete", {"ok": True})
    assert current["state_version"] == 3 and current["gate_epoch"] == 2
    value = json.loads(next((tmp_path / "receipts").rglob("*.json")).read_text())
    assert value["status"] == ("rejected" if conflict else "unknown")
