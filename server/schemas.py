"""Pydantic response models. They mirror contracts/models.py field for field; tables are {columns, rows}.

Timestamps serialise as ISO 8601 with offset (e.g. 2026-04-01T00:00:00+05:30), NaN as null, numpy as plain numbers
(server/serialize.py converts before validation).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

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


class WhatIfAlertModel(BaseModel):
    timestamp: datetime
    type: str
    severity: str
    origin: str
    explanation: str


class WhatIfDayModel(FramesModel):
    """A what-if day through the full pipeline: frame columns as /frames (incl. health_*), where to put the cursor,
    and the alerts the analytics raised on it."""
    cursor: datetime
    load_profile: Literal["steady", "daily"]
    alerts: list[WhatIfAlertModel]


class ValueModel(BaseModel):
    value: float | None
    unit: str
    estimated: bool = Field(description="rests on an IEC typical value or a placeholder nameplate value")
    source: str = Field(description="measured | twin | model")


class ThermalProfileModel(BaseModel):
    """IEC 60076-7 thermal diagram and heat flow at one instant (twin/thermal_profile.py)."""
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


class CurveModel(BaseModel):
    t_min: list[float]
    top_oil_C: list[float]
    hot_spot_C: list[float]


class WhatIfStartModel(BaseModel):
    top_oil_C: float
    gradient_K: float
    from_: str = Field(alias="from")


class WhatIfModel(BaseModel):
    """Steady state at a load, ambient and cooling effectiveness, plus the approach curve (Simulate mode)."""
    load_pu: float
    ambient_C: float
    cooling: float
    current_A: float
    top_oil_C: float
    hot_spot_C: float
    bottom_oil_C: float
    avg_winding_C: float
    winding_gradient_K: float
    hot_spot_factor: float
    losses_noload_W: float
    losses_load_W: float
    losses_total_W: float
    heat_dissipated_W: float
    heat_stored_W: float
    oil_flow_intensity: float
    radiator_effectiveness: float
    tau_oil_min: float
    tau_winding_min: float
    ageing_rate: float
    ageing_rate_nominal_cooling: float = Field(description="same load and ambient with radiators as designed")
    hot_spot_nominal_cooling_C: float
    time_to_steady_min: float = Field(description="until top-oil and gradient are within 1 K of steady state")
    curve: CurveModel
    start: WhatIfStartModel
    params: dict[str, float]
    estimated: list[str] = Field(description="fields that rest on IEC typical values or placeholder losses")


class RecommendationBrief(BaseModel):
    action: str
    test: str | None
    urgency: str
    standard_ref: str | None


class FindingModel(BaseModel):
    id: str
    type: str
    origin: str
    severity: str
    cause: str = Field(description="CPRI cause group: Overloading | Insulation | Short circuit | Supply and connections | Oil | Sensors and data")
    module: str
    parts: list[str]
    count: int
    first: datetime
    last: datetime
    explanation: str
    indicative: bool = Field(description="severity info: shown, not counted (A27)")
    recommendation: RecommendationBrief | None


class LastEventModel(BaseModel):
    timestamp: datetime
    peak_pu: float
    duration_ms: float
    class_: str = Field(alias="class")


class StressModel(BaseModel):
    events: int
    moderate_pu: float
    severe_pu: float
    moderate_limit: int
    qualifying: int
    severe_seen: bool
    triggered: bool
    cum_i2t_pu2s: float
    last_event: LastEventModel | None


class FindingsModel(BaseModel):
    dataset_id: str
    timestamp: datetime | None
    causes: list[str]
    findings: list[FindingModel]
    stress: StressModel
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


class PhysicsWhatIfModel(BaseModel):
    series: dict[str, SeriesModel]
    summary: dict[str, Any]
