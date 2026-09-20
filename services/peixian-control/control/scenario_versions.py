"""Immutable synthetic fixture registry: never enrich a Run with the latest fixture."""
import json
from pathlib import Path
ROOT = Path(__file__).parent
DATA14 = json.loads((ROOT / "scenario_data_v14.json").read_text())
DATA151 = json.loads((ROOT / "scenario_data_v151.json").read_text())
SOURCES14 = {"DEMO-CASE-THEFT": {"places": [{"id": "demo-place-dongjin", "label": "东津巷18号", "relationship": "相邻点", "device_ref": "东津巷口卡口", "source_ids": ["demo56", "demo35", "demo62"]}]}}
def select(scenario_id, scenario_snapshot, records_snapshot, legacy):
    for data in (legacy, DATA14, DATA151):
        context = data["scenarios"].get(scenario_id, {})
        if context.get("snapshot_id") == scenario_snapshot and context.get("records_snapshot_id") == records_snapshot:
            return data
    return None
def sources(data, legacy):
    versioned={(c['snapshot_id'],c['records_snapshot_id']) for version in (DATA14,DATA151) for c in version['scenarios'].values()}
    return SOURCES14 if any((c.get('snapshot_id'),c.get('records_snapshot_id')) in versioned for c in data.get('scenarios',{}).values()) else legacy
def supported_sources(context, cards):
    return set(cards) | {f["source_document"] for f in context["facts"] if f["record_id"] in cards and f.get("source_document")}
