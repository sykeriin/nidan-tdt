"""Measured vs twin plots -> docs/figures/twin_<ID>.png

    python -m twin.plot N S2
"""
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from twin.engine import TwinEngine, load_config  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def load_generated(sid: str) -> pd.DataFrame:
    t = pd.read_csv(ROOT / "data" / "generated" / f"trend_{sid}.csv", parse_dates=["timestamp"])
    t["timestamp"] = t["timestamp"].dt.tz_convert("Asia/Kolkata")
    t["dq_flags"] = t["dq_flags"].fillna("")
    return t


def plot(sid: str) -> Path:
    r = TwinEngine().run(load_generated(sid))
    cfg = load_config()
    x = r["timestamp"].dt.tz_localize(None)
    fig, ax = plt.subplots(3, 1, figsize=(14, 9.5), sharex=True)
    ax[0].plot(x, r["OTI_C"], color="#ef8a62", lw=0.9, label="top-oil, measured (OTI)")
    ax[0].plot(x, r["twin_oil_C"], color="k", lw=0.8, ls="--", label="top-oil, twin")
    ax[0].plot(x, r["WTI_C"], color="#b2182b", lw=0.6, alpha=0.6, label="hot-spot, measured (WTI)")
    ax[0].plot(x, r["twin_hs_C"], color="#555", lw=0.6, ls=":", label="hot-spot, twin")
    ax[0].plot(x, r["amb_C"], color="#4393c3", lw=0.6, label="ambient")
    ax[0].set_ylabel("°C")
    ax[0].legend(ncol=5, fontsize=8, loc="upper left")
    ax[1].plot(x, r["residual_oil_C"], color="#777", lw=0.6, label="residual = measured − twin top-oil")
    ax[1].plot(x, r["fidelity_rmse_C"], color="#c0392b", lw=1.4, label="fidelity RMSE (rolling 24 h)")
    ax[1].axhline(cfg["fidelity_alert_C"], color="#c0392b", ls=":", lw=1, label=f"drift alert {cfg['fidelity_alert_C']} °C")
    ax[1].axhline(0, color="k", lw=0.5)
    ax[1].set_ylabel("K")
    ax[1].legend(ncol=3, fontsize=8, loc="upper left")
    ax[2].semilogy(x, r["aging_rate"], color="#999", lw=0.6, label="ageing rate, expected (twin, healthy cooling)")
    ax[2].semilogy(x, r["aging_rate_actual"], color="#762a83", lw=0.7, label="ageing rate, actual (measured OTI + gradient)")
    ax[2].axhline(1, color="#762a83", ls=":", lw=0.8)
    ax[2].set_ylabel("relative ageing rate")
    a2 = ax[2].twinx()
    a2.plot(x, r["days_aged_cum"], color="#1b7837", lw=1.0, ls="--", label="life consumed, expected (days)")
    a2.plot(x, r["days_aged_actual_cum"], color="#1b7837", lw=1.5, label="life consumed, actual (days)")
    a2.set_ylabel("days aged")
    h1, l1 = ax[2].get_legend_handles_labels()
    h2, l2 = a2.get_legend_handles_labels()
    ax[2].legend(h1 + h2, l1 + l2, fontsize=8, loc="upper left")
    on = r.loc[r["gt_fault"] == 1, "timestamp"] if "gt_fault" in r else pd.Series(dtype="datetime64[ns]")
    if len(on):
        for a in ax:
            a.axvline(on.iloc[0].tz_localize(None), color="m", lw=1.2)
        ax[0].annotate("fault start", (on.iloc[0].tz_localize(None), ax[0].get_ylim()[1]), color="m", fontsize=9,
                       xytext=(4, -12), textcoords="offset points")
    fa = r.attrs["first_drift_alert"]
    if fa is not None:
        ax[1].axvline(fa.tz_localize(None), color="#c0392b", lw=1.2)
        ax[1].annotate(f"drift alert {fa:%d %b %H:%M}", (fa.tz_localize(None), ax[1].get_ylim()[1]), color="#c0392b",
                       fontsize=9, xytext=(4, -12), textcoords="offset points")
    ru = r.attrs["rul"]
    ax[-1].xaxis.set_major_locator(mdates.DayLocator(interval=2))
    ax[-1].xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    for a in ax:
        a.grid(alpha=0.25)
        a.margins(x=0)
    lc = r.attrs["life_consumed_days"]
    fig.suptitle(f"SIMULATED · Transformer-1 · scenario {sid}: measured (plant) vs twin (nominal)\n"
                 f"life consumed this month: actual {lc['actual']:.2f} d vs expected {lc['expected']:.2f} d "
                 f"({lc['actual_minus_expected']:+.2f} d) · peak ageing rate {r['aging_rate_actual'].max():.2f} · "
                 f"{r.attrs['rul_display']} ({ru.risk} risk) · OTI plausibility: {r.attrs['plausibility']['OTI_C']}",
                 fontsize=11)
    fig.tight_layout()
    out = ROOT / "docs" / "figures" / f"twin_{sid}.png"
    fig.savefig(out, dpi=110)
    plt.close(fig)
    return out


if __name__ == "__main__":
    for sid in sys.argv[1:] or ["N", "S2"]:
        print(plot(sid))
