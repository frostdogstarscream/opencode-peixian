"""Action-aware recovery decisions; protocol authorization remains in Control."""
import pytest
from test_orchestration_worker import worker


@pytest.mark.parametrize('action', ['pause', 'apply', 'provision', 'resume'])
@pytest.mark.parametrize('state', ['running', 'stopped', 'mixed', 'unknown'])
def test_recovery_target(action, state):
    job = dict(action=action, revision=7, spec_digest='frozen')
    observation = dict(complete=True, mutation_state='idle', accepting=False,
                       egress_closed=True, activity_count=0, applied_revision=7,
                       spec_digest='frozen', components=dict.fromkeys(['agent','gateway','relay'], state))
    if state == 'mixed':
        observation['components'] = dict(agent='running', gateway='stopped', relay='running')
    expected = 'needs_review' if state in ('mixed','unknown') else (
        'already_satisfied' if (state == 'stopped') == (action == 'pause') else 'needs_mutation')
    assert worker.recovery_decision(job, observation) == expected


@pytest.mark.parametrize('field,value', [('recovery_required', True), ('phase','reconciling'),
    ('recovery_of_attempt',1), ('mutation_authorized',True), ('recovery_attempt',True)])
def test_recovery_never_cancels_idle_candidate(field, value):
    job = dict(reason='idle_timeout', phase='closing', recovery_required=False)
    assert worker.can_cancel_idle(job)
    job[field] = value
    assert not worker.can_cancel_idle(job)


@pytest.mark.parametrize('state', ['running','stopped','mixed','unknown','apply_running','idle_stopped','idle_running','idle_changed','idle_closing_changed'])
def test_actual_lease_takeover(tmp_path, monkeypatch, state):
    from test_orchestration_worker import test_real_v4_store_and_worker_complete_one_registered_revision
    test_real_v4_store_and_worker_complete_one_registered_revision(tmp_path, monkeypatch, 'complete', recovery=state)


def test_unknown_defer_does_not_send_a_second_outcome(tmp_path, monkeypatch):
    from test_orchestration_worker import fixture
    runner, records, client = fixture(tmp_path, busy=True)
    original = runner.operation
    completions = []
    def operation(job, kind, values):
        if kind == 'complete':
            completions.append(values)
            raise worker.runtime.RuntimeFailure('worker_operation_outcome_unknown')
        return original(job, kind, values)
    monkeypatch.setattr(runner, 'operation', operation)
    with client, pytest.raises(worker.runtime.RuntimeFailure, match='worker_operation_outcome_unknown'):
        runner.once()
    assert len(completions) == 1 and completions[0]['deferred'] is True
    assert not any(kind == 'mutation' for kind, _ in records)
