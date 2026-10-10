"""Shared dataclasses (FINAL_PRD.md §12.3). Contract: change only with all four owners agreeing."""
from dataclasses import dataclass, field

import pandas as pd


@dataclass
class Dataset:
    trend: pd.DataFrame
    events: pd.DataFrame
    capabilities: dict[str, bool]
    mode: str                      # full | meter_only | data_only
    health_report: dict
    asset: dict


@dataclass
class InspectResult:
    """Adapter proposal before anything is committed (Import page input)."""
    tables: list[dict]             # [{name, role, rows, columns}]
    timestamp: dict                # {column, dayfirst, parsed_ok_pct}
    proposals: list[dict]          # [{source, canonical, confidence, unit, unit_options}]
    preview: pd.DataFrame
    warnings: list[str] = field(default_factory=list)


@dataclass
class TwinState:
    timestamp: pd.Timestamp
    row: dict
    twin: dict
    mode: str


@dataclass
class Alert:
    id: str
    timestamp: pd.Timestamp
    module: str        # overloading | insulation | short_circuit | electrical | oil | moisture | data
    type: str          # e.g. residual_drift, through_fault, oil_theft, oil_leak, jump_oti, unbalance
    severity: str      # info | warning | critical
    origin: str        # asset | sensor
    detector: str      # rule | residual | ml | physics
    value: float | None
    threshold: float | None
    explanation: str
    recommendation_id: str | None
    simulated: bool
    lead_time_h: float | None


@dataclass
class Recommendation:
    id: str
    action: str
    test: str | None
    urgency: str       # immediate | 24h | 7d | next_scheduled
    rationale: str
    alert_id: str
    standard_ref: str | None


@dataclass
class Health:
    score: float
    band: str
    components: dict[str, float]
    weights: dict[str, float]
    capped: bool


@dataclass
class RUL:
    years_low: float
    years_high: float
    risk: str
    consumed_days: float
    recent_rate: float


@dataclass
class AnalysisResult:
    alerts: list[Alert]
    recommendations: list[Recommendation]
    health: Health
    rul: RUL | None
    fidelity_rmse_C: float | None
