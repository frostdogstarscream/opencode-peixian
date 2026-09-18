"""Versioned independent fixtures for acceptance; never learn expectations from HTTP."""
import hashlib
import importlib.util
from pathlib import Path

PROFILES = {
    "legacy": ("records_service.py", "DEMO-SNAPSHOT-001", "demo-v1", (5,4,4,4,5,5,3)),
    "enhanced": ("records_service_simulated.py", "DEMO-SNAPSHOT-20260918-01", "demo-v1.1", (8,8,6,6,8,6,8)),
}


def load_profile(name):
    filename,snapshot,rule,counts=PROFILES[name]
    path=Path(__file__).with_name(filename)
    spec=importlib.util.spec_from_file_location("acceptance_fixture_"+name,path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    expected={key:module.response_for(key) for key in module.MODULES}
    assert tuple(len(expected[key]["records"]) for key in module.MODULES)==counts
    all_ids={row["record_id"] for value in expected.values() for row in value["records"]}
    for key,value in expected.items():
        assert value["snapshot_id"]==snapshot and value["rule_version"]==rule
        assert value["module"]==key and value["synthetic"] is True and value["rule_status"]=="demo_only"
        assert value["returned_count"]==value["total_count"]==len(value["records"])
        for row in value["records"]:
            assert row["source_type"] in module.MODULES
            assert all(row[k].startswith("DEMO-") for k in ("record_id","group_ref","member_ref"))
            assert set(row.get("source_record_ids",[]))<=all_ids
    return expected,{"profile":name,"snapshot_id":snapshot,"rule_version":rule,
                     "source_sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
                     "base_source_sha256":hashlib.sha256(path.with_name("records_service.py").read_bytes()).hexdigest()}
