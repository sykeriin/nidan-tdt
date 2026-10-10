"""Sensor / data faults vs asset faults. OWNER: Agent E (FINAL_PRD section 8.6).

Contract:
    detect(df, thresholds, caps=None) -> list[Alert]    # origin="sensor", module "data", detector "physics"
    episodes(df, thresholds, caps=None) -> list[Episode]  # the same, with row spans (used for relabelling)
    relabel(alerts, episodes) -> list[Alert]            # used by the pipeline (see analytics/pipeline.py)

A lying sensor must never be reported as a transformer fault. Checks, one alert per episode (not per sample):
  JUMP   oil / winding temperature step impossible for the thermal time constant (jump_sensor)
  RANGE  value outside its physical range (range_sensor)
  STUCK  a channel unchanged for >= 8 samples while load changes by > 10 % (stuck_sensor)
  DEAD   a temperature channel that is ~0 / a 0-1 flag over the whole data while others vary (dead_channel)
  DQ     JUMP_*, STUCK_*, RANGE_*, NEG_* codes in the optional dq_flags column (DATA_INGESTION_SPEC 2.8),
         de-duplicated against the physics episodes above.

Offline versus bad sensor: a row is OFFLINE (start-up, device not reporting) when every liveness channel
that has a value (IR, IY, IB, VR, VY, VB, OTI_C, amb_C) is exactly 0. Offline rows are skipped by every check,
and no step is evaluated across them. A row is DE-ENERGISED when all present V and I channels are exactly 0
while temperatures are alive (a real outage); voltage range and voltage stuck checks skip those rows.
A voltage of 0 on only one phase, or all voltages 0 with current flowing, is a RANGE fault.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass

import numpy as np
import pandas as pd

from analytics.common import make_alert, runs, step_hours, strip_quarantined
from contracts.models import Alert

# ---- values quoted from the spec (DATA_INGESTION_SPEC.md section 2.8, FINAL_PRD section 8.6) ----
JUMP_C_PER_15MIN = 5.0  # spec 2.8: JUMP_OTI / JUMP_WTI rate > 5 C per 15 min, scaled to the interval
TEMP_RANGE_C = (-10.0, 150.0)  # spec 2.8: OTI < -10 or > 150 C (also applied to amb_C)
WTI_RANGE_C = (-10.0, 200.0)  # NOT in spec: a real severe overload can drive the winding hot spot past 150 C, so WTI gets a wider cap
VOLT_RANGE_V = (100.0, 300.0)  # spec 2.8: phase-neutral voltage < 100 or > 300 V
STUCK_MIN_SAMPLES = 8  # spec 2.8: unchanged >= 8 samples ...
STUCK_LOAD_CHANGE = 0.10  # ... while load changes > 10 %
# ---- named defaults NOT in the spec (listed under "Needs decision" in the hand-off) ----
JUMP_MAX_GAP_STEPS = 4  # do not evaluate a step across a gap longer than this many sampling intervals
JUMP_LOAD_STEP = 0.25  # a temperature step that coincides with a relative load step above this is the load, not the sensor
                       # (real winding gradient responds within minutes, so a big load step can legitimately move WTI >5 C/15 min)
JUMP_LOAD_WINDOW_H = 3.0  # ... and for this long afterwards (oil time constant 180 min, as in tests/mock_data TAU_STEPS)
JUMP_LOAD_EXCUSE_MAX_C = 60.0  # but never a step beyond the whole rated top-oil rise (60 K, IEC default): that is not the load
JUMP_MERGE_ROWS = 4  # jump samples closer than this many rows belong to one episode (a spike = up + down)
DEAD_MAX_ABS = 1.0  # dead channel: |value| never above this (real Kaggle WTI is a 0/1 flag, max 1.0)
DEAD_MIN_HOURS = 24.0  # need this much online data before declaring a channel dead
DEAD_REF_VARIATION_C = 5.0  # another temperature channel must span at least this much ("others vary")
SEVERITY = {"jump_sensor": "warning", "range_sensor": "critical", "stuck_sensor": "warning", "dead_channel": "warning"}

TEMP_CHANNELS = ("OTI_C", "WTI_C", "amb_C")
JUMP_CHANNELS = ("OTI_C", "WTI_C")
VOLT_CHANNELS = ("VR", "VY", "VB")
CURR_CHANNELS = ("IR", "IY", "IB", "I_mean")
STUCK_CHANNELS = ("OTI_C", "WTI_C", "VR", "VY", "VB")
LIVENESS = ("IR", "IY", "IB", "VR", "VY", "VB", "OTI_C", "amb_C")

# Which asset alert types read which channels (used to relabel sensor-caused asset alerts).
ALERT_CHANNELS: dict[str, tuple[str, ...]] = {
    "top_oil_high": ("OTI_C",),
    "hot_spot_high": ("WTI_C",),
    "loading_high": CURR_CHANNELS,
    "overcurrent": CURR_CHANNELS,
    "current_unbalance": CURR_CHANNELS,
    "voltage_unbalance": VOLT_CHANNELS,
    "voltage_high": VOLT_CHANNELS,
    "voltage_low": VOLT_CHANNELS,
    "oil_low": ("OLI_pct",),
    "oil_leak": ("OLI_pct",),
    "oil_theft": ("OLI_pct",),
}
RELABEL_NOTE = " (likely sensor/data fault, not an asset fault)"


@dataclass
class Episode:
    type: str
    channel: str
    start: int  # row index of first flagged sample
    end: int  # row index of last flagged sample
    start_ts: pd.Timestamp
    end_ts: pd.Timestamp
    alert: Alert
    emitted: bool = True  # False: absorbed into a RANGE/STUCK alert, kept only so relabel() sees its span


def _num(df: pd.DataFrame, name: str) -> pd.Series | None:
    if name not in df.columns:
        return None
    s = pd.to_numeric(df[name], errors="coerce")
    return None if s.isna().all() else s


def _merge(rs: list[tuple[int, int]], gap: int) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for s, e in rs:
        if out and s - out[-1][1] - 1 <= gap:
            out[-1] = (out[-1][0], e)
        else:
            out.append((s, e))
    return out


def _all_zero_mask(df: pd.DataFrame, names: tuple[str, ...]) -> np.ndarray:
    cols = [_num(df, c) for c in names]
    cols = [s.to_numpy() for s in cols if s is not None]
    if not cols:
        return np.zeros(len(df), dtype=bool)
    arr = np.vstack(cols)
    return (~np.isnan(arr).all(axis=0)) & (np.nan_to_num(arr, nan=0.0) == 0).all(axis=0)


def _masks(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """(offline, de-energised) boolean row masks. See the module docstring."""
    return _all_zero_mask(df, LIVENESS), _all_zero_mask(df, VOLT_CHANNELS + CURR_CHANNELS[:3])


def _load(df: pd.DataFrame) -> np.ndarray | None:
    s = _num(df, "load_pu")
    if s is None:
        pct = _num(df, "loading_pct")
        s = None if pct is None else pct / 100.0
    if s is None:
        s = _num(df, "I_mean")
    return None if s is None else s.to_numpy()


def _canon_channel(df: pd.DataFrame, code_suffix: str) -> str | None:
    for cand in (code_suffix, code_suffix + "_C", code_suffix + "_pct"):
        if cand in df.columns:
            return cand
    low = {c.lower(): c for c in df.columns}
    return low.get(code_suffix.lower())


class _Builder:
    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.ts = pd.to_datetime(df["timestamp"])
        self.sim = df["simulated"].to_numpy() if "simulated" in df.columns else None
        self.eps: list[Episode] = []

    def add(self, type_: str, channel: str, s: int, e: int, value: float | None, threshold: float | None,
            text: str) -> None:
        ts = self.ts.iloc[s]
        a = make_alert(
            ts, type_, SEVERITY[type_], "physics", value=value, threshold=threshold,
            explanation=f"{text} Check the sensor / data path, not the transformer.",
            origin="sensor", simulated=True if self.sim is None else bool(self.sim[s]),
        )
        a.id = f"{a.id}-{channel}"  # same type + time on two channels must not collide
        self.eps.append(Episode(type_, channel, s, e, ts, self.ts.iloc[e], a))


def _jump(b: _Builder, offline: np.ndarray, h: float) -> None:
    load = _load(b.df)
    dt_h = b.ts.diff().dt.total_seconds().to_numpy() / 3600.0
    for ch in JUMP_CHANNELS:
        v = _num(b.df, ch)
        if v is None:
            continue
        x = v.to_numpy()
        sd = np.diff(x, prepend=np.nan)
        d = np.abs(sd)
        # Trend confirmation (NOT in spec): a steady genuine ramp that grazes the limit (e.g. +3 C then +5.05 C per
        # step in a hard overload) is not a jump; the step must also differ from the previous step by more than the limit.
        d2 = np.abs(sd - np.roll(sd, 1))
        d2 = np.where(np.isnan(d2), d, d2)
        with np.errstate(invalid="ignore"):
            ok = ~np.isnan(d) & ~offline & ~np.roll(offline, 1) & (dt_h > 0) & (dt_h <= JUMP_MAX_GAP_STEPS * h)
        ok[0] = False
        if load is not None:  # a step that a concurrent load step explains is not a sensor fault
            prev = np.roll(load, 1)
            with np.errstate(invalid="ignore", divide="ignore"):
                rel = np.abs(load - prev) / np.maximum(np.maximum(np.abs(load), np.abs(prev)), 1e-9)
            w = max(1, int(round(JUMP_LOAD_WINDOW_H / h)))
            stepped = pd.Series(np.nan_to_num(rel, nan=0.0) > JUMP_LOAD_STEP).astype(float).rolling(w, min_periods=1).max()
            ok &= ~((stepped.to_numpy() > 0) & (d <= JUMP_LOAD_EXCUSE_MAX_C))
        limit = JUMP_C_PER_15MIN * dt_h / 0.25
        mask = np.zeros(len(x), dtype=bool)
        mask[ok] = (d[ok] > limit[ok]) & (d2[ok] > limit[ok])
        for s, e in _merge(runs(mask), JUMP_MERGE_ROWS):
            step = x[s] - x[s - 1]
            b.add("jump_sensor", ch, s, e, step, limit[s],
                  f"{ch} stepped {step:+.1f} C in {dt_h[s] * 60:.0f} min; the limit is {limit[s]:.1f} C "
                  f"({JUMP_C_PER_15MIN:g} C per 15 min), impossible for the oil thermal time constant.")


def _range(b: _Builder, offline: np.ndarray, deen: np.ndarray) -> None:
    table: list[tuple[str, float, float | None, np.ndarray, str]] = []
    for ch in TEMP_CHANNELS:
        lim = WTI_RANGE_C if ch == "WTI_C" else TEMP_RANGE_C
        table.append((ch, lim[0], lim[1], offline, "C"))
    for ch in VOLT_CHANNELS:
        table.append((ch, VOLT_RANGE_V[0], VOLT_RANGE_V[1], offline | deen, "V"))
    for ch in CURR_CHANNELS:
        table.append((ch, 0.0, None, offline, "A"))  # negative current only
    for ch, lo, hi, skip, unit in table:
        v = _num(b.df, ch)
        if v is None:
            continue
        x = v.to_numpy()
        with np.errstate(invalid="ignore"):
            bad = (x < lo) if hi is None else ((x < lo) | (x > hi))
        bad &= ~skip & ~np.isnan(x)
        for s, e in runs(bad):
            seg = x[s : e + 1]
            ext = float(seg[np.argmax(np.abs(seg - (lo if x[s] < lo else hi if hi is not None else lo)))])
            lim = lo if x[s] < lo else hi
            b.add("range_sensor", ch, s, e, float(x[s]) if len(seg) == 1 else ext, lim,
                  f"{ch} read {x[s]:.1f} {unit}, outside the physical range "
                  f"[{lo:g}, {'inf' if hi is None else format(hi, 'g')}] {unit} for {e - s + 1} sample(s).")


def _stuck(b: _Builder, offline: np.ndarray, deen: np.ndarray, dead: set[str]) -> None:
    load = _load(b.df)
    if load is None:
        return  # "while load changes" cannot be evaluated without a load channel
    for ch in STUCK_CHANNELS:
        if ch in dead:
            continue
        v = _num(b.df, ch)
        if v is None:
            continue
        x = v.to_numpy()
        skip = offline | deen if ch in VOLT_CHANNELS else offline
        same = np.zeros(len(x), dtype=bool)  # same[i]: x[i] == x[i-1], both valid
        same[1:] = (x[1:] == x[:-1]) & ~np.isnan(x[1:]) & ~skip[1:] & ~skip[:-1]
        for s, e in runs(same):
            first, last = s - 1, e  # samples first..last all carry the same value
            if last - first + 1 < STUCK_MIN_SAMPLES:
                continue
            seg = load[first : last + 1]
            seg = seg[~np.isnan(seg)]
            if len(seg) < 2 or np.mean(seg) == 0:
                continue
            change = float((seg.max() - seg.min()) / abs(np.mean(seg)))
            if change > STUCK_LOAD_CHANGE:
                b.add("stuck_sensor", ch, first, last, float(x[first]), STUCK_LOAD_CHANGE,
                      f"{ch} stayed at {x[first]:.2f} for {last - first + 1} samples while load changed "
                      f"{change * 100:.0f} % (limit: >= {STUCK_MIN_SAMPLES} samples and > {STUCK_LOAD_CHANGE * 100:.0f} %).")


def _dead(b: _Builder, offline: np.ndarray, h: float) -> set[str]:
    dead: set[str] = set()
    temps = {c: _num(b.df, c) for c in TEMP_CHANNELS}
    temps = {c: s.to_numpy() for c, s in temps.items() if s is not None}
    for ch, x in temps.items():
        valid = ~np.isnan(x) & ~offline
        if valid.sum() * h < DEAD_MIN_HOURS or np.max(np.abs(x[valid])) > DEAD_MAX_ABS:
            continue
        varies = False
        for c, o in temps.items():
            ov = ~np.isnan(o) & ~offline
            if c != ch and ov.any() and np.ptp(o[ov]) >= DEAD_REF_VARIATION_C:
                varies = True
        if not varies:
            continue
        first = int(np.argmax(valid))
        frac0 = float(np.mean(x[valid] == 0))
        dead.add(ch)
        b.add("dead_channel", ch, first, len(x) - 1, float(np.max(np.abs(x[valid]))), DEAD_MAX_ABS,
              f"{ch} never exceeded {DEAD_MAX_ABS:g} over {int(valid.sum())} online samples ({frac0 * 100:.0f} % exactly 0) "
              "while other temperature channels vary: the channel is dead or a status flag, not a temperature.")
    return dead


def _dq(b: _Builder) -> None:
    df = b.df
    if "dq_flags" not in df.columns:
        return
    kinds = {"JUMP": "jump_sensor", "STUCK": "stuck_sensor", "RANGE": "range_sensor", "NEG": "range_sensor"}
    found: dict[tuple[str, str], np.ndarray] = {}
    for i, cell in enumerate(df["dq_flags"].fillna("").astype(str).tolist()):
        for code in (c.strip() for c in cell.split(";") if c.strip()):
            kind, _, col = code.partition("_")
            type_ = kinds.get(kind)
            ch = _canon_channel(df, col) if type_ else None
            if type_ and ch:
                found.setdefault((type_, ch), np.zeros(len(df), dtype=bool))[i] = True
    for (type_, ch), mask in sorted(found.items()):
        covered = np.zeros(len(df), dtype=bool)
        for ep in b.eps:
            if ep.channel == ch and ep.type == type_:
                covered[max(ep.start - 1, 0) : ep.end + 2] = True  # +-1 row: dq may flag either side of a step
        for s, e in _merge(runs(mask & ~covered), JUMP_MERGE_ROWS if type_ == "jump_sensor" else 0):
            val = pd.to_numeric(df[ch], errors="coerce").iloc[s]
            b.add(type_, ch, s, e, None if pd.isna(val) else float(val), None,
                  f"The ingestion layer flagged {type_.split('_')[0].upper()} on {ch} for {e - s + 1} sample(s) (dq_flags).")


def _collapse_jump(eps: list[Episode]) -> list[Episode]:
    """A jump that is just the edge of a RANGE or STUCK episode on the same channel is one event: one alert only
    (the RANGE/STUCK one). The jump episode stays in the list, emitted=False, so relabel() still sees its span."""
    host = [e for e in eps if e.type in ("range_sensor", "stuck_sensor")]
    for e in eps:
        if e.type == "jump_sensor" and any(r.channel == e.channel and r.start - 1 <= e.start and e.end <= r.end + 1 for r in host):
            e.emitted = False
    return eps


def episodes(df: pd.DataFrame, thresholds: dict | None = None, caps: dict | None = None) -> list[Episode]:
    """All sensor-fault episodes with their row span. `thresholds` and `caps` are accepted for contract symmetry;
    the sensor checks use module constants (spec values) and run on whichever channels exist."""
    df = strip_quarantined(df).reset_index(drop=True)
    if len(df) < 2 or "timestamp" not in df.columns:
        return []
    h = step_hours(df)
    if not h > 0:
        return []
    b = _Builder(df)
    offline, deen = _masks(df)
    _jump(b, offline, h)
    _range(b, offline, deen)
    dead = _dead(b, offline, h)
    _stuck(b, offline, deen, dead)
    _dq(b)
    return sorted(_collapse_jump(b.eps), key=lambda e: (e.start_ts, e.type, e.channel))


def detect(df: pd.DataFrame, thresholds: dict | None = None, caps: dict | None = None) -> list[Alert]:
    return alerts_of(episodes(df, thresholds, caps))


def alerts_of(eps: list[Episode]) -> list[Alert]:
    """The alerts to report: one per episode, minus jumps absorbed into a RANGE/STUCK alert."""
    return [e.alert for e in eps if e.emitted]


def relabel(alerts: list[Alert], eps: list[Episode]) -> list[Alert]:
    """Relabel (never delete) asset alerts whose source sample is flagged on the channel they read.

    The alert keeps its id and severity; origin becomes "sensor", the explanation gains RELABEL_NOTE and
    recommendation_id is cleared so recommend.build() assigns the sensor advice. Only rule/oil-detector alerts.
    """
    out = []
    for a in alerts:
        chans = ALERT_CHANNELS.get(a.type)
        if a.origin == "asset" and a.detector == "rule" and chans and any(
            e.channel in chans and e.start_ts <= a.timestamp <= e.end_ts for e in eps
        ):
            a = dataclasses.replace(a, origin="sensor", explanation=a.explanation + RELABEL_NOTE, recommendation_id=None)
        out.append(a)
    return out
