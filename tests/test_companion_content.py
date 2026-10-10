"""The companion app's pre-written responses must cover exactly the alert types the backend can raise."""
import json
from pathlib import Path

import pytest

from analytics.common import ALERT_MODULES

PATH = Path(__file__).resolve().parent.parent / "companion" / "content" / "responses.json"
CONTENT = json.loads(PATH.read_text(encoding="utf-8"))
TYPES = CONTENT["types"]
TEXT_FIELDS = ("title", "push", "meaning", "safe_to_wait", "escalate_if", "who")
URGENCIES = set(CONTENT["urgency_label"])


def test_every_backend_alert_type_has_a_response():
    assert set(TYPES) == set(ALERT_MODULES)


@pytest.mark.parametrize("t", sorted(ALERT_MODULES))
def test_response_is_complete(t):
    r = TYPES[t]
    for f in TEXT_FIELDS:
        assert isinstance(r[f], str) and r[f].strip(), f"{t}.{f}"
    assert len(r["push"]) <= 90, f"{t}: push text too long for a notification"
    for f in ("do_now", "check"):
        assert r[f] and all(isinstance(s, str) and s.strip() for s in r[f]), f"{t}.{f}"
    assert {"critical", "warning", "info"} <= set(r["urgency"])
    assert set(r["urgency"].values()) <= URGENCIES


@pytest.mark.parametrize("t", sorted(t for t, m in ALERT_MODULES.items() if m == "data"))
def test_sensor_responses_point_at_the_device(t):
    assert "device" in TYPES[t]["meaning"].lower() or "sensor" in TYPES[t]["meaning"].lower()
    assert TYPES[t]["who"] == "Instrument technician"


def test_no_test_limits_invented():
    """Recommendation text must not state numeric limits (they come from the standard, marked to-verify)."""
    import re
    for t, r in TYPES.items():
        blob = " ".join([r["meaning"], r["safe_to_wait"], r["escalate_if"], *r["do_now"], *r["check"]])
        assert not re.search(r"\d+\s?(%|°C|A\b|kV|V\b)", blob), f"{t}: numeric limit in text"
