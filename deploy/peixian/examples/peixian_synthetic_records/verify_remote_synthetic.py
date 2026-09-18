#!/usr/bin/env python3
"""Black-box verifier for the deployed synthetic records service.

The caller supplies the service URL and the *path* to its server-side key file
through environment variables.  Neither value nor any fixture record is ever
printed.  Successful output is a compact, non-sensitive summary only.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


EXPECTED_COUNTS = {
    "funds": 8,
    "calls": 8,
    "portrait": 6,
    "composite": 6,
    "night": 8,
    "vehicle": 6,
    "lookup": 8,
}
EXPECTED_SNAPSHOT = "DEMO-SNAPSHOT-20260918-01"


def request(base_url: str, key: str, path: str, *, method: str = "GET", payload=None, authorized: bool = True):
    headers = {"Accept": "application/json"}
    if authorized:
        headers["Authorization"] = "Bearer " + key
    if payload is not None:
        headers["Content-Type"] = "application/json"
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(base_url + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, dict(response.headers.items()), json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers.items()), json.loads(exc.read())


def main() -> None:
    base_url = os.environ["PEIXIAN_VERIFY_URL"]
    with open(os.environ["PEIXIAN_VERIFY_KEY_FILE"], "r", encoding="utf-8") as handle:
        key = handle.read().strip()
    assert key

    status, headers, health = request(base_url, key, "/health")
    assert status == 200 and health == {"ok": True, "synthetic": True}
    assert headers.get("Content-Type", "").startswith("application/json")
    assert headers.get("Cache-Control") == "no-store"
    assert all(name.lower() != "authorization" for name in headers)

    status, _, body = request(base_url, key, "/health", authorized=False)
    assert status == 401 and body == {"error": "unauthorized"}

    all_ids: set[str] = set()
    relation_rows = []
    for module, count in EXPECTED_COUNTS.items():
        status, headers, body = request(base_url, key, "/v1/demo/records/query", method="POST", payload={"module": module})
        assert status == 200
        assert headers.get("Content-Type", "").startswith("application/json")
        assert headers.get("Cache-Control") == "no-store"
        assert all(name.lower() != "authorization" for name in headers)
        assert body["synthetic"] is True
        assert body["module"] == module
        assert body["snapshot_id"] == EXPECTED_SNAPSHOT
        assert body["data_status"] == "complete"
        assert body["rule_version"] == "demo-v1.1"
        assert body["rule_status"] == "demo_only"
        assert body["returned_count"] == body["total_count"] == len(body["records"]) == count
        assert body["has_more"] is False
        assert body["missing_sources"] == [] and body["errors"] == []
        for record in body["records"]:
            assert record["record_id"].startswith("DEMO-")
            assert record["group_ref"].startswith("DEMO-")
            assert record["member_ref"].startswith("DEMO-")
            assert record["record_id"] not in all_ids
            all_ids.add(record["record_id"])
            if module in ("composite", "lookup"):
                relation_rows.append(record)

    for record in relation_rows:
        for source_record_id in record["source_record_ids"]:
            assert source_record_id in all_ids

    for bad_payload in (
        {},
        {"module": "unknown"},
        {"module": "funds", "page": 1},
        {"module": "funds", "scenario": "x"},
        {"module": "funds", "member_ref": "DEMO-MEMBER-ORCHID"},
    ):
        status, _, body = request(base_url, key, "/v1/demo/records/query", method="POST", payload=bad_payload)
        assert status == 400 and body == {"error": "invalid_request"}

    status, _, body = request(base_url, key, "/v1/demo/records/query", method="GET")
    assert status == 404 and body == {"error": "not_found"}
    status, _, body = request(base_url, key, "/unapproved", method="GET")
    assert status == 404 and body == {"error": "not_found"}

    print(
        json.dumps(
            {
                "verification": "passed",
                "snapshot_id": EXPECTED_SNAPSHOT,
                "module_counts": EXPECTED_COUNTS,
                "records_total": sum(EXPECTED_COUNTS.values()),
            },
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
