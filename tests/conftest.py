import socket
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session", autouse=True)
def generated_data():
    """Fresh clone: build generated scenarios and fixtures once (offline: weather comes from the cache)."""
    from sim import fixtures, generator
    if not all((ROOT / "data" / "generated" / f"trend_{s}.csv").exists() for s in generator.SCENARIO_IDS):
        for s in generator.SCENARIO_IDS:
            generator.write(s)
    if not (ROOT / "data" / "fixtures" / "F6_line_line_kA.csv").exists():
        fixtures.build()


@pytest.fixture
def no_network(monkeypatch):
    def guard(*a, **k):
        raise OSError("network disabled in test")
    monkeypatch.setattr(socket, "socket", guard)
    monkeypatch.setattr(socket, "create_connection", guard)
