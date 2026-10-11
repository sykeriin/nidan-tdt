"""Machine-learning second opinions for Diagnose: an Isolation Forest on the twin's residual, and a Prophet forecast.

Both are advisory. The physics (twin residual, thresholds, rules) stays the primary detector; these two answer different
questions and are shown next to it.

  isolation_forest(trend, t)   Trained on the first days of the record (assumed normal), scores every sample up to t on
                               [twin residual, load, phase unbalance, oil-level slope]. High score = unlike the training days.
  prophet_check(trend, t)      Prophet fitted on the weeks before t-24 h with ambient and load as regressors, then asked what
                               the top-oil temperature *should* have been over the last 3 days and the next 24 h. The last 24 h
                               are out-of-sample, so a reading outside the 95 % band is a genuine surprise.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

TRAIN_DAYS = 7


def _iso(ts) -> list[str]:
    return [pd.Timestamp(x).isoformat() for x in ts]


def _features(df: pd.DataFrame) -> pd.DataFrame:
    f = pd.DataFrame(index=df.index)
    f["residual"] = df["residual_oil_C"] if "residual_oil_C" in df else 0.0
    f["load"] = df["load_pu"] if "load_pu" in df else 0.0
    cur = [c for c in ("IR", "IY", "IB") if c in df]
    if len(cur) == 3:
        m = df[cur].mean(axis=1).replace(0, np.nan)
        f["unbalance"] = ((df[cur].max(axis=1) - df[cur].min(axis=1)) / m * 100).fillna(0)
    else:
        f["unbalance"] = 0.0
    f["oil_slope"] = df["OLI_pct"].diff(24).fillna(0) if "OLI_pct" in df else 0.0  # change over ~6 h at 15 min
    return f.fillna(0.0)


def isolation_forest(trend: pd.DataFrame, t: pd.Timestamp, days: int = 14) -> dict:
    from sklearn.ensemble import IsolationForest

    df = trend[trend["timestamp"] <= t].reset_index(drop=True)
    if len(df) < 200:
        return {"available": False, "reason": "not enough history yet: the forest needs about two days of samples"}
    X = _features(df)
    t0 = df["timestamp"].iloc[0]
    train_mask = df["timestamp"] < t0 + pd.Timedelta(days=TRAIN_DAYS)
    if train_mask.sum() < 100:
        train_mask = df.index < max(100, len(df) // 3)
    mu, sd = X[train_mask].mean(), X[train_mask].std().replace(0, 1.0)
    Z = (X - mu) / sd
    model = IsolationForest(n_estimators=250, contamination="auto", random_state=0).fit(Z[train_mask])
    raw = -model.score_samples(Z)  # higher = more anomalous
    s_train = raw[train_mask.to_numpy()]
    lo, hi = float(np.percentile(s_train, 50)), float(np.percentile(s_train, 99.7))
    score = np.clip((raw - lo) / (hi - lo + 1e-9), 0, 2)  # 0 = typical of training, 1 = the edge of it
    sm = pd.Series(score).rolling(8, min_periods=1).mean().to_numpy()  # 2 h smoothing: single samples are noisy
    flag = sm > 1.0
    # episodes
    eps, i = [], 0
    while i < len(flag):
        if flag[i]:
            j = i
            while j + 1 < len(flag) and flag[j + 1]:
                j += 1
            if j - i + 1 >= 8:  # at least 2 h
                seg = slice(i, j + 1)
                dev = (Z.iloc[seg].abs()).mean().sort_values(ascending=False)
                eps.append({"start": df["timestamp"].iloc[i].isoformat(), "end": df["timestamp"].iloc[j].isoformat(),
                            "peak": round(float(sm[seg].max()), 2), "driver": dev.index[0], "driver_z": round(float(dev.iloc[0]), 1)})
            i = j + 1
        else:
            i += 1
    w0 = t - pd.Timedelta(days=days)
    keep = (df["timestamp"] >= w0).to_numpy()
    idx = np.where(keep)[0][::4]  # hourly
    DRV = {"residual": "twin residual", "load": "load pattern", "unbalance": "phase unbalance", "oil_slope": "oil level trend"}
    now_dev = Z.iloc[-1].abs().sort_values(ascending=False)
    return {
        "available": True,
        "t": _iso(df["timestamp"].iloc[idx]), "score": [round(float(x), 3) for x in sm[idx]],
        "threshold": 1.0, "trained_on": f"first {TRAIN_DAYS} days ({int(train_mask.sum())} samples)",
        "features": list(X.columns), "episodes": [{**e, "driver": DRV.get(e["driver"], e["driver"])} for e in eps[-8:]],
        "now": {"score": round(float(sm[-1]), 2), "flagged": bool(flag[-1]), "driver": DRV.get(now_dev.index[0], now_dev.index[0])},
        "episode_count": len(eps),
        "note": "Advisory second opinion: it flags samples unlike the first week, which is a different question from 'is the transformer healthy'.",
    }


def prophet_check(trend: pd.DataFrame, t: pd.Timestamp, back_days: int = 21) -> dict:
    try:
        from prophet import Prophet
    except Exception:  # pragma: no cover
        return {"available": False, "reason": "Prophet is not installed on the server"}
    logging.getLogger("cmdstanpy").setLevel(logging.ERROR)
    logging.getLogger("prophet").setLevel(logging.ERROR)
    logging.getLogger("stan").setLevel(logging.ERROR)
    df = trend[trend["timestamp"] <= t]
    ycol = "OTI_C" if "OTI_C" in df and df["OTI_C"].notna().mean() > 0.5 else "twin_oil_C"
    need = {ycol, "amb_C", "load_pu", "timestamp"}
    if not need <= set(df.columns) or len(df) < 600:
        return {"available": False, "reason": "needs about a week of top-oil, ambient and load samples"}

    def prep(d: pd.DataFrame) -> pd.DataFrame:
        x = d[["timestamp", ycol, "amb_C", "load_pu"]].copy()
        x["timestamp"] = x["timestamp"].dt.tz_localize(None) if x["timestamp"].dt.tz is not None else x["timestamp"]
        x = x.set_index("timestamp").resample("1h").mean().dropna().reset_index()
        return x.rename(columns={"timestamp": "ds", ycol: "y"})

    h = prep(df[df["timestamp"] > t - pd.Timedelta(days=back_days)])
    t_naive = (t.tz_localize(None) if t.tzinfo is not None else t).floor("1h")
    cut = t_naive - pd.Timedelta(hours=24)
    train = h[h["ds"] <= cut]
    if len(train) < 72:
        return {"available": False, "reason": "needs at least three days before the last 24 h to train on"}
    m = Prophet(interval_width=0.95, daily_seasonality=True, weekly_seasonality=len(train) > 24 * 14, yearly_seasonality=False,
                changepoint_prior_scale=0.05)
    m.add_regressor("amb_C")
    m.add_regressor("load_pu")
    m.fit(train)
    # the next 24 h: ambient and load follow the average of the same hour over the last week
    recent = h[h["ds"] > t_naive - pd.Timedelta(days=7)]
    prof = recent.assign(hr=recent["ds"].dt.hour).groupby("hr")[["amb_C", "load_pu"]].mean()
    fut_ds = pd.date_range(t_naive - pd.Timedelta(hours=72), t_naive + pd.Timedelta(hours=24), freq="1h")
    fut = pd.DataFrame({"ds": fut_ds}).merge(h[["ds", "amb_C", "load_pu"]], on="ds", how="left")
    for c in ("amb_C", "load_pu"):
        fut[c] = fut[c].fillna(fut["ds"].dt.hour.map(prof[c]))
    p = m.predict(fut).merge(h[["ds", "y"]], on="ds", how="left")
    last = p[(p["ds"] > cut) & (p["ds"] <= t_naive) & p["y"].notna()]
    out = (last["y"] < last["yhat_lower"]) | (last["y"] > last["yhat_upper"])
    mae = float((last["y"] - last["yhat"]).abs().mean()) if len(last) else None
    hot = last[out]
    first_breach = hot["ds"].iloc[0].isoformat() if len(hot) else None
    p["breach"] = (p["y"].notna() & ((p["y"] < p["yhat_lower"]) | (p["y"] > p["yhat_upper"]))) & (p["ds"] > cut)
    r = lambda s: [None if pd.isna(v) else round(float(v), 2) for v in s]  # noqa: E731
    return {
        "available": True, "target": "top-oil temperature (sensor)" if ycol == "OTI_C" else "top-oil temperature (twin)",
        "t": [d.isoformat() for d in p["ds"]], "yhat": r(p["yhat"]), "lo": r(p["yhat_lower"]), "hi": r(p["yhat_upper"]), "actual": r(p["y"]),
        "breach": [bool(b) for b in p["breach"]], "cut": cut.isoformat(), "now": t_naive.isoformat(),
        "mae_24h_C": None if mae is None else round(mae, 2), "outside_band_hours": int(out.sum()), "hours_checked": int(len(last)),
        "first_breach": first_breach, "trained_hours": int(len(train)),
        "verdict": ("Last 24 h matched what the model expected." if int(out.sum()) == 0 else
                    f"{int(out.sum())} of the last {len(last)} hours were outside the 95 % band: the transformer ran hotter or cooler than its own recent pattern predicts."),
        "note": "Prophet with ambient and load as regressors, trained on the days before the last 24 h, so the last 24 h are a fair test.",
    }
