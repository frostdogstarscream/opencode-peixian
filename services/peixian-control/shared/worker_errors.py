"""Additive protocol-v2 diagnostics; never trust arbitrary remote error text."""
HEADER = "X-Peixian-Worker-Code"
CODES = frozenset({
    "worker_rejected", "worker_invalid_request", "worker_not_found", "worker_protocol_mismatch", "worker_capability_mismatch",
    "worker_lease_expired", "worker_attempt_inactive", "worker_phase_conflict",
    "worker_receipt_conflict", "worker_state_changed", "worker_gate_changed",
    "worker_observation_missing", "worker_observation_incomplete", "worker_observation_expired",
    "worker_observation_responsibility", "worker_observation_superseded", "worker_observation_conflict",
    "worker_boot_unregistered", "worker_gate_unverified", "worker_applied_unverified",
    "worker_maintenance_blocked", "worker_security_blocked",
    "worker_overloaded", "worker_api_unavailable", "worker_transport_failure",
    "worker_invalid_response", "worker_receipt_invalid", "worker_query_failed",
})
