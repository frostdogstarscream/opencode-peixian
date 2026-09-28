import pathlib
import re

from shared import tool_failure

CONTROL = pathlib.Path(__file__).resolve().parents[1] / 'control'
GATEWAY_PATH_MODULES = ('native_tool_gate.py', 'native_tool_scope.py', 'theft_candidates.py')
PRECHECK_CODES = (
    'candidate_limit_invalid', 'candidate_set_empty', 'candidate_source_incomplete',
    'source_selection_invalid', 'source_contract_unsupported', 'intent_review_invalid',
    'intent_binding_changed', 'tool_call_identity_invalid', 'scope_unavailable',
    'native_plugin_version_required',
)


def raised_codes():
    codes = set()
    for name in GATEWAY_PATH_MODULES:
        codes |= set(re.findall(r"\berror\(\s*'([a-z_]+)'", (CONTROL / name).read_text(encoding='utf-8')))
    return codes


def test_every_gateway_facing_code_has_a_public_message():
    missing = raised_codes() - set(tool_failure.MESSAGES)
    assert not missing, f'add these codes to shared/tool_failure.MESSAGES (and rebuild the gateway): {sorted(missing)}'


def test_public_keeps_scene_entry_codes():
    for code in ('case_entry_missing', 'person_case_tracks_first', 'person_case_centers_done', 'person_lookup_invalid'):
        assert tool_failure.public({'code': code})['code'] == code


def test_precheck_codes_are_reported_as_not_dispatched():
    for code in PRECHECK_CODES:
        detail = tool_failure.public({'code': code}, 'native_prepare')
        assert detail['code'] == code and detail['dispatch_status'] == 'not_dispatched', code
