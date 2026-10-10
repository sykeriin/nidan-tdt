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


# ---------------------------------------------------------------- generic profile, simulate, physics
class ProfileIn(BaseModel):
    values: dict[str, Any] = Field(description="Any of: rating_kVA, lv_voltage_V, hv_voltage_V, load_loss_W, no_load_loss_W, "
                                   "total_loss_100_W, total_loss_50_W, top_oil_rise_K, ... (twin/profile.py). Rating or rated current is required.")
    tags: dict[str, str] | None = Field(default=None, description="optional source tag per value; untagged values are 'User input'")


class ProfileModel(BaseModel):
    values: dict[str, Any]
    tags: dict[str, str]
    notes: list[str]


class PresetModel(ProfileModel):
    id: str
    label: str
    description: str


class SimulateIn(ProfileIn):
    scenario: str = Field(default="N", description="N | S1 | S2 | S3 | S4a | S4b | S5")
    seed: int = 0
    name: str | None = None
    plant: str = Field(default="iec", description="iec: thermal library with perturbed parameters | detailed: independent heat-balance model")


class DetailedIn(ProfileIn):
    from_pu: float = Field(default=0.4, ge=0, le=3)
    to_pu: float = Field(default=1.2, ge=0, le=3)
    ambient_C: float = Field(default=30.0, ge=-30, le=60)
    minutes: int = Field(default=600, ge=10, le=2880)
    k_factor: float = Field(default=1.0, ge=1, le=20, description="harmonic K-factor; adds eddy and stray loss")
    use_mass_capacity: bool = Field(default=False, description="use the thermal capacity implied by the nameplate masses")


class IngestIn(BaseModel):
    session: str = Field(description="1 to 40 letters, digits, '-' or '_'; becomes the dataset u-live-<session>")
    rows: list[dict[str, Any]] = Field(description="readings, any column names the adapter can map (timestamp, IR, IY, IB, VR, OTI_C, amb_C ...)")
    asset: dict[str, Any] | None = Field(default=None, description="optional transformer profile values (rating_kVA, lv_voltage_V ...); default is Transformer-1")


class ChainIn(ProfileIn):
    load_pu: float = Field(default=1.0, ge=0, le=3)
    ambient_C: float = Field(default=30.0, ge=-30, le=60)


class StepIn(ProfileIn):
    from_pu: float = Field(default=0.4, ge=0, le=3)
    to_pu: float = Field(default=1.2, ge=0, le=3)
    ambient_C: float = Field(default=30.0, ge=-30, le=60)
    minutes: int = Field(default=480, ge=10, le=2880)


class WhatIfIn(BaseModel):
    model: str = Field(default="iec", description="iec | detailed")
    k_factor: float = Field(default=1.0, ge=1, le=20)
    load_mult: float = Field(default=1.0, ge=0.2, le=2.0)
    ambient_offset_C: float = Field(default=0.0, ge=-15, le=25)
    rise_mult: float = Field(default=1.0, ge=0.7, le=2.0, description=">1 models degraded cooling")


class ChainStepModel(BaseModel):
    id: str
    title: str
    formula: str
    working: str
    value: float
    unit: str
    why: str


class ChainModel(BaseModel):
    steps: list[ChainStepModel]
    inputs: dict[str, float]
    top_oil_C: float
    hot_spot_C: float
    ageing_rate: float
    hours_per_equivalent_day: float | None
    library_check: dict[str, Any]
    parameters: dict[str, float]
    tags: dict[str, Any]


class StepResponseModel(BaseModel):
    t_min: list[int]
    top_oil_C: list[float]
    hot_spot_C: list[float]
    final: dict[str, float]
    time_constants_min: dict[str, float]
    inputs: dict[str, float]


class WhatIfModel(BaseModel):
    series: dict[str, SeriesModel]
    summary: dict[str, Any]
