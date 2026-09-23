"""Legacy dual-Agent cases opt in explicitly; production defaults to theft only."""

import pytest


@pytest.fixture(autouse=True)
def legacy_agent_mode(monkeypatch):
    monkeypatch.setenv('PX_AGENT_MODE', 'dual')
