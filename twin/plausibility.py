"""Physics plausibility check of the temperature channels (replaces the PRD §7.4 fitted twin).

Question: can the measured OTI - ambient rise come from ANY plausible oil-immersed ONAN distribution
transformer carrying this load? IEC 60076-7 (via the library) gives a band over a plausible parameter range.
Rows below/above the band -> IMPLAUSIBLE_RISE. Ambient is checked separately against Open-Meteo -> ATI_MISMATCH.

Works on any canonical trend with OTI_C, I_mean and an ambient (ATI_C or amb_C).
"""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from transformer_thermal_model.model import Model
from transformer_thermal_model.schemas import InputProfile, UserTransformerSpecifications
from transformer_thermal_model.schemas.thermal_model.initial_state import InitialLoad
from transformer_thermal_model.transformer import DistributionTransformer

from ingest.enrich import ati_mismatch, weather_at

# Plausible ONAN distribution-transformer envelope. x = 0.8 (IEC ONAN distribution) throughout.
#   low : coolest plausible unit - rated top-oil rise 30 K (below IS 1180-1:2014's 35 K limit [To verify]),
#         efficient core (load/no-load loss ratio R = 10), outdoor (no enclosure surcharge)
#   high: library defaults (60 K, +10 K kiosk surcharge) with a lossy core (R = 4)
BANDS = {
    "low": {"top_oil_temp_rise": 30.0, "R": 10.0, "amb_temp_surcharge": 0.0},
    "nominal": {"top_oil_temp_rise": 60.0, "R": 10000 / 1100, "amb_temp_surcharge": 10.0},
    "high": {"top_oil_temp_rise": 60.0, "R": 4.0, "amb_temp_surcharge": 10.0},
}
TOL_K = 2.0               # combined OTI + ATI sensor accuracy
SUSPECT_FRACTION = 0.5    # channel verdict: suspect if > 50 % of evaluable rows fall outside the band
MAX_FILL = 4              # interpolate load/ambient over <= 4 missing samples; longer -> new segment
BAD_TEMP_FLAGS = ("RANGE_OTI_C", "RANGE_ATI_C", "JUMP_OTI", "STUCK_OTI")


@dataclass
class PlausibilityResult:
    rows: pd.DataFrame                       # timestamp, load_pu, observed_rise, pred_low/nominal/high, implausible
    verdict: dict[str, str]                  # channel -> plausible | suspect | not checked
    summary: dict = field(default_factory=dict)


def steady_rise(load_pu, top_oil_temp_rise, R, amb_temp_surcharge, x=0.8):
    """IEC 60076-7 steady-state top-oil rise over ambient (incl. enclosure surcharge)."""
    k = np.asarray(load_pu, dtype=float)
    return top_oil_temp_rise * ((1 + R * k ** 2) / (1 + R)) ** x + amb_temp_surcharge


def _segments(ts: pd.Series, ok: pd.Series, gap=pd.Timedelta("1h")) -> list[np.ndarray]:
    idx = np.flatnonzero(ok.to_numpy())
    if len(idx) == 0:
        return []
    t = ts.to_numpy()[idx]
    breaks = np.flatnonzero(np.diff(t) > np.timedelta64(int(gap.total_seconds()), "s")) + 1
    return [s for s in np.split(idx, breaks) if len(s) >= 8]


def _run(amps, amb, ts, i_rated, p) -> np.ndarray:
    no_load = 1000.0
    specs = UserTransformerSpecifications(
        load_loss=no_load * p["R"], no_load_loss=no_load, nom_load_sec_side=i_rated,
        top_oil_temp_rise=p["top_oil_temp_rise"], amb_temp_surcharge=p["amb_temp_surcharge"])
    prof = InputProfile.create(datetime_index=pd.DatetimeIndex(ts).tz_localize(None), load_profile=amps,
                               ambient_temperature_profile=amb)
    out = Model(temperature_profile=prof, transformer=DistributionTransformer(user_specs=specs),
                initial_condition=InitialLoad(initial_load=float(amps[0]))).run()
    return out.convert_to_dataframe()["top_oil_temperature"].to_numpy()


def check(trend: pd.DataFrame, i_rated_A: float, weather: pd.DataFrame | None = None,
          bands=BANDS, tol_K=TOL_K) -> PlausibilityResult:
    t = trend.reset_index(drop=True)
    amb_col = "ATI_C" if "ATI_C" in t and t["ATI_C"].notna().any() else "amb_C"
    rows = pd.DataFrame({"timestamp": t["timestamp"], "load_pu": t.get("I_mean", np.nan) / i_rated_A})
    verdict = {"OTI_C": "not checked", "ATI_C": "not checked"}
    summary = {"i_rated_A": i_rated_A, "ambient_used": amb_col, "tol_K": tol_K,
               "bands": {k: dict(v) for k, v in bands.items()}}

    # ---- top-oil rise vs IEC band ----
    if "OTI_C" in t and t["OTI_C"].notna().any() and "I_mean" in t:
        flags = t.get("dq_flags", pd.Series("", index=t.index)).fillna("")
        bad = flags.str.contains("|".join(BAD_TEMP_FLAGS))
        amps = t["I_mean"].interpolate(limit=MAX_FILL, limit_area="inside")
        amb = t[amb_col].where(~flags.str.contains("RANGE_ATI_C")).interpolate(limit=MAX_FILL, limit_area="inside")
        if amb_col == "ATI_C" and "amb_C" in t:
            amb = amb.fillna(t["amb_C"])
        for name in bands:
            rows[f"pred_{name}"] = np.nan
        for seg in _segments(t["timestamp"], amps.notna() & amb.notna()):
            a, b = amps.to_numpy()[seg], amb.to_numpy()[seg]
            for name, p in bands.items():
                rows.loc[seg, f"pred_{name}"] = _run(a, b, t["timestamp"].iloc[seg], i_rated_A, p) - b
        rows["observed_rise"] = t["OTI_C"] - amb
        evaluable = rows["observed_rise"].notna() & rows["pred_low"].notna() & ~bad
        below = evaluable & (rows["observed_rise"] < rows["pred_low"] - tol_K)
        above = evaluable & (rows["observed_rise"] > rows["pred_high"] + tol_K)
        rows["implausible"] = below | above
        rows["evaluable"] = evaluable
        n = int(evaluable.sum())
        frac = float(rows["implausible"][evaluable].mean()) if n else np.nan
        verdict["OTI_C"] = "suspect" if n and frac > SUSPECT_FRACTION else "plausible" if n else "not checked"
        ev = rows[evaluable]
        summary["rise"] = {
            "evaluable_rows": n, "implausible_rows": int(rows["implausible"].sum()),
            "below_band": int(below.sum()), "above_band": int(above.sum()), "implausible_fraction": round(frac, 3),
            "observed_rise_median_K": round(float(ev["observed_rise"].median()), 2),
            "predicted_low_median_K": round(float(ev["pred_low"].median()), 2),
            "predicted_nominal_median_K": round(float(ev["pred_nominal"].median()), 2),
            "predicted_high_median_K": round(float(ev["pred_high"].median()), 2),
            "load_pu_median": round(float(ev["load_pu"].median()), 3),
            # even with zero load, core (no-load) losses alone keep top-oil this far above ambient:
            "no_load_floor_low_K": round(float(steady_rise(0.0, **bands["low"])), 2),
        }
        # rating sensitivity: does a bigger nameplate rescue the readings? (steady state at median load)
        med_amps = float(t["I_mean"][evaluable].median())
        summary["rating_sensitivity"] = {
            f"x{m:g}": round(float(steady_rise(med_amps / (i_rated_A * m), **bands["low"])), 2)
            for m in (1, 1.5, 2, 3, 5)}
    else:
        rows["implausible"] = False
        rows["evaluable"] = False

    # ---- ambient vs weather ----
    if "ATI_C" in t and weather is not None and not weather.empty:
        wx = weather_at(t["timestamp"], weather, "temp_C")
        flags = t.get("dq_flags", pd.Series("", index=t.index)).fillna("")
        ok = t["ATI_C"].notna() & wx.notna() & ~flags.str.contains("RANGE_ATI_C")
        if ok.sum() >= 96:
            d = (t["ATI_C"] - wx)[ok]
            daily = pd.DataFrame({"ati": t["ATI_C"][ok].to_numpy(), "wx": wx[ok].to_numpy()},
                                 index=pd.DatetimeIndex(t["timestamp"][ok])).resample("1D").mean().dropna()
            mism = ati_mismatch(t, weather)
            rows["ati_mismatch"] = mism.to_numpy()
            rows["weather_C"] = wx.to_numpy()
            rows["ATI_C"] = t["ATI_C"].where(ok).to_numpy()
            corr = float(np.corrcoef(t["ATI_C"][ok], wx[ok])[0, 1])
            summary["ambient"] = {
                "rows": int(ok.sum()), "bias_C": round(float(d.mean()), 2), "mae_C": round(float(d.abs().mean()), 2),
                "corr_15min": round(corr, 3), "corr_daily": round(float(daily["ati"].corr(daily["wx"])), 3),
                "mismatch_rows": int(mism.sum()), "mismatch_fraction": round(float(mism[ok].mean()), 4)}
            verdict["ATI_C"] = "suspect" if (mism[ok].mean() > 0.1 or corr < 0.5) else "plausible"
            if "rise" in summary:  # same test with weather as ambient: verdict must not hinge on the ATI sensor
                ev = rows["implausible"].notna() & rows["pred_low"].notna() & wx.notna() & t["OTI_C"].notna()
                rise_wx = (t["OTI_C"] - wx)[ev]
                summary["rise"]["observed_rise_vs_weather_median_K"] = round(float(rise_wx.median()), 2)
                summary["rise"]["below_band_vs_weather_fraction"] = round(
                    float((rise_wx < rows["pred_low"][ev] - tol_K).mean()), 3)
    if "ati_mismatch" not in rows:
        rows["ati_mismatch"] = False
    return PlausibilityResult(rows=rows, verdict=verdict, summary=summary)


def add_flags(trend: pd.DataFrame, result: PlausibilityResult) -> pd.DataFrame:
    """Append IMPLAUSIBLE_RISE / ATI_MISMATCH to dq_flags (rows kept, as always)."""
    t = trend.reset_index(drop=True).copy()
    for col, code in (("implausible", "IMPLAUSIBLE_RISE"), ("ati_mismatch", "ATI_MISMATCH")):
        m = result.rows[col].fillna(False).astype(bool).to_numpy()
        has = t["dq_flags"].fillna("").str.split(";").apply(lambda xs, c=code: c in xs).to_numpy()
        add = m & ~has
        t.loc[add, "dq_flags"] = (t.loc[add, "dq_flags"].fillna("") + ";" + code).str.lstrip(";")
    return t


def plot(result: PlausibilityResult, path, title: str = "") -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    r = result.rows
    has_rise = "observed_rise" in r
    has_amb = "weather_C" in r
    n = 1 + has_rise + has_amb
    fig, ax = plt.subplots(1, n, figsize=(6.2 * n, 5))
    ax = np.atleast_1d(ax)
    i = 0
    if has_rise:
        ok = r["evaluable"].astype(bool)  # RANGE/JUMP/STUCK rows are sensor faults, not part of the test
        a = ax[i]; i += 1
        a.scatter(r.loc[ok, "load_pu"], r.loc[ok, "observed_rise"], s=3, alpha=0.25, color="#555",
                  label="measured OTI − ambient")
        k = np.linspace(0, max(1.0, float(r.loc[ok, "load_pu"].quantile(0.995))), 100)
        for name, ls in (("low", "--"), ("nominal", "-"), ("high", "--")):
            a.plot(k, steady_rise(k, **BANDS[name]), ls, color="#c0392b", lw=1.5,
                   label=f"IEC 60076-7 steady state, {name}")
        a.fill_between(k, steady_rise(k, **BANDS["low"]), steady_rise(k, **BANDS["high"]), color="#c0392b", alpha=0.08)
        a.set_xlabel("load (pu of rating)")
        a.set_ylabel("top-oil rise over ambient (K)")
        a.set_title(f"Top-oil rise vs physics band ({int(ok.sum())} rows)")
        a.set_ylim(min(-5, float(r.loc[ok, "observed_rise"].quantile(0.001))), float(steady_rise(k[-1], **BANDS["high"])) + 10)
        a.legend(fontsize=8, loc="upper left")
        a.grid(alpha=0.3)
        a = ax[i]; i += 1
        d = r[ok].set_index("timestamp")[["observed_rise", "pred_low", "pred_nominal", "pred_high"]].resample("1D").median()
        a.fill_between(d.index, d["pred_low"], d["pred_high"], color="#c0392b", alpha=0.15, label="IEC band (daily median)")
        a.plot(d.index, d["pred_nominal"], color="#c0392b", lw=1, label="IEC nominal")
        a.plot(d.index, d["observed_rise"], color="k", lw=1.2, label="measured OTI − ambient")
        a.set_ylabel("rise (K), daily median")
        a.set_title(f"Over time — OTI verdict: {result.verdict['OTI_C'].upper()}")
        a.legend(fontsize=8)
        a.grid(alpha=0.3)
        fig.autofmt_xdate()
    if has_amb:
        a = ax[i]
        d = r.set_index("timestamp")[["ATI_C", "weather_C"]].dropna().resample("1D").mean()
        a.plot(d.index, d["weather_C"], color="#2166ac", lw=1.2, label="Open-Meteo air temperature")
        a.plot(d.index, d["ATI_C"], color="k", lw=1.2, label="measured ATI")
        amb = result.summary.get("ambient", {})
        a.set_title(f"Ambient vs weather — ATI verdict: {result.verdict['ATI_C'].upper()}")
        a.text(0.02, 0.02, f"bias {amb.get('bias_C'):+} °C · MAE {amb.get('mae_C')} °C\n"
                           f"corr 15-min {amb.get('corr_15min')} · daily {amb.get('corr_daily')}\n"
                           f"ATI_MISMATCH rows {amb.get('mismatch_rows')}",
               transform=a.transAxes, va="bottom", fontsize=8)
        a.set_ylabel("°C, daily mean")
        a.legend(fontsize=8, loc="upper right")
        a.grid(alpha=0.3)
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
