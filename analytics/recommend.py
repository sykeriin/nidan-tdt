"""Recommendation engine. OWNER: Agent B (scoring and advice). STUB.

Contract:
    build(alerts, health, thresholds) -> list[Recommendation]
Table: FINAL_PRD section 8.10. Every alert type in analytics.common.ALERT_MODULES must map to at least
one recommendation. Each recommendation: action, test, urgency (immediate|24h|7d|next_scheduled),
rationale (names the triggering signal), alert_id, standard_ref. It must also set alert.recommendation_id.
Test names are standard; whether CEA specifically recommends each is [To verify], so put that in standard_ref text.
"""
from __future__ import annotations

from contracts.models import Alert, Health, Recommendation


def build(alerts: list[Alert], health: Health, thresholds: dict) -> list[Recommendation]:
    return []
