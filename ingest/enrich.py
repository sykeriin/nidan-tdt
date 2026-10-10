"""Step 7 ENRICH: ambient/RH from the offline Open-Meteo cache, nameplate resolution.

Cache: data/cache/weather/bengaluru_YYYY-MM.json (raw Open-Meteo archive response).
Fetch once with network:  python -m ingest.enrich fetch 2026 4
After that everything runs offline.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from twin import profile as _profile

from contracts.canonical import TZ

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache" / "weather"
SITES = {
    "bengaluru": {"latitude": 12.9716, "longitude": 77.5946},   # Transformer-1, Bengaluru city [Assumed site point]
    "hyderabad": {"latitude": 17.3850, "longitude": 78.4867},   # Kaggle unit [Assumed location]
}
DEFAULT_SITE = "bengaluru"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FALLBACK_AMBIENT_C = 27.0  # [Assumed] only when no ATI, no cache coverage, no climatology


# ---------- weather cache ----------
def cache_path(year: int, month: int, site: str = DEFAULT_SITE, cache_dir=CACHE) -> Path:
    return Path(cache_dir) / f"{site}_{year:04d}-{month:02d}.json"


def fetch_month(year: int, month: int, site: str = DEFAULT_SITE, cache_dir=CACHE) -> Path:
    import requests  # network only here
    start = pd.Timestamp(year=year, month=month, day=1)
    end = start + pd.offsets.MonthEnd(0)
    r = requests.get(ARCHIVE_URL, timeout=60, params={
        "latitude": SITES[site]["latitude"], "longitude": SITES[site]["longitude"],
        "start_date": start.date().isoformat(), "end_date": end.date().isoformat(),
        "hourly": "temperature_2m,relative_humidity_2m", "timezone": TZ})
    r.raise_for_status()
    p = cache_path(year, month, site, cache_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(r.text, encoding="utf-8")
    return p


def load_weather(cache_dir=CACHE, site: str = DEFAULT_SITE) -> pd.DataFrame:
    """All cached months for a site as hourly frame [timestamp, temp_C, rh_pct] (tz-aware). Empty if no cache."""
    frames = []
    for p in sorted(Path(cache_dir).glob(f"{site}_*.json")):
        h = json.loads(p.read_text(encoding="utf-8"))["hourly"]
        frames.append(pd.DataFrame({
            "timestamp": pd.to_datetime(h["time"]).tz_localize(TZ),
            "temp_C": pd.to_numeric(pd.Series(h["temperature_2m"]), errors="coerce"),
            "rh_pct": pd.to_numeric(pd.Series(h["relative_humidity_2m"]), errors="coerce")}))
    if not frames:
        return pd.DataFrame(columns=["timestamp", "temp_C", "rh_pct"])
    return pd.concat(frames).drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)


def weather_at(ts: pd.Series, weather: pd.DataFrame, col: str) -> pd.Series:
    """Time-interpolate hourly weather to ts; NaN outside cache coverage."""
    if weather.empty:
        return pd.Series(np.nan, index=ts.index)
    x = weather["timestamp"].dt.as_unit("ns").astype("int64").to_numpy()
    t = pd.to_datetime(ts).dt.as_unit("ns").astype("int64").to_numpy()
    v = np.interp(t, x, weather[col].to_numpy())
    hour_ns = 3600 * 10**9  # hold edge values up to 1 h past the hourly cache (e.g. 23:15-23:45 on the last day)
    v[(t < x[0] - hour_ns) | (t > x[-1] + hour_ns)] = np.nan
    return pd.Series(v, index=ts.index)


def fill_ambient(df: pd.DataFrame, weather: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """amb_C = valid ATI_C; else cache; else interpolate ATI within 2 h; else cache hour-of-day climatology; else constant."""
    df = df.copy()
    log = []
    amb = pd.Series(np.nan, index=df.index)
    if "ATI_C" in df:
        bad = df.get("__dq_RANGE_ATI_C", pd.Series(False, index=df.index)).astype(bool)
        amb = df["ATI_C"].where(~bad)
    need = amb.isna()
    w = weather_at(df["timestamp"], weather, "temp_C")
    take = need & w.notna()
    amb[take] = w[take]
    df["__dq_IMPUTED_AMB"] = take
    if take.any():
        log.append(f"amb_C from Open-Meteo cache for {int(take.sum())} rows")
    need = amb.isna()
    if need.any() and "ATI_C" in df and amb.notna().any():
        s = pd.Series(amb.to_numpy(), index=pd.DatetimeIndex(df["timestamp"]))
        filled = s.interpolate(method="time", limit=8, limit_area="inside").to_numpy()
        take = need & ~np.isnan(filled)
        amb[take] = filled[take.to_numpy()]
        df["__dq_IMPUTED_AMB"] |= take
        if take.any():
            log.append(f"amb_C interpolated from neighbouring ATI for {int(take.sum())} rows")
    need = amb.isna()
    if need.any():
        if not weather.empty:
            clim = weather.groupby(weather["timestamp"].dt.hour)["temp_C"].mean()
            amb[need] = df.loc[need, "timestamp"].dt.hour.map(clim).to_numpy()
            log.append(f"amb_C from cache hour-of-day climatology for {int(need.sum())} rows (ASSUMED_AMBIENT)")
        else:
            amb[need] = FALLBACK_AMBIENT_C
            log.append(f"amb_C constant {FALLBACK_AMBIENT_C} C for {int(need.sum())} rows (ASSUMED_AMBIENT)")
        df["__dq_ASSUMED_AMBIENT"] = need
    df["amb_C"] = amb.astype(float)
    if "RH_pct" not in df or df["RH_pct"].isna().all():
        rh = weather_at(df["timestamp"], weather, "rh_pct")
        if rh.notna().any():
            df["RH_pct"] = rh
            df["__dq_IMPUTED_RH"] = rh.notna()
            log.append(f"RH_pct from Open-Meteo cache for {int(rh.notna().sum())} rows")
    return df, log


def fill_ambient_static(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Snapshot mode (no time, so no weather lookup): valid ATI, else median of valid ATI, else constant."""
    df = df.copy()
    bad = df.get("__dq_RANGE_ATI_C", pd.Series(False, index=df.index)).astype(bool)
    amb = df["ATI_C"].where(~bad) if "ATI_C" in df else pd.Series(np.nan, index=df.index)
    need = amb.isna()
    fill = float(amb.median()) if amb.notna().any() else FALLBACK_AMBIENT_C
    amb[need] = fill
    df["__dq_ASSUMED_AMBIENT"] = need
    df["amb_C"] = amb.astype(float)
    return df, ([f"amb_C assumed {fill:.1f} C for {int(need.sum())} records (ASSUMED_AMBIENT)"] if need.any() else [])


def ati_mismatch(df: pd.DataFrame, weather: pd.DataFrame, limit_C=8.0, hours=6) -> pd.Series:
    """ATI vs Open-Meteo differs > limit for > hours (spec §2.8)."""
    if "ATI_C" not in df or weather.empty:
        return pd.Series(False, index=df.index)
    diff = (df["ATI_C"] - weather_at(df["timestamp"], weather, "temp_C")).abs() > limit_C
    s = pd.Series(diff.to_numpy(), index=pd.DatetimeIndex(df["timestamp"]))
    run = s.astype(int).rolling(f"{hours}h").mean() >= 0.999
    return pd.Series(run.to_numpy() & diff.to_numpy(), index=df.index)


# ---------- nameplate ----------
def read_asset(path) -> dict:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    vals = {k: (v["value"] if isinstance(v, dict) and "value" in v else v) for k, v in raw.items()}
    vals["tags"] = {k: v.get("tag") for k, v in raw.items() if isinstance(v, dict)}
    return vals


def resolve_asset(asset, trend: pd.DataFrame | None = None) -> dict:
    """asset: path to asset.yaml | dict (UI form: rating_kVA, lv_voltage_V, ...) | None/'estimate'."""
    if isinstance(asset, (str, Path)) and str(asset) != "estimate":
        a = read_asset(ROOT / asset if not Path(asset).is_absolute() else asset)
        a["nameplate_source"] = "asset.yaml"
    elif isinstance(asset, dict):
        a = dict(asset)
        a.setdefault("nameplate_source", "user input")
    else:
        a = {"nameplate_source": "estimated"}
    a.setdefault("lv_voltage_V", 415)
    if not a.get("i_rated_A") and a.get("rating_kVA"):
        a["i_rated_A"] = round(a["rating_kVA"] * 1000 / (np.sqrt(3) * a["lv_voltage_V"]), 1)
    if not a.get("i_rated_A") and trend is not None:
        i = trend[["IR", "IY", "IB"]].mean(axis=1) if {"IR", "IY", "IB"} <= set(trend) else None
        if i is not None and i.notna().any():
            vln = trend[[c for c in ("VR", "VY", "VB") if c in trend]].mean(axis=1)
            if vln.notna().any() and a.get("nameplate_source") == "estimated":
                a["lv_voltage_V"] = round(float(vln[vln > 100].median() * np.sqrt(3)), 1)
            a["i_rated_A"] = round(float(i.quantile(0.99)) / 0.8, 1)
            a["rating_kVA"] = round(a["i_rated_A"] * np.sqrt(3) * a["lv_voltage_V"] / 1000, 1)
            a["nameplate_source"] = "estimated"
            a.setdefault("tags", {}).update(i_rated_A="Assumed - estimated from data (p99 I_mean / 0.8)",
                                            rating_kVA="Assumed - estimated from data")
    return _profile.complete(a)


if __name__ == "__main__":
    if len(sys.argv) in (4, 5) and sys.argv[1] == "fetch":
        print(fetch_month(int(sys.argv[2]), int(sys.argv[3]), *sys.argv[4:]))
    else:
        print("usage: python -m ingest.enrich fetch YEAR MONTH [SITE]")
