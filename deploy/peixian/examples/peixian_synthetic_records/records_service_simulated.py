#!/usr/bin/env python3
"""Richer but wholly fictitious fixtures for the isolated records service.

The HTTP listener, Bearer validation and exact request validation stay in
``records_service.py``.  This overlay loads the same ``fixtures.json`` that the
plugin ships, so HTTP payloads and plugin-side canonical checks stay identical.
Every ``record_id`` is ``demo`` plus digits.  Names and places are fictional.
"""

from __future__ import annotations

import copy
import importlib.util
import json
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


def _fixtures_path() -> Path:
    here = Path(__file__).resolve().parent
    for candidate in (here / "plugin" / "fixtures.json", here / "fixtures.json"):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("fixtures.json is required next to the service or under plugin/")


DATA = json.loads(_fixtures_path().read_text(encoding="utf-8"))
FIXTURES = {module: copy.deepcopy(payload["records"]) for module, payload in DATA["records"].items()}


def response_for(module):
    return copy.deepcopy(DATA["records"][module])


base.SOURCE = "沛县七项合成资料服务（合成演示）"
base.FIXTURES = FIXTURES
base.response_for = response_for


if __name__ == "__main__":
    base.main()
