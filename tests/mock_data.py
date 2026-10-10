"""MOCK data for P3 development and tests.

NOT real and NOT the P2 generator. It is a deliberately simple stand-in with the same columns the real
pipeline will provide (FINAL_PRD sections 3.1, 5.2, 7.2) and KNOWN injected faults, so detectors have a ground
truth to be tested against. Every row carries source="mock", simulated=True.

Replace with P2's generator output when it exists. The shapes and column names must stay compatible.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

I_RATED = 1391.0  # A, 1000 kVA at 415 V   [Assumed asset]
V_LN = 239.6  # V
R_LOSS = 9.09  # load loss / no-load loss  [placeholder losses]
RISE_RATED = 60.0  # K top-oil rise at rated load (IEC default)
X_OIL = 0.8
Y_WIND = 1.6
GRADIENT = 23.0  # K winding-oil gradient at rated load
TAU_STEPS = 12  # 180 min oil time constant at 15 min steps
SCENARIOS = ("N", "S1", "S2", "S3", "S4", "S5")
START = pd.Timestamp("2026-04-01 00:00", tz="Asia/Kolkata")

TREND_COLS = [
    "timestamp", "IR", "IY", "IB", "I_mean", "IN", "VR", "VY", "VB", "S_kVA", "loading_pct",
    "OTI_C", "WTI_C", "amb_C", "RH_pct", "OLI_pct", "dq_flags", "source", "simulated",
    "load_pu", "twin_oil_C", "twin_hs_C", "aging_rate", "days_aged_cum", "residual_oil_C", "fidelity_rmse_C",
    "gt_fault",
]
EVENT_COLS = ["timestamp", "event_type", "phase", "peak_pu", "duration_ms", "i2t_pu2s", "source", "simulated"]


def _lag(x: np.ndarray, tau: float) -> np.ndarray:
    y = np.empty_like(x, dtype=float)
    y[0] = x[0]
    a = 1.0 / tau
    for i in range(1, len(x)):
        y[i] = y[i - 1] + a * (x[i] - y[i - 1])
    return y


def _ult_rise(k: np.ndarray, mult: np.ndarray | float = 1.0, base: float = RISE_RATED) -> np.ndarray:
    return base * mult * ((1 + R_LOSS * k**2) / (1 + R_LOSS)) ** X_OIL


def make_mock(scenario: str = "N", seed: int = 0, days: int = 30) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (trend, events) for a mock scenario. Deterministic for a given seed."""
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}")
    rng = np.random.default_rng(seed)
    n = days * 96
    ts = pd.date_range(START, periods=n, freq="15min")
    h = np.asarray(ts.hour + ts.minute / 60.0)
    dow = np.asarray(ts.dayofweek)
    day = np.arange(n) / 96.0

    # Campus load profile (per unit), weekday peak ~0.62
    base = 0.32 + 0.30 * np.clip(np.sin((h - 7) / 11 * np.pi), 0, None) * np.where(dow < 5, 1.0, 0.5)
    load = base + rng.normal(0, 0.012, n)
    amb = 27 + 7 * np.sin((h - 9) / 24 * 2 * np.pi) + rng.normal(0, 0.3, n)

    rise_mult = np.ones(n)
    pf = np.array([1.0, 1.0, 1.0])
    oil_level = np.full(n, 100.0)
    gt = np.array([""] * n, dtype=object)

    if scenario == "S1":  # overload, days 24-27, daytime
        m = (day >= 24) & (day < 27) & (h >= 8) & (h < 18)
        load = np.where(m, 1.15 + 0.20 * np.clip(np.sin((h - 8) / 10 * np.pi), 0, None), load)
        gt[(day >= 24) & (day < 27)] = "overload"
    if scenario == "S2":  # cooling degradation, ramp from day 20
        rise_mult = 1 + 0.25 * np.clip((day - 20) / 8, 0, 1)
        gt[day >= 20] = "cooling_degradation"
    if scenario == "S3":  # unbalance from day 25
        pf = np.array([1.15, 0.92, 1.0])
        gt[day >= 25] = "unbalance"
    if scenario == "S4":  # slow leak days 20-25, theft step day 27 02:30
        oil_level = 100 - 22 * np.clip((day - 20) / 5, 0, 1)
        theft_at = (START + pd.Timedelta(days=27, hours=2, minutes=30))
        oil_level = np.where(ts >= theft_at, oil_level - 12, oil_level)
        gt[(day >= 20) & (day < 25)] = "oil_leak"
        gt[ts >= theft_at] = "oil_theft"

    # Phase currents (A): small natural imbalance plus scenario imbalance
    nat = np.array([1.0, 1.0, 1.0]) * (1 + rng.normal(0, 0.01, (n, 3)))
    ph = (load[:, None] * I_RATED) * nat * pf[None, :]
    ph += rng.normal(0, 0.003 * I_RATED * 0.5, ph.shape)
    i_mean = ph.mean(axis=1)
    k = i_mean / I_RATED  # per-unit load seen by the twin

    # Plant (the "measured" data): perturbed parameters, scenario faults, sensor noise
    oil_plant = _lag(amb + _ult_rise(k, rise_mult, base=RISE_RATED * 1.03), TAU_STEPS) + rng.normal(0, 0.4, n)
    wti = oil_plant + GRADIENT * k**Y_WIND + rng.normal(0, 0.5, n)
    # Twin: nominal parameters, measured load and ambient only
    oil_twin = _lag(amb + _ult_rise(k), TAU_STEPS)
    hs_twin = oil_twin + GRADIENT * k**Y_WIND
    aging = 2.0 ** ((hs_twin - 98.0) / 6.0)
    resid = oil_plant - oil_twin
    fid = pd.Series(resid).rolling(96, min_periods=8).apply(lambda r: float(np.sqrt(np.mean(np.square(r)))), raw=True)

    vph = V_LN * (1 - 0.02 * k[:, None]) + rng.normal(0, 0.8, (n, 3))
    trend = pd.DataFrame(
        {
            "timestamp": ts,
            "IR": ph[:, 0], "IY": ph[:, 1], "IB": ph[:, 2], "I_mean": i_mean,
            "IN": np.nan,
            "VR": vph[:, 0], "VY": vph[:, 1], "VB": vph[:, 2],
            "S_kVA": 3 * V_LN * i_mean / 1000.0,
            "loading_pct": k * 100.0,
            "OTI_C": oil_plant, "WTI_C": wti, "amb_C": amb,
            "RH_pct": np.clip(60 + 20 * np.sin((h - 3) / 24 * 2 * np.pi) + rng.normal(0, 3, n), 10, 100),
            "OLI_pct": oil_level + rng.normal(0, 0.15, n),
            "dq_flags": "", "source": "mock", "simulated": True,
            "load_pu": k, "twin_oil_C": oil_twin, "twin_hs_C": hs_twin, "aging_rate": aging,
            "days_aged_cum": np.cumsum(aging * 15 / 1440.0), "residual_oil_C": resid,
            "fidelity_rmse_C": fid.to_numpy(),
            "gt_fault": gt,
        }
    )[TREND_COLS]

    ev_rows = []
    if scenario == "S5":  # event table only; invisible in the 15-minute trend
        for (d, hh, mm, pk, ms) in [(27, 10, 14, 6.0, 300), (27, 10, 22, 10.0, 500), (27, 15, 40, 3.5, 200)]:
            ev_rows.append(
                {
                    "timestamp": START + pd.Timedelta(days=d, hours=hh, minutes=mm),
                    "event_type": "through_fault", "phase": "3ph",
                    "peak_pu": pk, "duration_ms": ms, "i2t_pu2s": pk**2 * ms / 1000.0,
                    "source": "mock", "simulated": True,
                }
            )
    events = pd.DataFrame(ev_rows, columns=EVENT_COLS)
    return trend, events


def ground_truth(scenario: str) -> list[dict]:
    """Known injected faults. Used ONLY by evaluation, never by detectors."""
    d = lambda days, hours=0, minutes=0: START + pd.Timedelta(days=days, hours=hours, minutes=minutes)  # noqa: E731
    table = {
        "N": [],
        "S1": [{"fault": "overload", "onset": d(24, 8), "end": d(27), "expect": ["loading_high", "overcurrent", "hot_spot_high"]}],
        "S2": [{"fault": "cooling_degradation", "onset": d(20), "end": d(30), "expect": ["residual_drift"]}],
        "S3": [{"fault": "unbalance", "onset": d(25), "end": d(30), "expect": ["current_unbalance"]}],
        "S4": [
            {"fault": "oil_leak", "onset": d(20), "end": d(25), "expect": ["oil_leak", "oil_low"]},
            {"fault": "oil_theft", "onset": d(27, 2, 30), "end": d(27, 3, 30), "expect": ["oil_theft"]},
        ],
        "S5": [
            {"fault": "through_fault", "onset": d(27, 10, 14), "end": d(27, 15, 41), "expect": ["through_fault", "through_fault_stress"]}
        ],
    }
    return table[scenario]


def mock_caps(meter_only: bool = False) -> dict[str, bool]:
    """Capability matrix for the mock data (all channels present except IN)."""
    return {
        "thermal_twin": True, "residual": not meter_only, "hotspot_wti": True, "unbalance_current": True,
        "voltage_quality": True, "neutral_current": False, "oil_level": True, "through_fault": True,
        "breathing": True, "aging_rul": True, "lead_time": True,
    }
