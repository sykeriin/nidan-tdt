"""Generated campus data for Transformer-1 (FINAL_PRD.md §5): plant = perturbed library + sensor noise.

    python -m sim.generator            # all scenarios -> data/generated/
    python -m sim.generator N S2       # some

Every scenario shares the Normal base (same seed -> identical rows before fault onset).
The library always gets LV amps. Ambient/RH come from the offline Open-Meteo cache.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from transformer_thermal_model.model import Model
from transformer_thermal_model.schemas import InputProfile, UserTransformerSpecifications
from transformer_thermal_model.schemas.thermal_model.initial_state import InitialLoad
from transformer_thermal_model.transformer import DistributionTransformer

from contracts.canonical import TREND_COLUMNS, TZ, empty_events
from ingest.enrich import load_weather, read_asset, weather_at

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "generated"
SCENARIO_IDS = ["N", "S1", "S2", "S3", "S4a", "S4b", "S5"]
PH = ["IR", "IY", "IB"]


def load_config(path=ROOT / "config" / "scenarios.yaml") -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def _smooth_step(h, on, off, width=0.5):
    return 1 / (1 + np.exp(-(h - on) / width)) * 1 / (1 + np.exp(-(off - h) / width))


def run_plant(amps: np.ndarray, amb: np.ndarray, idx: pd.DatetimeIndex, asset: dict,
              rise_mult: float = 1.0, hot_spot_fac: float | None = None) -> pd.DataFrame:
    """Library run. amps = LV amps (never per-unit)."""
    specs = UserTransformerSpecifications(
        load_loss=asset["load_loss_W"], no_load_loss=asset["no_load_loss_W"],
        nom_load_sec_side=asset["i_rated_A"],
        top_oil_temp_rise=60.0 * rise_mult, hot_spot_fac=hot_spot_fac)
    prof = InputProfile.create(datetime_index=idx.tz_localize(None), load_profile=amps,
                               ambient_temperature_profile=amb)
    out = Model(temperature_profile=prof, transformer=DistributionTransformer(user_specs=specs),
                initial_condition=InitialLoad(initial_load=float(amps[0]))).run()
    df = out.convert_to_dataframe()
    return pd.DataFrame({"oil": df["top_oil_temperature"].to_numpy(), "hs": df["hot_spot_temperature"].to_numpy()})


def generate(scenario_id: str = "N", seed: int = 0, cfg: dict | None = None,
             weather: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Canonical trend + events for one scenario (FINAL_PRD.md §12.2)."""
    if scenario_id not in SCENARIO_IDS:
        raise ValueError(f"unknown scenario {scenario_id}")
    cfg = cfg or load_config()
    asset = read_asset(ROOT / "config" / "asset.yaml")
    i_rated = asset["i_rated_A"]
    w = cfg["window"]
    idx = pd.date_range(pd.Timestamp(w["start"], tz=TZ), periods=w["days"] * 96, freq=w["freq"])
    n = len(idx)
    hour = np.asarray(idx.hour + idx.minute / 60)
    day = np.asarray((idx - idx[0]).days + 1)  # 1-based calendar day
    wx = load_weather() if weather is None else weather
    amb_true = weather_at(pd.Series(idx), wx, "temp_C").to_numpy()
    if np.isnan(amb_true).any():
        raise ValueError("weather cache does not cover the window; run python -m ingest.enrich fetch 2026 4")

    # ---- Normal base: every random draw happens here, in a fixed order ----
    rng = np.random.default_rng(seed)
    L, P = cfg["load"], cfg["plant"]
    n_days = w["days"]
    weekday_peak = rng.uniform(*L["weekday_peak_pu"], n_days)
    weekend_peak = rng.uniform(*L["weekend_peak_pu"], n_days)
    is_weekday = idx.dayofweek < 5
    peak = np.where(is_weekday, weekday_peak[day - 1], weekend_peak[day - 1])
    ar = np.zeros(n)
    e = rng.normal(0, L["noise_pu"], n)
    for k in range(1, n):
        ar[k] = 0.8 * ar[k - 1] + e[k] * np.sqrt(1 - 0.8 ** 2)
    pu = (L["night_pu"] + (peak - L["night_pu"]) * _smooth_step(hour, *L["day_hours"])
          + L["evening_bump_pu"] * _smooth_step(hour, 19, 23)
          + L["ambient_coupling_pu_per_C"] * np.clip(amb_true - 28, 0, None) + ar)
    pu = np.clip(pu, 0.1, None)
    static = rng.uniform(-L["phase_imbalance"], L["phase_imbalance"], 3)
    static -= static.mean()
    phase_noise = rng.normal(0, L["phase_noise"], (n, 3))
    rise_mult = rng.uniform(*P["top_oil_rise_mult"])
    hsf = rng.uniform(*P["hot_spot_fac"])
    nt = P["noise_temp_C"]
    noise_oti, noise_wti, noise_ati, noise_oli = (rng.normal(0, s, n) for s in (nt, nt, 0.3, 0.3))
    noise_vi = rng.normal(0, P["noise_vi_frac"], (n, 6))
    v_offset = rng.uniform(-0.003, 0.003, 3)
    pf = np.clip(0.93 + 0.03 * pu + rng.normal(0, 0.005, n), 0.8, 0.99)
    freq = 50 + rng.normal(0, 0.03, n)

    # ---- scenario injections (plant only) ----
    sc = cfg["scenarios"][scenario_id]
    srng = np.random.default_rng([seed, SCENARIO_IDS.index(scenario_id)])
    gt = np.zeros(n, dtype=bool)
    oli_delta = np.zeros(n)
    rise_ramp = np.zeros(n)  # 0..1 weight towards degraded cooling
    phase_mult = np.ones((n, 3))
    events = empty_events()
    meta = {}

    if scenario_id == "S1":
        add = np.zeros(n)
        for step in sc["plan"]:
            d, lvl, dur = step["day"], step["level_pu"], step["hours"]
            on, off = sc["centre_h"] - dur / 2, sc["centre_h"] + dur / 2
            win = (day == d) * _smooth_step(hour, on + 0.25, off - 0.25, 0.06)  # ~15 min ramps inside [on, off)
            add = np.maximum(add, win * np.clip(lvl - pu, 0, None))
            gt |= (day == d) & (hour >= on) & (hour < off)
            meta[f"day{d}"] = {"level_pu": lvl, "hours": dur}
        pu = pu + add
    elif scenario_id == "S2":
        t0 = idx[0] + pd.Timedelta(days=sc["start_day"] - 1)
        rise_ramp = np.clip((idx - t0) / pd.Timedelta(days=sc["ramp_days"]), 0, 1)
        gt = idx >= t0
    elif scenario_id == "S3":
        t0 = idx[0] + pd.Timedelta(days=sc["start_day"] - 1)
        up = srng.uniform(*sc["up_frac"])
        on = idx >= t0
        phase_mult[on, PH.index(sc["up_phase"])] = 1 + up
        phase_mult[on, PH.index(sc["down_phase"])] = 1 - sc["down_frac"]
        gt = on
        meta["up_frac"] = round(up, 3)
    elif scenario_id == "S4a":
        t0 = idx[0] + pd.Timedelta(days=sc["start_day"] - 1, hours=sc["start_h"])
        frac = np.clip((idx - t0) / pd.Timedelta(days=sc["days"]), 0, 1)
        oli_delta = -sc["drop_pct"] * frac
        gt = idx >= t0
    elif scenario_id == "S4b":
        t0 = idx[0] + pd.Timedelta(days=sc["day"] - 1, hours=sc["hour"])
        step = srng.uniform(*sc["step_pct"])
        k0 = int(np.searchsorted(idx, t0))
        for j in range(sc["samples"]):
            oli_delta[k0 + j:] -= step / sc["samples"]
        gt = idx >= t0
        meta["step_pct"] = round(step, 2)
    elif scenario_id == "S5":
        d0 = idx[0].normalize() + pd.Timedelta(days=sc["day"] - 1)
        rows = []
        for ev in sc["events"]:
            t = d0 + pd.Timedelta(ev["time"])
            rows.append({"timestamp": t, "event_type": "through_fault", "phase": ev["phase"],
                         "peak_pu": ev["peak_pu"], "duration_ms": ev["duration_ms"],
                         "i2t_pu2s": ev["peak_pu"] ** 2 * ev["duration_ms"] / 1000,
                         "source": "generated_sim", "simulated": True})
            gt |= (idx <= t) & (t < idx + pd.Timedelta(w["freq"]))
        events = pd.DataFrame(rows)

    # ---- currents (amps), thermal plant, sensors ----
    i_true = pu[:, None] * i_rated * (1 + static) * phase_mult * (1 + phase_noise)
    i_mean_true = i_true.mean(axis=1)
    base = run_plant(i_mean_true, amb_true, idx, asset, rise_mult, hsf)
    oil, hs = base["oil"].to_numpy(), base["hs"].to_numpy()
    if scenario_id == "S2":
        deg = run_plant(i_mean_true, amb_true, idx, asset, rise_mult * sc["rise_mult"], hsf)
        oil = oil + rise_ramp * (deg["oil"].to_numpy() - oil)
        hs = hs + rise_ramp * (deg["hs"].to_numpy() - hs)

    meas_i = i_true * (1 + noise_vi[:, :3])
    v_ln = 415 / np.sqrt(3) * (1.005 - 0.01 * pu)[:, None] * (1 + v_offset) * (1 + noise_vi[:, 3:])
    ang = np.deg2rad([0, -120, 120])
    i_n = np.abs((meas_i * np.exp(1j * ang)).sum(axis=1))
    s_kva = (v_ln * meas_i).sum(axis=1) / 1000
    oli = np.clip(P["oil_level_base_pct"] + P["oil_level_per_C"] * (oil - 50) + noise_oli + oli_delta, 0, 100)

    trend = pd.DataFrame({
        "timestamp": idx,
        "IR": meas_i[:, 0], "IY": meas_i[:, 1], "IB": meas_i[:, 2], "I_mean": meas_i.mean(axis=1), "IN": i_n,
        "VR": v_ln[:, 0], "VY": v_ln[:, 1], "VB": v_ln[:, 2],
        "S_kVA": s_kva, "P_kW": s_kva * pf, "Q_kVAr": s_kva * np.sqrt(1 - pf ** 2), "PF": pf, "freq_Hz": freq,
        "loading_pct": meas_i.mean(axis=1) / i_rated * 100,
        "OTI_C": oil + noise_oti, "WTI_C": hs + noise_wti, "ATI_C": amb_true + noise_ati,
        "OLI_pct": oli,
    })
    trend["amb_C"] = trend["ATI_C"]
    trend["dq_flags"] = ""
    trend["source"] = "generated_sim"
    trend["simulated"] = True
    trend["gt_fault"] = gt.astype(int)
    trend["gt_type"] = np.where(gt, scenario_id if scenario_id != "N" else "", "")
    trend = trend[[c for c in TREND_COLUMNS if c in trend] + ["gt_fault", "gt_type"]]
    num = trend.select_dtypes("number").columns
    trend[num] = trend[num].round(3)
    trend.attrs["meta"] = {"scenario": scenario_id, "name": sc["name"], "seed": seed,
                           "plant": {"top_oil_rise_mult": round(rise_mult, 4), "hot_spot_fac": round(hsf, 4)},
                           "twin_nominal": {"top_oil_rise_K": 60.0, "hot_spot_fac": 1.2},
                           "i_rated_A": i_rated, **meta}
    return trend, events


def write(scenario_id: str, seed: int = 0, out=OUT) -> Path:
    trend, events = generate(scenario_id, seed)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    trend.to_csv(out / f"trend_{scenario_id}.csv", index=False)
    events.to_csv(out / f"events_{scenario_id}.csv", index=False)
    (out / f"meta_{scenario_id}.json").write_text(json.dumps(trend.attrs["meta"], indent=1), encoding="utf-8")
    return out / f"trend_{scenario_id}.csv"


if __name__ == "__main__":
    for sid in sys.argv[1:] or SCENARIO_IDS:
        print(write(sid))
