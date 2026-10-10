"""Real data for analytics tests and evaluation: generator -> adapter -> twin (replaces tests/mock_data.py).

    df, events = load_scenario("S2")          # canonical trend + twin columns (PRD 7.2), events table
    caps = capabilities("S2")                 # adapter capability matrix (main vocabulary), twin-adjusted
    gt = ground_truth("S2")                   # [{fault, onset, end, expect}] from gt_* columns + scenarios.yaml
    ref = normal_reference(thresholds)        # residual.calibrate on the real Normal twin run
    kdf, kcaps = kaggle()                     # cleaned Kaggle data through the twin (estimated rating)

Ground truth is used only by eval/ and tests, never by detectors (they strip gt_*).
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pandas as pd

from contracts.canonical import TZ
from ingest.adapter import load
from twin.engine import TwinEngine

ROOT = Path(__file__).resolve().parent.parent
GEN = ROOT / "data" / "generated"
SCENARIOS = ("N", "S1", "S2", "S3", "S4a", "S4b", "S5")
START = pd.Timestamp("2026-04-01 00:00", tz=TZ)
EXPECT = {  # alert types that count as detecting each fault
    "overload": ["loading_high", "overcurrent", "hot_spot_high", "top_oil_high", "ageing_rate_high"],
    "cooling_degradation": ["residual_drift", "top_oil_high", "hot_spot_high", "ageing_rate_high"],  # + consequences
    "unbalance": ["current_unbalance"],
    "oil_leak": ["oil_leak", "oil_low"],
    "oil_theft": ["oil_theft", "oil_low"],
    "through_fault": ["through_fault", "through_fault_stress"],
}
FAULT = {"S1": "overload", "S2": "cooling_degradation", "S3": "unbalance", "S4a": "oil_leak",
         "S4b": "oil_theft", "S5": "through_fault"}
# Placeholder losses for the Kaggle unit (no nameplate): only the load/no-load ratio matters to the twin. [Assumed]
KAGGLE_LOSSES = {"load_loss_W": 2300.0, "no_load_loss_W": 350.0, "years_in_service": 0}


def effective_caps(caps: dict, df_twin: pd.DataFrame) -> dict:
    """Adapter capabilities adjusted by the twin: a top-oil channel that fails the physics plausibility check
    can't support residual/fidelity analytics (PRD 7.4)."""
    out = dict(caps)
    if df_twin.attrs.get("plausibility", {}).get("OTI_C") == "suspect":
        out["residual_fidelity"] = False
    return out


@lru_cache(maxsize=None)
def _scenario(sid: str) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    if sid not in SCENARIOS:
        raise ValueError(f"unknown scenario {sid!r}")
    paths = [GEN / f"trend_{sid}.csv"]
    ev = GEN / f"events_{sid}.csv"
    if ev.exists() and len(pd.read_csv(ev)):
        paths.append(ev)
    ds = load(paths, asset="config/asset.yaml", source="generated_sim", simulated=True)
    twin = TwinEngine().run(ds)
    return twin, ds.events, effective_caps(ds.capabilities, twin)


def load_scenario(sid: str, days: float | None = None, seed: int = 0) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Twin output for a scenario. seed=0 is the shipped data (data/generated); other seeds are generated on the fly
    (generator -> twin, no files) to check robustness on plants with different perturbed parameters."""
    if seed:
        twin, events = _other_seed(sid, seed)
    else:
        twin, events, _ = _scenario(sid)
    attrs = dict(twin.attrs)
    twin, events = twin.copy(), events.copy()
    twin.attrs = attrs
    if days is not None:
        end = START + pd.Timedelta(days=days)
        twin = twin[twin["timestamp"] < end].reset_index(drop=True)
        events = events[events["timestamp"] < end].reset_index(drop=True)
    return twin, events


@lru_cache(maxsize=None)
def _other_seed(sid: str, seed: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    from sim.generator import generate
    trend, events = generate(sid, seed=seed)
    return TwinEngine().run(trend), events


def capabilities(sid: str = "N") -> dict:
    return dict(_scenario(sid)[2])


def ground_truth(sid: str) -> list[dict]:
    if sid == "N":
        return []
    twin, events, _ = _scenario(sid)
    fault = FAULT[sid]
    if sid == "S5":
        onset, end = events["timestamp"].min(), events["timestamp"].max() + pd.Timedelta(minutes=1)
    else:
        g = twin.loc[twin["gt_fault"] == 1, "timestamp"]
        onset, end = g.min(), g.max() + pd.Timedelta(minutes=15)
    return [{"fault": fault, "onset": onset, "end": end, "expect": list(EXPECT[fault])}]


def normal_reference(thresholds: dict) -> dict:
    from analytics import residual
    from analytics.common import strip_quarantined
    return residual.calibrate(strip_quarantined(load_scenario("N")[0]), thresholds)


@lru_cache(maxsize=1)
def _kaggle() -> tuple[pd.DataFrame, dict]:
    clean = ROOT / "data" / "clean"
    if not (clean / "kaggle.parquet").exists():
        from ingest import kaggle_clean
        kaggle_clean.main()
    k = pd.read_parquet(clean / "kaggle.parquet")
    rep = json.loads((clean / "kaggle_health_report.json").read_text(encoding="utf-8"))
    asset = {**rep["asset"], **KAGGLE_LOSSES}
    twin = TwinEngine(asset).run(k)
    return twin, effective_caps(rep["capabilities"], twin)


def kaggle() -> tuple[pd.DataFrame, dict]:
    twin, caps = _kaggle()
    out = twin.copy()
    out.attrs = dict(twin.attrs)
    return out, dict(caps)
