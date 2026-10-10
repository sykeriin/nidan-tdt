"""Twin engine (FINAL_PRD.md §7, §12.2): nominal Transformer-1 twin alongside the measured data.

    TwinEngine(asset).run(ds)      batch over a Dataset / canonical trend
    TwinEngine(asset).step(row)    streaming, one canonical row at a time; identical numbers to run()

Per timestep (§7.2): twin_oil_C, twin_hs_C, aging_rate, days_aged_cum, residual_oil_C (= OTI − twin, NaN in
meter-only), fidelity_rmse_C (rolling 24 h), load_pu; plus twin_restart, fidelity_alert and the physics
plausibility band (rise_low_K / rise_high_K, implausible_rise; PRD §7.4).

Two ageing figures (IEC 60076-7 practice: hot-spot = measured top-oil + winding gradient when top-oil is trustworthy):
  expected (aging_rate, days_aged_cum): twin hot-spot = healthy cooling.
  actual (aging_rate_actual, days_aged_actual_cum): measured OTI + twin gradient (twin_hs - twin_oil), per row, only
  where the OTI channel has passed the plausibility check so far (causal, after a warm-up), the row has no sensor-fault
  flag and is not below the physics band (a rise above it may be a real asset fault, e.g. cooling, so it is kept);
  otherwise the twin hot-spot (see ageing_source).
The gap actual - expected is the life a fault cost. RUL uses actual ageing.
Twin parameters are nominal (asset.yaml + library defaults); the generator's plant is deliberately different.
"""
from collections import deque
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from contracts.models import Dataset, TwinState
from ingest.enrich import read_asset
from twin import ageing, plausibility, rul, thermal

ROOT = Path(__file__).resolve().parent.parent
DRIFT_MESSAGE = "model drift — check cooling / recalibrate"
OUT_COLS = ["twin_oil_C", "twin_hs_C", "aging_rate", "days_aged_cum", "residual_oil_C", "fidelity_rmse_C",
            "load_pu", "twin_restart", "fidelity_alert", "dt_min", "rise_low_K", "rise_high_K", "implausible_rise",
            "hs_ageing_C", "ageing_source", "aging_rate_actual", "days_aged_actual_cum"]


def load_config(path=ROOT / "config" / "twin.yaml") -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def _band_transformer(i_rated, p):
    return thermal.make_transformer(i_rated, 1000.0 * p["R"], 1000.0, top_oil_temp_rise=p["top_oil_temp_rise"],
                                    amb_temp_surcharge=p["amb_temp_surcharge"])


def life_consumed(res: pd.DataFrame) -> dict:
    """Equivalent days of insulation life used over the period: expected (healthy twin) vs actual (measured)."""
    exp = float(res["days_aged_cum"].iloc[-1]) if len(res) else 0.0
    act = float(res["days_aged_actual_cum"].iloc[-1]) if len(res) else 0.0
    return {"expected": round(exp, 3), "actual": round(act, 3), "actual_minus_expected": round(act - exp, 3),
            "measured_share": round(float((res["ageing_source"] == "measured").mean()), 3) if len(res) else 0.0}


def _bad_temp(flags: str) -> bool:
    return any(f in (flags or "") for f in plausibility.BAD_TEMP_FLAGS)


class TwinEngine:
    def __init__(self, asset: dict | str = "config/asset.yaml", cfg: dict | None = None):
        a = read_asset(ROOT / asset) if isinstance(asset, str) else dict(asset)
        self.asset, self.cfg = a, cfg or load_config()
        self.i_rated = float(a["i_rated_A"])
        self.tr = thermal.make_transformer(self.i_rated, a["load_loss_W"], a["no_load_loss_W"])
        self.bands = {k: _band_transformer(self.i_rated, plausibility.BANDS[k]) for k in ("low", "high")}
        self.insulation = a.get("insulation", "normal")
        self._reset_stream()

    # ---------------- batch ----------------
    def run(self, ds: Dataset | pd.DataFrame) -> pd.DataFrame:
        trend = ds.trend if isinstance(ds, Dataset) else ds
        t = trend.reset_index(drop=True).copy()
        n = len(t)
        has_oti = "OTI_C" in t and t["OTI_C"].notna().any()
        mode = (ds.mode if isinstance(ds, Dataset) else None) or ("full" if has_oti else "meter_only")
        amps = t["I_mean"].to_numpy(float) if "I_mean" in t else np.full(n, np.nan)
        amb = t["amb_C"].to_numpy(float)
        ts = t["timestamp"]
        valid = ~np.isnan(amps) & ~np.isnan(amb)
        out = {c: np.full(n, np.nan) for c in OUT_COLS}
        out["twin_restart"] = np.zeros(n, bool)
        restart_gap = pd.Timedelta(hours=self.cfg["restart_gap_h"])
        vi = np.flatnonzero(valid)
        if len(vi):
            vts = ts.iloc[vi].reset_index(drop=True)
            gaps = vts.diff()
            starts = np.r_[0, np.flatnonzero((gaps > restart_gap).to_numpy())]
            ends = np.r_[starts[1:], len(vi)]
            for s0, s1 in zip(starts, ends):
                rows = vi[s0:s1]
                seg_ts = ts.iloc[rows]
                oil, hs = thermal.run_segment(self.tr, seg_ts, amps[rows], amb[rows])
                out["twin_oil_C"][rows], out["twin_hs_C"][rows] = oil, hs
                for name, tr in self.bands.items():
                    b_oil, _ = thermal.run_segment(tr, seg_ts, amps[rows], amb[rows])
                    out[f"rise_{name}_K"][rows] = b_oil - amb[rows]
                out["twin_restart"][rows[0]] = True
                dt = seg_ts.diff().dt.total_seconds().fillna(0).to_numpy() / 60
                out["dt_min"][rows] = dt
            out["aging_rate"][vi] = ageing.rate(out["twin_hs_C"][vi], self.insulation)
            inc = np.where(valid, np.nan_to_num(out["aging_rate"]) * np.nan_to_num(out["dt_min"]) / 1440, 0.0)
            out["days_aged_cum"] = np.cumsum(inc)
        else:
            out["days_aged_cum"] = np.zeros(n)
        out["load_pu"] = amps / self.i_rated
        oti = t["OTI_C"].to_numpy(float) if has_oti and mode != "meter_only" else np.full(n, np.nan)
        out["residual_oil_C"] = oti - out["twin_oil_C"]
        win = f"{self.cfg['fidelity_window_h']}h"
        sq = pd.Series(out["residual_oil_C"] ** 2, index=pd.DatetimeIndex(ts))
        out["fidelity_rmse_C"] = np.sqrt(sq.rolling(win, min_periods=self.cfg["fidelity_min_samples"]).mean().to_numpy())
        out["fidelity_alert"] = np.nan_to_num(out["fidelity_rmse_C"]) > self.cfg["fidelity_alert_C"]
        flags = t["dq_flags"].fillna("") if "dq_flags" in t else pd.Series("", index=t.index)
        rise = oti - amb
        ok = ~np.isnan(rise) & ~np.isnan(out["rise_low_K"]) & ~flags.map(_bad_temp).to_numpy()
        tol = plausibility.TOL_K
        out["implausible_rise"] = ok & ((rise < out["rise_low_K"] - tol) | (rise > out["rise_high_K"] + tol))
        n_ev, n_bad = np.cumsum(ok), np.cumsum(out["implausible_rise"])
        channel_ok = (n_ev >= self.cfg["plausibility_warmup_rows"]) & (n_bad <= plausibility.SUSPECT_FRACTION * n_ev)
        use = ok & ~(rise < out["rise_low_K"] - tol) & channel_ok   # below band = impossible = sensor; above = maybe asset fault
        out["hs_ageing_C"] = np.where(use, oti + out["twin_hs_C"] - out["twin_oil_C"], out["twin_hs_C"])
        out["ageing_source"] = np.where(use, "measured", np.where(valid, "twin", ""))
        out["aging_rate_actual"] = np.full(n, np.nan)
        if len(vi):
            out["aging_rate_actual"][vi] = ageing.rate(out["hs_ageing_C"][vi], self.insulation)
        out["days_aged_actual_cum"] = np.cumsum(
            np.where(valid, np.nan_to_num(out["aging_rate_actual"]) * np.nan_to_num(out["dt_min"]) / 1440, 0.0))
        res = pd.concat([t, pd.DataFrame(out)], axis=1)
        res.attrs.update(self._summary(res, mode, ok))
        return res

    def _summary(self, res: pd.DataFrame, mode: str, evaluable) -> dict:
        n_ev = int(np.sum(evaluable))
        frac = float(res["implausible_rise"][evaluable].mean()) if n_ev else np.nan
        verdict = ("not checked" if not n_ev else "suspect" if frac > plausibility.SUSPECT_FRACTION else "plausible")
        r = rul.estimate(res, self.asset.get("years_in_service", 0), self.cfg)
        drift = bool(res["fidelity_alert"].any())
        return {"mode": mode, "rul": r, "rul_display": rul.display(r, self.cfg),
                "life_consumed_days": life_consumed(res), "plausibility": {"OTI_C": verdict, "implausible_fraction": frac,
                                                          "evaluable_rows": n_ev},
                "fidelity_rmse_C_last": float(res["fidelity_rmse_C"].dropna().iloc[-1]) if res["fidelity_rmse_C"].notna().any() else None,
                "drift_message": DRIFT_MESSAGE if drift else None,
                "first_drift_alert": res.loc[res["fidelity_alert"], "timestamp"].min() if drift else None}

    # ---------------- streaming ----------------
    def _reset_stream(self):
        self._st = thermal.Stepper(self.tr)
        self._band_st = {k: thermal.Stepper(tr) for k, tr in self.bands.items()}
        self._last_valid_ts = None
        self._cum = 0.0
        self._cum_act = 0.0
        self._sq = deque()           # (ts, residual²) inside the fidelity window
        self._hist = []              # rows for RUL
        self._ev = [0, 0]            # evaluable, implausible (plausibility verdict)

    def step(self, row: dict, mode: str | None = None) -> TwinState:
        ts = pd.Timestamp(row["timestamp"])
        amps, amb = row.get("I_mean", np.nan), row.get("amb_C", np.nan)
        amps = np.nan if amps is None else float(amps)
        amb = np.nan if amb is None else float(amb)
        oti = row.get("OTI_C", np.nan)
        oti = np.nan if oti is None or mode == "meter_only" else float(oti)
        mode = mode or ("full" if not np.isnan(oti) else "meter_only")
        tw = {c: np.nan for c in OUT_COLS}
        tw.update(twin_restart=False, fidelity_alert=False, implausible_rise=False, ageing_source="")
        if not (np.isnan(amps) or np.isnan(amb)):
            gap = None if self._last_valid_ts is None else ts - self._last_valid_ts
            if gap is None or gap > pd.Timedelta(hours=self.cfg["restart_gap_h"]):
                oil, hs = self._st.reset(amps, amb)
                bands = {k: st.reset(amps, amb)[0] for k, st in self._band_st.items()}
                dt, tw["twin_restart"] = 0.0, True
            else:
                dt = gap.total_seconds() / 60
                oil, hs = self._st.step(amps, amb, dt)
                bands = {k: st.step(amps, amb, dt)[0] for k, st in self._band_st.items()}
            self._last_valid_ts = ts
            rate = float(ageing.rate(hs, self.insulation)[0])
            self._cum += rate * dt / 1440
            tw.update(twin_oil_C=oil, twin_hs_C=hs, aging_rate=rate, dt_min=dt,
                      rise_low_K=bands["low"] - amb, rise_high_K=bands["high"] - amb)
            rise = oti - amb
            if not np.isnan(rise) and not _bad_temp(row.get("dq_flags", "")):
                tol = plausibility.TOL_K
                tw["implausible_rise"] = bool(rise < tw["rise_low_K"] - tol or rise > tw["rise_high_K"] + tol)
                self._ev[0] += 1
                self._ev[1] += tw["implausible_rise"]
                channel_ok = (self._ev[0] >= self.cfg["plausibility_warmup_rows"]
                              and self._ev[1] <= plausibility.SUSPECT_FRACTION * self._ev[0])
                use = channel_ok and not rise < tw["rise_low_K"] - tol   # only below-band rows fall back
            else:
                use = False
            tw["hs_ageing_C"] = oti + hs - oil if use else hs
            tw["ageing_source"] = "measured" if use else "twin"
            tw["aging_rate_actual"] = float(ageing.rate(tw["hs_ageing_C"], self.insulation)[0])
            self._cum_act += tw["aging_rate_actual"] * dt / 1440
        tw["days_aged_cum"] = self._cum
        tw["days_aged_actual_cum"] = self._cum_act
        tw["load_pu"] = amps / self.i_rated
        tw["residual_oil_C"] = oti - tw["twin_oil_C"]
        win = pd.Timedelta(hours=self.cfg["fidelity_window_h"])
        if not np.isnan(tw["residual_oil_C"]):
            self._sq.append((ts, tw["residual_oil_C"] ** 2))
        while self._sq and self._sq[0][0] <= ts - win:
            self._sq.popleft()
        if len(self._sq) >= self.cfg["fidelity_min_samples"]:
            tw["fidelity_rmse_C"] = float(np.sqrt(np.mean([v for _, v in self._sq])))
        tw["fidelity_alert"] = bool(np.nan_to_num(tw["fidelity_rmse_C"]) > self.cfg["fidelity_alert_C"])
        if tw["fidelity_alert"]:
            tw["drift_message"] = DRIFT_MESSAGE
        self._hist.append({"timestamp": ts, "aging_rate_actual": tw["aging_rate_actual"], "dt_min": tw["dt_min"],
                           "days_aged_actual_cum": tw["days_aged_actual_cum"]})
        return TwinState(timestamp=ts, row=row, twin=tw, mode=mode)

    def current_rul(self):
        return rul.estimate(pd.DataFrame(self._hist), self.asset.get("years_in_service", 0), self.cfg)

    def plausibility_verdict(self) -> str:
        n, bad = self._ev
        return "not checked" if not n else "suspect" if bad / n > plausibility.SUSPECT_FRACTION else "plausible"
