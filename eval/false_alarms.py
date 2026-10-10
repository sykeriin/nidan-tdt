"""False-alarm count on a scenario that has no faults. OWNER: Agent C (proof). STUB.

Contract:
    false_alarms(alerts, ground_truth) -> dict      # {"count": int, "by_type": {...}, "alerts_per_week": float}
On the Normal scenario ground_truth is empty, so every warning/critical asset alert is a false alarm.
Target: zero.
"""
from __future__ import annotations

from contracts.models import Alert


def false_alarms(alerts: list[Alert], ground_truth: list[dict]) -> dict:
    return {"count": 0, "by_type": {}, "alerts_per_week": 0.0}
