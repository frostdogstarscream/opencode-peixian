#!/usr/bin/env python3
"""Richer but wholly fictitious fixtures for the isolated records service.

The HTTP listener, Bearer validation and exact request validation stay in
``records_service.py``.  This overlay changes only the embedded synthetic
records and snapshot metadata.  Every identifier is deliberately DEMO-prefixed
and no item represents a real person, account, phone, vehicle, location or case.
"""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path


_source = Path(__file__).with_name("records_service.py")
_spec = importlib.util.spec_from_file_location("peixian_records_base", _source)
base = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(base)

MODULES = base.MODULES
MAX_BODY_BYTES = base.MAX_BODY_BYTES
Handler = base.Handler
ThreadingHTTPServer = base.ThreadingHTTPServer

FIXTURES = {
    "funds": [
        {"record_id": "DEMO-FND-001", "source_type": "funds", "group_ref": "DEMO-ACCOUNT-HARBOR-A", "member_ref": "DEMO-MEMBER-ORCHID", "transaction_ref": "DEMO-TXN-1001", "occurred_at": "2026-09-14T20:14:00+08:00", "direction": "credit", "amount_minor": 12800, "channel": "synthetic_qr", "counterparty_ref": "DEMO-ACCOUNT-EMBER-B"},
        {"record_id": "DEMO-FND-002", "source_type": "funds", "group_ref": "DEMO-ACCOUNT-HARBOR-A", "member_ref": "DEMO-MEMBER-ORCHID", "transaction_ref": "DEMO-TXN-1002", "occurred_at": "2026-09-14T20:17:00+08:00", "direction": "debit", "amount_minor": 12600, "channel": "synthetic_transfer", "counterparty_ref": "DEMO-ACCOUNT-CEDAR-C"},
        {"record_id": "DEMO-FND-003", "source_type": "funds", "group_ref": "DEMO-ACCOUNT-EMBER-B", "member_ref": "DEMO-MEMBER-QUARTZ", "transaction_ref": "DEMO-TXN-1003", "occurred_at": "2026-09-14T20:18:00+08:00", "direction": "credit", "amount_minor": 7800, "channel": "synthetic_qr", "counterparty_ref": "DEMO-ACCOUNT-HARBOR-A"},
        {"record_id": "DEMO-FND-004", "source_type": "funds", "group_ref": "DEMO-ACCOUNT-EMBER-B", "member_ref": "DEMO-MEMBER-QUARTZ", "transaction_ref": "DEMO-TXN-1004", "occurred_at": "2026-09-14T20:24:00+08:00", "direction": "debit", "amount_minor": 7600, "channel": "synthetic_transfer", "counterparty_ref": "DEMO-ACCOUNT-CEDAR-C"},
        {"record_id": "DEMO-FND-005", "source_type": "funds", "group_ref": "DEMO-ACCOUNT-CEDAR-C", "member_ref": "DEMO-MEMBER-SAFFRON", "transaction_ref": "DEMO-TXN-1005", "occurred_at": "2026-09-14T20:26:00+08:00", "direction": "credit", "amount_minor": 12600, "channel": "synthetic_transfer", "counterparty_ref": "DEMO-ACCOUNT-HARBOR-A"},
        {"record_id": "DEMO-FND-006", "source_type": "funds", "group_ref": "DEMO-ACCOUNT-CEDAR-C", "member_ref": "DEMO-MEMBER-SAFFRON", "transaction_ref": "DEMO-TXN-1006", "occurred_at": "2026-09-14T20:31:00+08:00", "direction": "credit", "amount_minor": 7600, "channel": "synthetic_transfer", "counterparty_ref": "DEMO-ACCOUNT-EMBER-B"},
        {"record_id": "DEMO-FND-007", "source_type": "funds", "group_ref": "DEMO-ACCOUNT-HARBOR-A", "member_ref": "DEMO-MEMBER-ORCHID", "transaction_ref": "DEMO-TXN-1007", "occurred_at": "2026-09-15T00:42:00+08:00", "direction": "debit", "amount_minor": 3200, "channel": "synthetic_qr", "counterparty_ref": "DEMO-ACCOUNT-GLASS-D"},
        {"record_id": "DEMO-FND-008", "source_type": "funds", "group_ref": "DEMO-ACCOUNT-GLASS-D", "member_ref": "DEMO-MEMBER-INDIGO", "transaction_ref": "DEMO-TXN-1008", "occurred_at": "2026-09-15T00:44:00+08:00", "direction": "credit", "amount_minor": 3200, "channel": "synthetic_qr", "counterparty_ref": "DEMO-ACCOUNT-HARBOR-A"},
    ],
    "calls": [
        {"record_id": "DEMO-CAL-001", "source_type": "calls", "group_ref": "DEMO-CONTACT-ORCHID", "member_ref": "DEMO-MEMBER-ORCHID", "call_ref": "DEMO-CALL-2001", "occurred_at": "2026-09-14T20:05:00+08:00", "direction": "outbound", "peer_ref": "DEMO-CONTACT-QUARTZ", "duration_seconds": 94, "cell_ref": "DEMO-CELL-ALPHA"},
        {"record_id": "DEMO-CAL-002", "source_type": "calls", "group_ref": "DEMO-CONTACT-QUARTZ", "member_ref": "DEMO-MEMBER-QUARTZ", "call_ref": "DEMO-CALL-2002", "occurred_at": "2026-09-14T20:05:00+08:00", "direction": "inbound", "peer_ref": "DEMO-CONTACT-ORCHID", "duration_seconds": 94, "cell_ref": "DEMO-CELL-BRAVO"},
        {"record_id": "DEMO-CAL-003", "source_type": "calls", "group_ref": "DEMO-CONTACT-QUARTZ", "member_ref": "DEMO-MEMBER-QUARTZ", "call_ref": "DEMO-CALL-2003", "occurred_at": "2026-09-14T20:12:00+08:00", "direction": "outbound", "peer_ref": "DEMO-CONTACT-SAFFRON", "duration_seconds": 61, "cell_ref": "DEMO-CELL-BRAVO"},
        {"record_id": "DEMO-CAL-004", "source_type": "calls", "group_ref": "DEMO-CONTACT-SAFFRON", "member_ref": "DEMO-MEMBER-SAFFRON", "call_ref": "DEMO-CALL-2004", "occurred_at": "2026-09-14T20:12:00+08:00", "direction": "inbound", "peer_ref": "DEMO-CONTACT-QUARTZ", "duration_seconds": 61, "cell_ref": "DEMO-CELL-CHARLIE"},
        {"record_id": "DEMO-CAL-005", "source_type": "calls", "group_ref": "DEMO-CONTACT-ORCHID", "member_ref": "DEMO-MEMBER-ORCHID", "call_ref": "DEMO-CALL-2005", "occurred_at": "2026-09-14T23:48:00+08:00", "direction": "outbound", "peer_ref": "DEMO-CONTACT-INDIGO", "duration_seconds": 46, "cell_ref": "DEMO-CELL-DELTA"},
        {"record_id": "DEMO-CAL-006", "source_type": "calls", "group_ref": "DEMO-CONTACT-INDIGO", "member_ref": "DEMO-MEMBER-INDIGO", "call_ref": "DEMO-CALL-2006", "occurred_at": "2026-09-14T23:48:00+08:00", "direction": "inbound", "peer_ref": "DEMO-CONTACT-ORCHID", "duration_seconds": 46, "cell_ref": "DEMO-CELL-ECHO"},
        {"record_id": "DEMO-CAL-007", "source_type": "calls", "group_ref": "DEMO-CONTACT-SAFFRON", "member_ref": "DEMO-MEMBER-SAFFRON", "call_ref": "DEMO-CALL-2007", "occurred_at": "2026-09-15T00:30:00+08:00", "direction": "outbound", "peer_ref": "DEMO-CONTACT-ORCHID", "duration_seconds": 73, "cell_ref": "DEMO-CELL-CHARLIE"},
        {"record_id": "DEMO-CAL-008", "source_type": "calls", "group_ref": "DEMO-CONTACT-ORCHID", "member_ref": "DEMO-MEMBER-ORCHID", "call_ref": "DEMO-CALL-2008", "occurred_at": "2026-09-15T00:30:00+08:00", "direction": "inbound", "peer_ref": "DEMO-CONTACT-SAFFRON", "duration_seconds": 73, "cell_ref": "DEMO-CELL-DELTA"},
    ],
    "portrait": [
        {"record_id": "DEMO-POR-001", "source_type": "portrait", "group_ref": "DEMO-CAPTURE-ALPHA", "member_ref": "DEMO-MEMBER-ORCHID", "event_ref": "DEMO-VIS-3001", "occurred_at": "2026-09-14T20:01:00+08:00", "kind": "same_frame", "co_member_ref": "DEMO-MEMBER-QUARTZ", "device_ref": "DEMO-CAMERA-ALPHA", "match_basis": "synthetic_co_presence"},
        {"record_id": "DEMO-POR-002", "source_type": "portrait", "group_ref": "DEMO-CAPTURE-ALPHA", "member_ref": "DEMO-MEMBER-QUARTZ", "event_ref": "DEMO-VIS-3002", "occurred_at": "2026-09-14T20:01:00+08:00", "kind": "same_frame", "co_member_ref": "DEMO-MEMBER-ORCHID", "device_ref": "DEMO-CAMERA-ALPHA", "match_basis": "synthetic_co_presence"},
        {"record_id": "DEMO-POR-003", "source_type": "portrait", "group_ref": "DEMO-CAPTURE-BRAVO", "member_ref": "DEMO-MEMBER-QUARTZ", "event_ref": "DEMO-VIS-3003", "occurred_at": "2026-09-14T20:10:00+08:00", "kind": "same_frame", "co_member_ref": "DEMO-MEMBER-SAFFRON", "device_ref": "DEMO-CAMERA-BRAVO", "match_basis": "synthetic_co_presence"},
        {"record_id": "DEMO-POR-004", "source_type": "portrait", "group_ref": "DEMO-CAPTURE-BRAVO", "member_ref": "DEMO-MEMBER-SAFFRON", "event_ref": "DEMO-VIS-3004", "occurred_at": "2026-09-14T20:10:00+08:00", "kind": "same_frame", "co_member_ref": "DEMO-MEMBER-QUARTZ", "device_ref": "DEMO-CAMERA-BRAVO", "match_basis": "synthetic_co_presence"},
        {"record_id": "DEMO-POR-005", "source_type": "portrait", "group_ref": "DEMO-CAPTURE-CHARLIE", "member_ref": "DEMO-MEMBER-ORCHID", "event_ref": "DEMO-VIS-3005", "occurred_at": "2026-09-14T23:55:00+08:00", "kind": "same_trip", "co_member_ref": "DEMO-MEMBER-INDIGO", "device_ref": "DEMO-CAMERA-CHARLIE", "match_basis": "synthetic_co_presence"},
        {"record_id": "DEMO-POR-006", "source_type": "portrait", "group_ref": "DEMO-CAPTURE-CHARLIE", "member_ref": "DEMO-MEMBER-INDIGO", "event_ref": "DEMO-VIS-3006", "occurred_at": "2026-09-14T23:55:00+08:00", "kind": "same_trip", "co_member_ref": "DEMO-MEMBER-ORCHID", "device_ref": "DEMO-CAMERA-CHARLIE", "match_basis": "synthetic_co_presence"},
    ],
    "composite": [
        {"record_id": "DEMO-CMP-001", "source_type": "funds", "group_ref": "DEMO-MEMBER-ORCHID", "member_ref": "DEMO-MEMBER-QUARTZ", "relation_ref": "DEMO-REL-4001", "relation_kind": "shared_transaction_window", "source_record_ids": ["DEMO-FND-001", "DEMO-FND-003"], "observed_at": "2026-09-14T20:18:00+08:00"},
        {"record_id": "DEMO-CMP-002", "source_type": "calls", "group_ref": "DEMO-MEMBER-ORCHID", "member_ref": "DEMO-MEMBER-QUARTZ", "relation_ref": "DEMO-REL-4002", "relation_kind": "paired_call_event", "source_record_ids": ["DEMO-CAL-001", "DEMO-CAL-002"], "observed_at": "2026-09-14T20:05:00+08:00"},
        {"record_id": "DEMO-CMP-003", "source_type": "portrait", "group_ref": "DEMO-MEMBER-ORCHID", "member_ref": "DEMO-MEMBER-QUARTZ", "relation_ref": "DEMO-REL-4003", "relation_kind": "same_frame_event", "source_record_ids": ["DEMO-POR-001", "DEMO-POR-002"], "observed_at": "2026-09-14T20:01:00+08:00"},
        {"record_id": "DEMO-CMP-004", "source_type": "funds", "group_ref": "DEMO-MEMBER-QUARTZ", "member_ref": "DEMO-MEMBER-SAFFRON", "relation_ref": "DEMO-REL-4004", "relation_kind": "shared_transaction_window", "source_record_ids": ["DEMO-FND-004", "DEMO-FND-006"], "observed_at": "2026-09-14T20:31:00+08:00"},
        {"record_id": "DEMO-CMP-005", "source_type": "calls", "group_ref": "DEMO-MEMBER-QUARTZ", "member_ref": "DEMO-MEMBER-SAFFRON", "relation_ref": "DEMO-REL-4005", "relation_kind": "paired_call_event", "source_record_ids": ["DEMO-CAL-003", "DEMO-CAL-004"], "observed_at": "2026-09-14T20:12:00+08:00"},
        {"record_id": "DEMO-CMP-006", "source_type": "portrait", "group_ref": "DEMO-MEMBER-ORCHID", "member_ref": "DEMO-MEMBER-INDIGO", "relation_ref": "DEMO-REL-4006", "relation_kind": "same_trip_event", "source_record_ids": ["DEMO-POR-005", "DEMO-POR-006"], "observed_at": "2026-09-14T23:55:00+08:00"},
    ],
    "night": [
        {"record_id": "DEMO-NGT-001", "source_type": "night", "group_ref": "DEMO-MEMBER-ORCHID", "member_ref": "DEMO-NIGHT-EVENT-5001", "kind": "person", "occurred_at": "2026-09-14T22:16:00+08:00", "event_ref": "DEMO-VIS-3010", "device_ref": "DEMO-CAMERA-DELTA", "time_window": "22:00-06:00"},
        {"record_id": "DEMO-NGT-002", "source_type": "night", "group_ref": "DEMO-MEMBER-QUARTZ", "member_ref": "DEMO-NIGHT-EVENT-5002", "kind": "person", "occurred_at": "2026-09-14T22:18:00+08:00", "event_ref": "DEMO-VIS-3011", "device_ref": "DEMO-CAMERA-DELTA", "time_window": "22:00-06:00"},
        {"record_id": "DEMO-NGT-003", "source_type": "night", "group_ref": "DEMO-VEHICLE-EMBER-A", "member_ref": "DEMO-NIGHT-EVENT-5003", "kind": "vehicle", "occurred_at": "2026-09-14T23:51:00+08:00", "event_ref": "DEMO-PASS-6003", "device_ref": "DEMO-GATE-ALPHA", "time_window": "22:00-06:00"},
        {"record_id": "DEMO-NGT-004", "source_type": "night", "group_ref": "DEMO-MEMBER-INDIGO", "member_ref": "DEMO-NIGHT-EVENT-5004", "kind": "person", "occurred_at": "2026-09-14T23:55:00+08:00", "event_ref": "DEMO-VIS-3006", "device_ref": "DEMO-CAMERA-CHARLIE", "time_window": "22:00-06:00"},
        {"record_id": "DEMO-NGT-005", "source_type": "night", "group_ref": "DEMO-MEMBER-SAFFRON", "member_ref": "DEMO-NIGHT-EVENT-5005", "kind": "person", "occurred_at": "2026-09-15T00:29:00+08:00", "event_ref": "DEMO-VIS-3012", "device_ref": "DEMO-CAMERA-ECHO", "time_window": "22:00-06:00"},
        {"record_id": "DEMO-NGT-006", "source_type": "night", "group_ref": "DEMO-VEHICLE-EMBER-A", "member_ref": "DEMO-NIGHT-EVENT-5006", "kind": "vehicle", "occurred_at": "2026-09-15T00:47:00+08:00", "event_ref": "DEMO-PASS-6004", "device_ref": "DEMO-GATE-BRAVO", "time_window": "22:00-06:00"},
        {"record_id": "DEMO-NGT-007", "source_type": "night", "group_ref": "DEMO-MEMBER-ORCHID", "member_ref": "DEMO-NIGHT-EVENT-5007", "kind": "person", "occurred_at": "2026-09-15T01:12:00+08:00", "event_ref": "DEMO-VIS-3013", "device_ref": "DEMO-CAMERA-ECHO", "time_window": "22:00-06:00"},
        {"record_id": "DEMO-NGT-008", "source_type": "night", "group_ref": "DEMO-VEHICLE-GLASS-B", "member_ref": "DEMO-NIGHT-EVENT-5008", "kind": "vehicle", "occurred_at": "2026-09-15T02:08:00+08:00", "event_ref": "DEMO-PASS-6005", "device_ref": "DEMO-GATE-CHARLIE", "time_window": "22:00-06:00"},
    ],
    "vehicle": [
        {"record_id": "DEMO-VEH-001", "source_type": "vehicle", "group_ref": "DEMO-VEHICLE-EMBER-A", "member_ref": "DEMO-MEMBER-ORCHID", "passage_ref": "DEMO-PASS-6001", "occurred_at": "2026-09-14T19:54:00+08:00", "direction": "inbound", "device_ref": "DEMO-GATE-ALPHA", "lane_ref": "DEMO-LANE-1", "vehicle_class": "synthetic_sedan"},
        {"record_id": "DEMO-VEH-002", "source_type": "vehicle", "group_ref": "DEMO-VEHICLE-EMBER-A", "member_ref": "DEMO-MEMBER-QUARTZ", "passage_ref": "DEMO-PASS-6002", "occurred_at": "2026-09-14T20:07:00+08:00", "direction": "inbound", "device_ref": "DEMO-GATE-BRAVO", "lane_ref": "DEMO-LANE-2", "vehicle_class": "synthetic_sedan"},
        {"record_id": "DEMO-VEH-003", "source_type": "vehicle", "group_ref": "DEMO-VEHICLE-EMBER-A", "member_ref": "DEMO-MEMBER-SAFFRON", "passage_ref": "DEMO-PASS-6003", "occurred_at": "2026-09-14T23:51:00+08:00", "direction": "outbound", "device_ref": "DEMO-GATE-ALPHA", "lane_ref": "DEMO-LANE-1", "vehicle_class": "synthetic_sedan"},
        {"record_id": "DEMO-VEH-004", "source_type": "vehicle", "group_ref": "DEMO-VEHICLE-EMBER-A", "member_ref": "DEMO-MEMBER-ORCHID", "passage_ref": "DEMO-PASS-6004", "occurred_at": "2026-09-15T00:47:00+08:00", "direction": "outbound", "device_ref": "DEMO-GATE-BRAVO", "lane_ref": "DEMO-LANE-2", "vehicle_class": "synthetic_sedan"},
        {"record_id": "DEMO-VEH-005", "source_type": "vehicle", "group_ref": "DEMO-VEHICLE-GLASS-B", "member_ref": "DEMO-MEMBER-INDIGO", "passage_ref": "DEMO-PASS-6005", "occurred_at": "2026-09-15T02:08:00+08:00", "direction": "inbound", "device_ref": "DEMO-GATE-CHARLIE", "lane_ref": "DEMO-LANE-1", "vehicle_class": "synthetic_van"},
        {"record_id": "DEMO-VEH-006", "source_type": "vehicle", "group_ref": "DEMO-VEHICLE-GLASS-B", "member_ref": "DEMO-MEMBER-INDIGO", "passage_ref": "DEMO-PASS-6006", "occurred_at": "2026-09-15T03:40:00+08:00", "direction": "outbound", "device_ref": "DEMO-GATE-DELTA", "lane_ref": "DEMO-LANE-1", "vehicle_class": "synthetic_van"},
    ],
    "lookup": [
        {"record_id": "DEMO-LKP-001", "source_type": "lookup", "group_ref": "DEMO-MEMBER-ORCHID", "member_ref": "DEMO-ACCOUNT-HARBOR-A", "relation_ref": "DEMO-LOOKUP-7001", "kind": "member_to_account", "source_record_ids": ["DEMO-FND-001", "DEMO-FND-002"]},
        {"record_id": "DEMO-LKP-002", "source_type": "lookup", "group_ref": "DEMO-MEMBER-QUARTZ", "member_ref": "DEMO-ACCOUNT-EMBER-B", "relation_ref": "DEMO-LOOKUP-7002", "kind": "member_to_account", "source_record_ids": ["DEMO-FND-003", "DEMO-FND-004"]},
        {"record_id": "DEMO-LKP-003", "source_type": "lookup", "group_ref": "DEMO-MEMBER-SAFFRON", "member_ref": "DEMO-ACCOUNT-CEDAR-C", "relation_ref": "DEMO-LOOKUP-7003", "kind": "member_to_account", "source_record_ids": ["DEMO-FND-005", "DEMO-FND-006"]},
        {"record_id": "DEMO-LKP-004", "source_type": "lookup", "group_ref": "DEMO-MEMBER-ORCHID", "member_ref": "DEMO-CONTACT-QUARTZ", "relation_ref": "DEMO-LOOKUP-7004", "kind": "member_to_contact", "source_record_ids": ["DEMO-CAL-001"]},
        {"record_id": "DEMO-LKP-005", "source_type": "lookup", "group_ref": "DEMO-MEMBER-QUARTZ", "member_ref": "DEMO-CONTACT-SAFFRON", "relation_ref": "DEMO-LOOKUP-7005", "kind": "member_to_contact", "source_record_ids": ["DEMO-CAL-003"]},
        {"record_id": "DEMO-LKP-006", "source_type": "lookup", "group_ref": "DEMO-MEMBER-ORCHID", "member_ref": "DEMO-VEHICLE-EMBER-A", "relation_ref": "DEMO-LOOKUP-7006", "kind": "member_to_vehicle", "source_record_ids": ["DEMO-VEH-001", "DEMO-VEH-004"]},
        {"record_id": "DEMO-LKP-007", "source_type": "lookup", "group_ref": "DEMO-MEMBER-INDIGO", "member_ref": "DEMO-VEHICLE-GLASS-B", "relation_ref": "DEMO-LOOKUP-7007", "kind": "member_to_vehicle", "source_record_ids": ["DEMO-VEH-005", "DEMO-VEH-006"]},
        {"record_id": "DEMO-LKP-008", "source_type": "lookup", "group_ref": "DEMO-MEMBER-ORCHID", "member_ref": "DEMO-MEMBER-QUARTZ", "relation_ref": "DEMO-LOOKUP-7008", "kind": "shared_capture_event", "source_record_ids": ["DEMO-POR-001", "DEMO-POR-002"]},
    ],
}


def response_for(module):
    records = copy.deepcopy(FIXTURES[module])
    return {
        "schema_version": "1.0",
        "synthetic": True,
        "module": module,
        "snapshot_id": "DEMO-SNAPSHOT-20260918-01",
        "scope": {"material_batch": "DEMO-BATCH-20260918-01", "timezone": "Asia/Shanghai", "query_scope": "embedded_fixture_only"},
        "data_status": "complete",
        "records": records,
        "returned_count": len(records),
        "total_count": len(records),
        "has_more": False,
        "missing_sources": [],
        "errors": [],
        "rule_version": "demo-v1.1",
        "rule_status": "demo_only",
    }


base.SOURCE = "沛县七项合成资料服务（合成演示）"
base.FIXTURES = FIXTURES
base.response_for = response_for


if __name__ == "__main__":
    base.main()
