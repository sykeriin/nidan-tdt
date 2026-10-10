"""Pydantic response models. They mirror contracts/models.py field for field; tables are {columns, rows}.

Timestamps serialise as ISO 8601 with offset (e.g. 2026-04-01T00:00:00+05:30), NaN as null, numpy as plain numbers
(server/serialize.py converts before validation).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AlertModel(BaseModel):
    id: str
    timestamp: datetime
    module: str = Field(description="overloading | insulation | short_circuit | electrical | oil | moisture | data")
    type: str
    severity: str = Field(description="info | warning | critical")
    origin: str = Field(description="asset | sensor")
    detector: str = Field(description="rule | residual | ml | physics")
    value: float | None
    threshold: float | None
    explanation: str
    recommendation_id: str | None
    simulated: bool
    lead_time_h: float | None


class RecommendationModel(BaseModel):
    id: str
    action: str
    test: str | None
    urgency: str = Field(description="immediate | 24h | 7d | next_scheduled")
    rationale: str
    alert_id: str
    standard_ref: str | None


class HealthModel(BaseModel):
    score: float = Field(description="0-100")
    band: str = Field(description="Green (>= 80) | Yellow (60-79) | Red (< 60)")
    components: dict[str, float] = Field(description="sub-scores 0-100: thermal, ageing, loading, electrical, integrity, fault_stress")
    weights: dict[str, float]
    capped: bool


class RULModel(BaseModel):
    years_low: float
    years_high: float
    risk: str = Field(description="Low | Med | High")
    consumed_days: float
    recent_rate: float


class AnalysisResultModel(BaseModel):
    alerts: list[AlertModel]
    recommendations: list[RecommendationModel]
    health: HealthModel
    rul: RULModel | None
    fidelity_rmse_C: float | None


class TableModel(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any]]


class SeriesModel(BaseModel):
    t: list[datetime] = Field(description="sample times, ISO 8601 with offset")
    v: list[float | None]


class DatasetInfoModel(BaseModel):
    dataset_id: str
    name: str
    mode: str | None
    rows: int
    start: datetime | None
    end: datetime | None
    simulated: bool
    source: str
    health_score: float | None
    health_band: str | None
    cached: bool
    files: list[str] | None = Field(default=None, description="original file names (uploads only)")


class InspectResultModel(BaseModel):
    tables: list[dict[str, Any]]
    timestamp: dict[str, Any]
    proposals: list[dict[str, Any]]
    preview: TableModel
    warnings: list[str]


class DatasetModel(BaseModel):
    """contracts.models.Dataset without the frames (fetch them with /run)."""
    dataset_id: str
    mode: str
    rows: int
    capabilities: dict[str, bool]
    health_report: dict[str, Any]
    asset: dict[str, Any]


class RunModel(BaseModel):
    """contracts.models.Run; trend and health_series as downsampled series (<= max_points per series)."""
    dataset_id: str
    name: str
    mode: str
    capabilities: dict[str, bool]
    health_report: dict[str, Any]
    asset: dict[str, Any]
    summary: dict[str, Any]
    analysis: AnalysisResultModel
    series: dict[str, SeriesModel]
    health_series: dict[str, SeriesModel]
    bands: dict[str, list[Any]] = Field(description="health band per health_series sample time")
    events: TableModel
    records: TableModel | None = Field(default=None, description="snapshot mode: records ranked worst first")
    start: datetime | None
    end: datetime | None
    rows_in_range: int
    max_points: int
    downsampled: bool


class FramesModel(BaseModel):
    """Full-resolution, time-aligned columns (not downsampled): one list per field, same length as timestamp."""
    dataset_id: str
    rows: int
    timestamp: list[datetime]
    columns: dict[str, list[Any]]


class ValueModel(BaseModel):
    value: float | None
    unit: str
    estimated: bool = Field(description="rests on an IEC typical value or a placeholder nameplate value")
    source: str = Field(description="measured | twin | model")


class ThermalProfileModel(BaseModel):
    """IEC 60076-7 thermal diagram and heat flow at one instant (twin/profile.py)."""
    dataset_id: str
    timestamp: datetime
    mode: str
    values: dict[str, ValueModel]
    params: dict[str, float] = Field(description="model constants: P0_W, Pk_W, R, d_theta_or_K, x, y, gr_K, H, tau_*")
    simulated: bool


class QuantityModel(BaseModel):
    key: str
    label: str
    value: float | None
    unit: str
    kind: str = Field(description="measured | twin | residual | info")
    estimated: bool
    digits: int


class TermModel(BaseModel):
    symbol: str
    value: float | None
    unit: str
    meaning: str
    estimated: bool
    digits: int


class ResultModel(BaseModel):
    symbol: str
    value: float | None
    unit: str
    digits: int


class EquationModel(BaseModel):
    name: str
    symbolic: str
    substituted: str | None = Field(description="the equation with live values; null when an input is missing")
    result: ResultModel
    terms: list[TermModel]
    note: str | None
    estimated: bool


class PartAlertModel(BaseModel):
    id: str
    type: str
    severity: str
    origin: str
    timestamp: datetime
    explanation: str


class PartModel(BaseModel):
    quantities: list[QuantityModel]
    equations: list[EquationModel]
    alerts: list[PartAlertModel] = Field(description="alerts active on this part (last 24 h)")
    tests: list[str] = Field(description="recommended tests for those alerts")
    verdict: str | None = Field(default=None, description="oti only: inside | above | suspect")


class ComponentsModel(BaseModel):
    """Per-part view at one instant; part ids match web/src/twin/parts.ts."""
    dataset_id: str
    timestamp: datetime
    mode: str
    parts: dict[str, PartModel]
    simulated: bool


class StateAtModel(BaseModel):
    timestamp: datetime
    row: dict[str, Any]
    twin: dict[str, Any]
    mode: str
    health: HealthModel
    alerts: list[AlertModel]
    simulated: bool


class ErrorModel(BaseModel):
    detail: str
