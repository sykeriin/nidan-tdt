"""Health Index (FINAL_PRD section 8.8). OWNER: Agent B (scoring and advice).

Contract:
    compute_series(df, alerts, caps, thresholds) -> pd.DataFrame
        columns: timestamp, score, band, thermal, ageing, loading, electrical, integrity, fault_stress, capped
    compute(df, alerts, caps, thresholds) -> Health      # value at the last timestamp

Score = weighted mean of six sub-scores (0..100, 100 = healthy), weights 30/25/15/15/10/5 renormalised over
the sub-scores that are available. A sub-score is available when its capability flag is set AND its input
column holds data; at a given row it also drops out if that row's inputs are NaN. If nothing is available the
score is 100 with empty weights (no evidence of a problem); callers can see that from `Health.weights == {}`.

Transparent mapping (the PRD gives no formula; every parameter is [Assumed] in config/health.yaml):
    Every "higher is worse" signal uses one piecewise-linear curve through four points
        100 at ok_fraction * warning  ->  score_at_warning (70) at warning
        ->  score_at_critical (30) at critical  ->  0 at critical + zero_span * (critical - warning)
    with warning/critical taken from thresholds.yaml where it has them:
    thermal      min(top-oil curve on OTI_C else twin_oil_C, hot-spot curve on twin_hs_C else WTI_C),
                 using top_oil_c and hot_spot_c warning/critical.
    ageing       aging_rate rolling mean (windows_h.ageing) on the ageing_rate points in health.yaml
                 (1.0 is the reference rate at hot-spot 98 C). Needs caps["ageing_rul"].
    loading      load_pu (else loading_pct/100) rolling mean (windows_h.loading) vs loading_pu warning/alarm.
    electrical   min(current unbalance % vs current_unbalance_pct warning/alarm, voltage unbalance % with
                 voltage_unbalance_pct.alarm as warning, voltage deviation from nominal as a fraction of the
                 voltage_pu limit). Needs caps["unbalance"] and/or caps["voltage_quality"].
    integrity    OLI_pct on a lower-is-worse curve (ok_pct -> oil_level_pct.low -> critical_pct), then capped
                 at alert_scores while an oil_leak/oil_theft alert is in effect. Needs caps["oil_leak_theft"].
    fault_stress 100 - per_event_penalty per through_fault alert so far (damage does not heal, no reset is
                 modelled), capped at alert_scores once a through_fault_stress alert exists.
                 Needs caps["through_fault"].

Weakest-link cap: a critical asset-origin alert whose timestamp lies in (t - cap_window_h, t] caps the score
at weakest_link.cap_score (40). Alerts carry only a start time, so this window defines "in effect".
`capped` is True only when the cap actually lowered the score. Bands: Green >= 80, Yellow 60-79, Red < 60.
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from analytics.common import step_hours
from contracts.models import Alert, Health

HEALTH_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "health.yaml"
DEFAULT_V_LN_NOMINAL_V = 239.6  # used only if thresholds["reference"] lacks v_ln_nominal_v
SUB_SCORES = ("thermal", "ageing", "loading", "electrical", "integrity", "fault_stress")


@lru_cache(maxsize=1)
def _default_config() -> dict:
    with open(HEALTH_CONFIG_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _config(thresholds: dict) -> dict:
    """Defaults from config/health.yaml; thresholds["health"] may override whole top-level blocks."""
    cfg = deepcopy(_default_config())
    for key, val in (thresholds.get("health") or {}).items():
        if isinstance(val, dict) and isinstance(cfg.get(key), dict):
            cfg[key].update(val)
        else:
            cfg[key] = val
    return cfg


def _curve(x: np.ndarray, ok: float, warn: float, crit: float, cfg: dict, lower_is_worse: bool = False) -> np.ndarray:
    """Piecewise-linear score; NaN in, NaN out."""
    c = cfg["curve"]
    zero = crit + c["zero_span"] * (crit - warn)
    xs = np.array([ok, warn, crit, zero], dtype=float)
    ys = np.array([100.0, c["score_at_warning"], c["score_at_critical"], 0.0])
    x = np.asarray(x, dtype=float)
    out = np.interp(-x, -xs, ys) if lower_is_worse else np.interp(x, xs, ys)
    return np.where(np.isnan(x), np.nan, out)


def _generic(x: np.ndarray, warn: float, crit: float, cfg: dict) -> np.ndarray:
    return _curve(x, cfg["curve"]["ok_fraction"] * warn, warn, crit, cfg)


def _col(df: pd.DataFrame, name: str) -> np.ndarray | None:
    """Column as float array, or None when absent or all NaN."""
    if name not in df.columns:
        return None
    v = pd.to_numeric(df[name], errors="coerce").to_numpy(dtype=float)
    return None if np.isnan(v).all() else v


def _first(df: pd.DataFrame, *names: str) -> np.ndarray | None:
    for n in names:
        v = _col(df, n)
        if v is not None:
            return v
    return None


def _rolling_mean(v: np.ndarray, steps: int) -> np.ndarray:
    return pd.Series(v).rolling(steps, min_periods=1).mean().to_numpy()


def _ns(ts) -> np.ndarray:
    return pd.DatetimeIndex(pd.to_datetime(ts, utc=True)).as_unit("ns").asi8


def _active(t_ns: np.ndarray, alert_ns: np.ndarray, window_h: float | None) -> np.ndarray:
    """True where an alert time lies in (t - window, t]; window None means any time up to t."""
    srt = np.sort(alert_ns)
    hi = np.searchsorted(srt, t_ns, side="right")
    if window_h is None:
        return hi > 0
    lo = np.searchsorted(srt, t_ns - int(window_h * 3.6e12), side="right")
    return hi > lo


def _unbalance(df: pd.DataFrame, cols: tuple[str, str, str], mean_col: str | None) -> np.ndarray | None:
    if any(c not in df.columns for c in cols):
        return None
    ph = df[list(cols)].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    if np.isnan(ph).all():
        return None
    mean = ph.mean(axis=1)
    if mean_col is not None and mean_col in df.columns:
        mean = np.where(np.isnan(pd.to_numeric(df[mean_col], errors="coerce")), mean, pd.to_numeric(df[mean_col], errors="coerce"))
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.abs(ph - mean[:, None]).max(axis=1) / mean * 100.0


def _thermal(df: pd.DataFrame, op: dict, cfg: dict) -> np.ndarray | None:
    parts = []
    oil = _first(df, "OTI_C", "twin_oil_C")
    if oil is not None:
        parts.append(_generic(oil, op["top_oil_c"]["warning"], op["top_oil_c"]["critical"], cfg))
    hs = _first(df, "twin_hs_C", "WTI_C")
    if hs is not None:
        parts.append(_generic(hs, op["hot_spot_c"]["warning"], op["hot_spot_c"]["critical"], cfg))
    if not parts:
        return None
    return np.nanmin(np.vstack(parts), axis=0) if len(parts) > 1 else parts[0]


def _load_pu(df: pd.DataFrame) -> np.ndarray | None:
    v = _col(df, "load_pu")
    if v is None:
        pct = _col(df, "loading_pct")
        v = None if pct is None else pct / 100.0
    return v


def _electrical(df: pd.DataFrame, op: dict, caps: dict, cfg: dict, load: np.ndarray | None, v_nom: float) -> np.ndarray | None:
    parts = []
    mult = cfg["voltage"]["critical_multiple"]
    if caps.get("unbalance"):
        iu = _unbalance(df, ("IR", "IY", "IB"), "I_mean")
        if iu is not None:
            if load is not None:
                iu = np.where(load < cfg["unbalance"]["min_load_pu"], 0.0, iu)
            cu = op["current_unbalance_pct"]
            parts.append(_generic(iu, cu["warning"], cu["alarm"], cfg))
    if caps.get("voltage_quality"):
        vu = _unbalance(df, ("VR", "VY", "VB"), None)
        if vu is not None:
            lim = op["voltage_unbalance_pct"]["alarm"]
            parts.append(_generic(vu, lim, mult * lim, cfg))
            vmean = df[["VR", "VY", "VB"]].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float).mean(axis=1)
            pu = vmean / v_nom
            hi, lo = op["voltage_pu"]["high"], op["voltage_pu"]["low"]
            ratio = np.where(pu >= 1.0, (pu - 1.0) / (hi - 1.0), (1.0 - pu) / (1.0 - lo))
            parts.append(_generic(np.where(np.isnan(pu), np.nan, ratio), 1.0, mult, cfg))
    if not parts:
        return None
    return np.nanmin(np.vstack(parts), axis=0) if len(parts) > 1 else parts[0]


def _integrity(df: pd.DataFrame, t_ns: np.ndarray, alerts: list[Alert], op: dict, cfg: dict) -> np.ndarray | None:
    lvl = _col(df, "OLI_pct")
    if lvl is None:
        return None
    o = cfg["oil_level"]
    score = _curve(lvl, o["ok_pct"], op["oil_level_pct"]["low"], o["critical_pct"], cfg, lower_is_worse=True)
    window = cfg["weakest_link"]["cap_window_h"]
    for sev, ceiling in (("warning", cfg["alert_scores"]["warning"]), ("critical", cfg["alert_scores"]["critical"])):
        times = [a.timestamp for a in alerts if a.type in ("oil_leak", "oil_theft") and a.severity == sev]
        if times:
            score = np.where(_active(t_ns, _ns(times), window), np.minimum(score, ceiling), score)
    return score


def _fault_stress(t_ns: np.ndarray, alerts: list[Alert], cfg: dict) -> np.ndarray:
    score = np.full(len(t_ns), 100.0)
    faults = [a.timestamp for a in alerts if a.type == "through_fault"]
    if faults:
        n = np.searchsorted(np.sort(_ns(faults)), t_ns, side="right")
        score = np.maximum(0.0, 100.0 - cfg["through_fault"]["per_event_penalty"] * n)
    ceilings = cfg["alert_scores"]
    for sev in ("warning", "critical"):
        times = [a.timestamp for a in alerts if a.type == "through_fault_stress" and a.severity == sev]
        if times:
            score = np.where(_active(t_ns, _ns(times), None), np.minimum(score, ceilings[sev]), score)
    return score


def _band(score: float, cfg: dict) -> str:
    if score >= cfg["bands"]["green_min"]:
        return "Green"
    return "Yellow" if score >= cfg["bands"]["yellow_min"] else "Red"


def compute_series(df: pd.DataFrame, alerts: list[Alert], caps: dict, thresholds: dict) -> pd.DataFrame:
    cols = ["timestamp", "score", "band", *SUB_SCORES, "capped"]
    if df is None or len(df) == 0 or "timestamp" not in df.columns:
        return pd.DataFrame(columns=cols)
    cfg = _config(thresholds)
    op = thresholds["operating"]
    n = len(df)
    t_ns = _ns(df["timestamp"])
    step = step_hours(df) if n > 1 else float("nan")
    steps = lambda hours: 1 if not step or np.isnan(step) else max(1, int(round(hours / step)))  # noqa: E731

    load = _load_pu(df)
    sub: dict[str, np.ndarray | None] = dict.fromkeys(SUB_SCORES)
    sub["thermal"] = _thermal(df, op, cfg)
    rate = _col(df, "aging_rate_actual")  # actual ageing (measured OTI + gradient) when the twin provides it
    if rate is None:
        rate = _col(df, "aging_rate")
    if caps.get("ageing_rul") and rate is not None:
        a = cfg["ageing_rate"]
        sub["ageing"] = _curve(_rolling_mean(rate, steps(cfg["windows_h"]["ageing"])), a["ok"], a["warning"], a["critical"], cfg)
    if load is not None:
        lp = op["loading_pu"]
        sub["loading"] = _generic(_rolling_mean(load, steps(cfg["windows_h"]["loading"])), lp["warning"], lp["alarm"], cfg)
    if caps.get("unbalance") or caps.get("voltage_quality"):
        sub["electrical"] = _electrical(df, op, caps, cfg, load, thresholds.get("reference", {}).get("v_ln_nominal_v", DEFAULT_V_LN_NOMINAL_V))
    if caps.get("oil_leak_theft"):
        sub["integrity"] = _integrity(df, t_ns, alerts, op, cfg)
    if caps.get("through_fault"):
        sub["fault_stress"] = _fault_stress(t_ns, alerts, cfg)

    w = np.array([cfg["weights"][k] for k in SUB_SCORES], dtype=float)
    mat = np.vstack([np.full(n, np.nan) if sub[k] is None else np.clip(sub[k], 0.0, 100.0) for k in SUB_SCORES])
    avail = ~np.isnan(mat)
    wsum = (avail * w[:, None]).sum(axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        raw = np.where(wsum > 0, (np.nan_to_num(mat) * w[:, None]).sum(axis=0) / wsum, 100.0)

    crit = [a.timestamp for a in alerts if a.severity == "critical" and a.origin == "asset"]
    cap_on = _active(t_ns, _ns(crit), cfg["weakest_link"]["cap_window_h"]) if crit else np.zeros(n, dtype=bool)
    cap_score = cfg["weakest_link"]["cap_score"]
    capped = cap_on & (raw > cap_score)
    score = np.clip(np.where(cap_on, np.minimum(raw, cap_score), raw), 0.0, 100.0)

    out = pd.DataFrame({"timestamp": df["timestamp"].reset_index(drop=True)})
    out["score"] = score
    out["band"] = [_band(s, cfg) for s in score]
    for i, k in enumerate(SUB_SCORES):
        out[k] = mat[i]
    out["capped"] = capped
    return out


def compute(df: pd.DataFrame, alerts: list[Alert], caps: dict, thresholds: dict) -> Health:
    series = compute_series(df, alerts, caps, thresholds)
    if series.empty:
        return Health(score=100.0, band="Green", components={}, weights={}, capped=False)
    cfg = _config(thresholds)
    last = series.iloc[-1]
    comps = {k: float(last[k]) for k in SUB_SCORES if not pd.isna(last[k])}
    total = sum(cfg["weights"][k] for k in comps)
    weights = {k: cfg["weights"][k] / total for k in comps} if total else {}
    return Health(
        score=float(last["score"]), band=str(last["band"]), components=comps, weights=weights, capped=bool(last["capped"])
    )
