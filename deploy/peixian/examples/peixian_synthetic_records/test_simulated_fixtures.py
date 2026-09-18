"""Regression checks for the richer, entirely synthetic records fixture.

This test deliberately avoids starting a listener: it validates the fixed
fixture contract that the isolated records service exposes.  The production
HTTP/authentication boundary remains covered by ``test_records_service.py``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


HERE = Path(__file__).resolve().parent
MODULE_PATH = HERE / "records_service_simulated.py"


def load_overlay():
    spec = importlib.util.spec_from_file_location("records_service_simulated", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load simulated fixture overlay")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_simulated_fixture_contract() -> None:
    service = load_overlay()
    expected_counts = {
        "funds": 8,
        "calls": 8,
        "portrait": 6,
        "composite": 6,
        "night": 8,
        "vehicle": 6,
        "lookup": 8,
    }

    assert set(service.FIXTURES) == set(service.MODULES) == set(expected_counts)
    all_record_ids: set[str] = set()

    for module, expected_count in expected_counts.items():
        records = service.FIXTURES[module]
        assert len(records) == expected_count
        for record in records:
            assert record["record_id"].startswith("DEMO-")
            assert record["group_ref"].startswith("DEMO-")
            assert record["member_ref"].startswith("DEMO-")
            assert record["source_type"] in service.MODULES
            assert record["record_id"] not in all_record_ids
            all_record_ids.add(record["record_id"])

        response = service.response_for(module)
        assert response["synthetic"] is True
        assert response["module"] == module
        assert response["snapshot_id"] == "DEMO-SNAPSHOT-20260918-01"
        assert response["rule_version"] == "demo-v1.1"
        assert response["rule_status"] == "demo_only"
        assert response["data_status"] == "complete"
        assert response["returned_count"] == expected_count
        assert response["total_count"] == expected_count
        assert response["has_more"] is False
        assert response["records"] == records
        assert response["missing_sources"] == []
        assert response["errors"] == []

    # Cross-module relation rows may only reference records in this same fixed
    # synthetic batch.  This prevents accidental introduction of real IDs.
    for module in ("composite", "lookup"):
        for record in service.FIXTURES[module]:
            for source_record_id in record["source_record_ids"]:
                assert source_record_id in all_record_ids

    print("simulated fixture contract: OK")


if __name__ == "__main__":
    test_simulated_fixture_contract()
