"""Live plant with injectable anomalies (SIMULATED): one tick = one 15-minute sample, produced on demand.

    s = LiveSession()
    s.inject("cooling_fault", severity=1.4)      # the plant changes; the twin does not know
    frame = s.tick()                              # measured row -> TwinEngine.step -> analyze -> frame

The plant is the generator's plant (perturbed library parameters, sensor noise) stepped one sample at a time with the
library's own update functions (twin.thermal.Stepper). Faults go into the PLANT only, exactly as in sim/generator.py;
the twin (nominal parameters) and the analytics see only the resulting measurements, so detection is not told the answer.
The analytics run on a rolling window of the last WINDOW_ROWS samples.
"""
from __future__ import annotations

import json
import threading
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from analytics.common import load_thresholds
from analytics.pipeline import analyze
from contracts.canonical import TZ
from eval import scenarios as sc
from ingest.enrich import read_asset
from sim.generator import _smooth_step, load_config
from twin import profile, thermal
from twin import thermal_profile as profile_mod
from twin.engine import TwinEngine
from twin.engine import load_config as twin_config

ROOT = Path(__file__).resolve().parent.parent
TICK = pd.Timedelta(minutes=15)
WINDOW_ROWS = 672          # 7 days of samples for the analytics
PROFILE_ROWS = 300         # rows the thermal profile needs for its rolling radiator estimate
WARMUP_ROWS = 192          # 2 days run silently before the first frame so the twin and detectors have history
ALERT_WINDOW = pd.Timedelta(hours=24)
SENSORS = {"OTI_C": "Top-oil temperature", "WTI_C": "Winding temperature", "OLI_pct": "Oil level"}
PH = ["IR", "IY", "IB"]


def _p(key, label, lo, hi, step, default, unit=""):
    return {"key": key, "label": label, "min": lo, "max": hi, "step": step, "default": default, "unit": unit}


# kind -> UI description. oneshot = acts once and finishes; everything else stays until cleared.
CATALOGUE: dict[str, dict] = {
    "overload": {"label": "Overload", "group": "Load", "oneshot": False,
                 "desc": "Load climbs to the chosen level and stays there.",
                 "params": [_p("level_pu", "Load", 1.05, 1.4, 0.01, 1.2, "pu")]},
    "heatwave": {"label": "Heatwave", "group": "Load", "oneshot": False,
                 "desc": "Ambient temperature rises over about an hour. A real stress the twin predicts, so it usually raises no fault alert.",
                 "params": [_p("delta_C", "Ambient rise", 3, 20, 0.5, 10, "°C")]},
    "cooling_fault": {"label": "Cooling fault", "group": "Thermal", "oneshot": False,
                      "desc": "Radiators lose effectiveness over a day and a half. The twin still expects normal cooling.",
                      "params": [_p("severity", "Oil temperature rise vs normal", 1.1, 1.8, 0.05, 1.4, "x")]},
    "phase_unbalance": {"label": "Phase unbalance", "group": "Electrical", "oneshot": False,
                        "desc": "One phase draws more, another less.",
                        "params": [_p("up_frac", "Extra on R phase", 0.05, 0.4, 0.01, 0.15, ""),
                                   _p("down_frac", "Less on Y phase", 0.0, 0.3, 0.01, 0.08, "")]},
    "voltage_sag": {"label": "Voltage sag", "group": "Electrical", "oneshot": False,
                    "desc": "Supply voltage drops.",
                    "params": [_p("factor", "Voltage", 0.8, 0.98, 0.01, 0.9, "x")]},
    "voltage_high": {"label": "Voltage high", "group": "Electrical", "oneshot": False,
                     "desc": "Supply voltage rises.",
                     "params": [_p("factor", "Voltage", 1.02, 1.2, 0.01, 1.1, "x")]},
    "through_fault": {"label": "Through-fault", "group": "Electrical", "oneshot": True,
                      "desc": "A short-circuit current passes through (one event).",
                      "params": [_p("peak_pu", "Peak current", 2, 12, 0.5, 8, "pu"),
                                 _p("duration_ms", "Duration", 100, 1000, 50, 400, "ms")]},
    "oil_leak": {"label": "Oil leak", "group": "Oil", "oneshot": False,
                 "desc": "Oil level falls steadily until you clear it or refill.",
                 "params": [_p("days", "Time to lose the amount", 0.5, 5, 0.25, 1.5, "days"),
                            _p("drop_pct", "Amount", 5, 40, 1, 20, "%")]},
    "oil_theft": {"label": "Oil theft", "group": "Oil", "oneshot": True,
                  "desc": "Oil level drops suddenly.",
                  "params": [_p("step_pct", "Drop", 5, 30, 1, 12, "%")]},
    "sensor_stuck": {"label": "Sensor stuck", "group": "Sensor", "oneshot": False,
                     "desc": "A sensor freezes at its current reading.",
                     "params": [], "channel": True},
    "sensor_dead": {"label": "Sensor dead", "group": "Sensor", "oneshot": False,
                    "desc": "A sensor stops working and reads zero.",
                    "params": [], "channel": True},
    "sensor_jump": {"label": "Sensor jump", "group": "Sensor", "oneshot": False,
                    "desc": "A sensor reading steps by a fixed amount.",
                    "params": [_p("offset", "Offset", 5, 40, 1, 15, "units")], "channel": True},
    "sensor_drift": {"label": "Sensor drift", "group": "Sensor", "oneshot": False,
                     "desc": "A sensor reading creeps away from the truth.",
                     "params": [_p("per_hour", "Drift per hour", 0.2, 3, 0.1, 1.0, "units/h")], "channel": True},
}
for k in ("sensor_stuck", "sensor_dead", "sensor_jump", "sensor_drift"):
    CATALOGUE[k]["channels"] = SENSORS


@dataclass
class Injection:
    id: int
    kind: str
    params: dict
    start_tick: int
    state: dict = field(default_factory=dict)

    def info(self, tick: int) -> dict:
        return {"id": self.id, "kind": self.kind, "label": CATALOGUE[self.kind]["label"], "params": self.params,
                "since_h": round((tick - self.start_tick) * TICK.total_seconds() / 3600, 2)}


class LiveSession:
    def __init__(self, seed: int = 0, start: str = "2026-04-01 06:00", warmup: int = WARMUP_ROWS, asset: dict | None = None):
        """asset: any transformer profile (twin/profile.py); default is Transformer-1 (config/asset.yaml)."""
        self.lock = threading.RLock()
        self.cfg = load_config()
        self.asset = profile.complete(asset if asset is not None else read_asset(ROOT / "config" / "asset.yaml"))
        self.i_rated = float(self.asset["i_rated_A"])
        self.seed = seed
        self.rng = np.random.default_rng(seed)
        meta = ROOT / "data" / "generated" / "meta_N.json"
        if asset is None and meta.exists():       # Transformer-1: the same plant the shipped Normal data was measured on
            plant = json.loads(meta.read_text(encoding="utf-8"))["plant"]
            self.rise_mult, self.hsf = float(plant["top_oil_rise_mult"]), float(plant["hot_spot_fac"])
        else:                                     # any other asset: draw the plant like sim/generator.py does
            P = self.cfg["plant"]
            self.rise_mult = float(self.rng.uniform(*P["top_oil_rise_mult"]))
            self.hsf = float(self.rng.uniform(*P["hot_spot_fac"]) * self.asset["hot_spot_factor"] / 1.2)
        self.start = pd.Timestamp(start, tz=TZ)
        self.th = load_thresholds(asset=self.asset)
        self.caps = sc.capabilities("N")
        self.ref = sc.normal_reference(self.th)
        self.bottom_ratio = float(twin_config()["bottom_oil_ratio"])
        self._build(warmup)

    # ---------------------------------------------------------------- construction
    def _tr(self, rise_mult: float):
        a = self.asset
        kw = profile.thermal_kwargs(a)             # the asset's own rise, time constants, gradient, exponents
        kw["top_oil_temp_rise"] = a.get("top_oil_rise_K", 60.0) * rise_mult
        kw["hot_spot_fac"] = self.hsf
        return thermal.make_transformer(self.i_rated, a["load_loss_W"], a["no_load_loss_W"], **kw)

    def _build(self, warmup: int):
        L, P = self.cfg["load"], self.cfg["plant"]
        self.L, self.P = L, P
        self.engine = TwinEngine(self.asset)
        self.plant = thermal.Stepper(self._tr(self.rise_mult))
        self.deg = None                          # degraded-cooling stepper, created by a cooling fault
        self.cf_w = 0.0
        self.static = self.rng.uniform(-L["phase_imbalance"], L["phase_imbalance"], 3)
        self.static -= self.static.mean()
        self.v_offset = self.rng.uniform(-0.003, 0.003, 3)
        self.ar = 0.0
        self.peak, self.peak_day = 0.6, None
        self.oli_delta = 0.0
        self.injections: list[Injection] = []
        self._next_id = 1
        self.n = 0                               # samples produced
        self.rows: deque[dict] = deque(maxlen=WINDOW_ROWS)
        self.events: list[dict] = []
        self.last: dict | None = None
        self._plant_ready = False
        for _ in range(warmup):
            self._sample()
        self.warm = self.n

    # ---------------------------------------------------------------- injections
    def inject(self, kind: str, **params) -> dict:
        if kind not in CATALOGUE:
            raise ValueError(f"unknown injection {kind!r}; known: {sorted(CATALOGUE)}")
        spec = CATALOGUE[kind]
        clean = {}
        for p in spec["params"]:
            v = float(params.get(p["key"], p["default"]))
            if not p["min"] <= v <= p["max"]:
                raise ValueError(f"{p['key']} must be within {p['min']}..{p['max']}")
            clean[p["key"]] = v
        if spec.get("channel"):
            ch = params.get("channel")
            if ch not in SENSORS:
                raise ValueError(f"channel must be one of {sorted(SENSORS)}")
            clean["channel"] = ch
        with self.lock:
            if not spec["oneshot"]:                      # a second injection of the same kind replaces the first
                self.injections = [i for i in self.injections
                                   if not (i.kind == kind and i.params.get("channel") == clean.get("channel"))]
            inj = Injection(self._next_id, kind, clean, self.n)
            self._next_id += 1
            if kind == "cooling_fault":
                self.deg = thermal.Stepper(self._tr(self.rise_mult * clean["severity"]))
                self.deg.top, self.deg.hs_w, self.deg.hs_o = self.plant.top, self.plant.hs_w, self.plant.hs_o
            self.injections.append(inj)
            return inj.info(self.n)

    def clear(self, injection_id: int | None = None, kind: str | None = None) -> int:
        """Remove injections (all, one by id, or all of a kind). Returns how many were removed."""
        with self.lock:
            keep = [i for i in self.injections if not (
                (injection_id is None and kind is None) or i.id == injection_id or (kind is not None and i.kind == kind))]
            removed = len(self.injections) - len(keep)
            self.injections = keep
            return removed

    def refill_oil(self):
        with self.lock:
            self.oli_delta = 0.0
            self.injections = [i for i in self.injections if i.kind != "oil_leak"]

    def active(self) -> list[dict]:
        with self.lock:
            return [i.info(self.n) for i in self.injections]

    def _get(self, kind):
        for i in self.injections:
            if i.kind == kind:
                return i
        return None

    @staticmethod
    def _ramp(elapsed_h: float, full_h: float) -> float:
        return float(min(1.0, max(0.0, elapsed_h / full_h)))

    # ---------------------------------------------------------------- one sample
    def _sample(self) -> dict:
        """Advance the plant one tick and run the twin on the measurement. Returns the (measured + twin) row."""
        L, P = self.L, self.P
        ts = self.start + TICK * self.n
        hour = ts.hour + ts.minute / 60
        el = lambda inj: (self.n - inj.start_tick) * TICK.total_seconds() / 3600   # noqa: E731

        # ---- base ambient and load (generator's load shape, one sample at a time)
        amb = 27 + 5 * np.sin(2 * np.pi * (hour - 9) / 24) + self.rng.normal(0, 0.15)
        heat = self._get("heatwave")
        if heat:
            amb += heat.params["delta_C"] * self._ramp(el(heat), 1.0)
        if self.peak_day != ts.date():
            self.peak_day = ts.date()
            lo, hi = L["weekday_peak_pu"] if ts.dayofweek < 5 else L["weekend_peak_pu"]
            self.peak = float(self.rng.uniform(lo, hi))
        self.ar = 0.8 * self.ar + self.rng.normal(0, L["noise_pu"]) * np.sqrt(1 - 0.8 ** 2)
        pu = (L["night_pu"] + (self.peak - L["night_pu"]) * _smooth_step(hour, *L["day_hours"])
              + L["evening_bump_pu"] * _smooth_step(hour, 19, 23)
              + L["ambient_coupling_pu_per_C"] * max(amb - 28, 0) + self.ar)
        pu = max(pu, 0.1)
        ov = self._get("overload")
        if ov:
            pu += self._ramp(el(ov), 0.25) * max(ov.params["level_pu"] - pu, 0)

        phase_mult = np.ones(3)
        ub = self._get("phase_unbalance")
        if ub:
            w = self._ramp(el(ub), 0.25)
            phase_mult[0] += w * ub.params["up_frac"]
            phase_mult[1] -= w * ub.params["down_frac"]
        vmult = 1.0
        for k in ("voltage_sag", "voltage_high"):
            v = self._get(k)
            if v:
                vmult *= 1 + self._ramp(el(v), 0.25) * (v.params["factor"] - 1)

        i_true = pu * self.i_rated * (1 + self.static) * phase_mult * (1 + self.rng.normal(0, L["phase_noise"], 3))
        i_mean_true = float(i_true.mean())

        # ---- thermal plant (library stepped one sample; degraded cooling blended in like S2)
        if not self._plant_ready:
            self.plant.reset(i_mean_true, amb)
            self._plant_ready = True
            oil, hs = float(self.plant.top), float(self.plant.top + self.plant.hs_w - self.plant.hs_o)
        else:
            oil, hs = self.plant.step(i_mean_true, amb, TICK.total_seconds() / 60)
        cf = self._get("cooling_fault")
        if self.deg is not None:
            d_oil, d_hs = self.deg.step(i_mean_true, amb, TICK.total_seconds() / 60)
            target = self._ramp(el(cf), 36.0) if cf else 0.0
            # fault builds over 36 h; once cleared it fades over 6 h (the degraded state relaxes, it does not snap)
            self.cf_w = target if cf else max(0.0, self.cf_w - 1 / 24)
            oil, hs = oil + self.cf_w * (d_oil - oil), hs + self.cf_w * (d_hs - hs)
            if not cf and self.cf_w <= 0.0:
                self.deg = None

        # ---- oil level: thermal expansion plus the leak / theft that happened to the plant
        lk = self._get("oil_leak")
        if lk:
            self.oli_delta -= lk.params["drop_pct"] / (lk.params["days"] * 96)
        th = self._get("oil_theft")
        if th:
            if "left" not in th.state:
                th.state["left"] = 2
            self.oli_delta -= th.params["step_pct"] / 2
            th.state["left"] -= 1
            if th.state["left"] <= 0:
                self.injections.remove(th)

        # ---- measurements
        noise_i = self.rng.normal(0, P["noise_vi_frac"], 3)
        noise_v = self.rng.normal(0, P["noise_vi_frac"], 3)
        meas_i = i_true * (1 + noise_i)
        v_ln = float(self.asset["lv_voltage_V"]) / np.sqrt(3) * (1.005 - 0.01 * pu) * (1 + self.v_offset) * (1 + noise_v) * vmult
        ang = np.deg2rad([0, -120, 120])
        i_n = float(np.abs((meas_i * np.exp(1j * ang)).sum()))
        s_kva = float((v_ln * meas_i).sum() / 1000)
        pf = float(np.clip(0.93 + 0.03 * pu + self.rng.normal(0, 0.005), 0.8, 0.99))
        nt = P["noise_temp_C"]
        oli = float(np.clip(P["oil_level_base_pct"] + P["oil_level_per_C"] * (oil - 50) + self.rng.normal(0, 0.3) + self.oli_delta, 0, 100))
        ati = float(amb + self.rng.normal(0, 0.3))
        row = {
            "timestamp": ts, "IR": meas_i[0], "IY": meas_i[1], "IB": meas_i[2], "I_mean": float(meas_i.mean()), "IN": i_n,
            "VR": v_ln[0], "VY": v_ln[1], "VB": v_ln[2], "S_kVA": s_kva, "P_kW": s_kva * pf,
            "Q_kVAr": s_kva * float(np.sqrt(1 - pf ** 2)), "PF": pf, "freq_Hz": 50 + self.rng.normal(0, 0.03),
            "loading_pct": float(meas_i.mean()) / self.i_rated * 100,
            "OTI_C": oil + self.rng.normal(0, nt), "WTI_C": hs + self.rng.normal(0, nt), "ATI_C": ati, "OLI_pct": oli,
            "amb_C": ati, "dq_flags": "", "source": "live_sim", "simulated": True,
        }
        # sensor faults act on the reading only (the plant is fine)
        for inj in self.injections:
            if not inj.kind.startswith("sensor_"):
                continue
            ch = inj.params["channel"]
            if inj.kind == "sensor_stuck":
                inj.state.setdefault("held", row[ch])
                row[ch] = inj.state["held"]
            elif inj.kind == "sensor_dead":
                row[ch] = 0.0                       # a dead transmitter reads zero
            elif inj.kind == "sensor_jump":
                row[ch] = row[ch] + inj.params["offset"]
            elif inj.kind == "sensor_drift":
                row[ch] = row[ch] + inj.params["per_hour"] * el(inj)
        # one-shot through-fault: an event row (the 15-minute trend cannot see it)
        tf = self._get("through_fault")
        new_events = []
        if tf:
            pk, ms = tf.params["peak_pu"], tf.params["duration_ms"]
            new_events.append({"timestamp": ts + pd.Timedelta(seconds=int(self.rng.integers(30, 800))),
                               "event_type": "through_fault", "phase": "3ph", "peak_pu": pk, "duration_ms": ms,
                               "i2t_pu2s": pk ** 2 * ms / 1000, "source": "live_sim", "simulated": True})
            self.injections.remove(tf)

        state = self.engine.step(row)
        full = {**state.row, **state.twin, "timestamp": ts}
        self.rows.append(full)
        self.events.extend(new_events)
        self.n += 1
        return full

    # ---------------------------------------------------------------- one frame for the UI
    def tick(self) -> dict:
        """Advance one sample and return {frame, alerts, injections, health} (JSON-safe via server.serialize.plain)."""
        with self.lock:
            self._sample()
            df = pd.DataFrame(list(self.rows))
            ev = pd.DataFrame(self.events) if self.events else pd.DataFrame()
            ts = df["timestamp"].iloc[-1]
            res = analyze(df, ev, self.caps, self.th, self.ref)
            prof = profile_mod.compute(df.tail(PROFILE_ROWS).reset_index(drop=True), self.asset, self.bottom_ratio).iloc[-1]
            frame = dict(df.iloc[-1].to_dict())
            frame.update({c: prof[c] for c in profile_mod.COLUMNS if c in prof})
            h = res.health
            frame.update(health_score=h.score, health_band=h.band, health_capped=h.capped,
                         **{f"health_{k}": v for k, v in h.components.items()})
            alerts = [a for a in res.alerts if ts - ALERT_WINDOW < a.timestamp <= ts]
            self.last = {"tick": self.n, "frame": frame, "alerts": alerts, "injections": self.active(), "simulated": True}
            return self.last

    def params(self) -> dict:
        return profile_mod.params(profile_mod.specs_for(self.asset), self.bottom_ratio)
