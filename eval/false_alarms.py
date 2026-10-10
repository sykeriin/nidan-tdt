"""False-alarm count against ground truth. OWNER: Agent C (proof).

Contract:
    false_alarms(alerts, ground_truth, days=30) -> dict
        {"count", "by_type", "alerts_per_week", "true_positive_count"}
An alert is a true positive if it matches a ground-truth fault (type in the fault's expect list, timestamp in
[onset, end + 24 h]); otherwise it is a false alarm. Severity "info" alerts are ignored. On the Normal scenario
ground_truth is empty, so every warning/critical alert is a false alarm. Target: zero.
"""
from __future__ import annotations

from collections import Counter

from contracts.models import Alert
from eval.lead_time import alert_matches_fault


def false_alarms(alerts: list[Alert], ground_truth: list[dict], days: float = 30) -> dict:
    """Count warning/critical alerts that match no ground-truth fault. `days` is the data span."""
    counted = [a for a in alerts if a.severity != "info"]
    false_ones = [a for a in counted if not any(alert_matches_fault(a, f) for f in ground_truth)]
    return {
        "count": len(false_ones),
        "by_type": dict(Counter(a.type for a in false_ones)),
        "alerts_per_week": len(false_ones) / (days / 7.0),
        "true_positive_count": len(counted) - len(false_ones),
    }
