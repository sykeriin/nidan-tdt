"""Static review plots of generated scenarios -> docs/figures/scenario_<ID>.png

    python -m sim.plot            # all scenarios in data/generated/
"""
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from sim.generator import SCENARIO_IDS, load_config  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
GEN = ROOT / "data" / "generated"
FIG = ROOT / "docs" / "figures"
PH_COLOURS = {"IR": "#d62728", "IY": "#e6b800", "IB": "#1f77b4"}  # R/Y/B


def _read(sid):
    t = pd.read_csv(GEN / f"trend_{sid}.csv", parse_dates=["timestamp"])
    e = pd.read_csv(GEN / f"events_{sid}.csv", parse_dates=["timestamp"])
    t["timestamp"] = t["timestamp"].dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
    if len(e):
        e["timestamp"] = e["timestamp"].dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
    return t, e


def plot(sid: str) -> Path:
    t, ev = _read(sid)
    base = _read("N")[0] if sid != "N" else None
    name = load_config()["scenarios"][sid]["name"]
    oil_panel = sid.startswith("S4")
    n = 4 if (oil_panel or sid == "S5") else 3
    fig, ax = plt.subplots(n, 1, figsize=(14, 2.6 * n + 0.6), sharex=True)
    x = t["timestamp"]
    ax[0].plot(x, t["loading_pct"] / 100, lw=0.8, color="k")
    ax[0].axhline(1.0, color="r", lw=0.6, ls=":")
    ax[0].set_ylabel("load (pu)")
    for c, col in PH_COLOURS.items():
        ax[1].plot(x, t[c], lw=0.6, color=col, label=c)
    ax[1].set_ylabel("current (A)")
    ax[1].legend(loc="upper left", ncol=3, fontsize=8)
    ax[2].plot(x, t["WTI_C"], lw=0.7, color="#b2182b", label="hot-spot (WTI)")
    ax[2].plot(x, t["OTI_C"], lw=0.8, color="#ef8a62", label="top-oil (OTI, measured)")
    ax[2].plot(x, t["ATI_C"], lw=0.7, color="#4393c3", label="ambient (ATI)")
    if base is not None and sid in ("S1", "S2", "S3"):
        ax[2].plot(base["timestamp"], base["OTI_C"], lw=0.7, color="grey", ls="--", label="top-oil, Normal")
    ax[2].set_ylabel("temperature (°C)")
    ax[2].legend(loc="upper left", ncol=4, fontsize=8)
    if oil_panel:
        ax[3].plot(x, t["OLI_pct"], lw=0.8, color="#1b7837", label="oil level")
        if base is not None:
            ax[3].plot(base["timestamp"], base["OLI_pct"], lw=0.7, color="grey", ls="--", label="Normal")
        ax[3].axhline(85, color="r", lw=0.6, ls=":")
        ax[3].set_ylabel("OLI (%)")
        ax[3].legend(loc="lower left", fontsize=8)
    if sid == "S5":
        ax[3].stem(ev["timestamp"], ev["peak_pu"], basefmt=" ")
        for _, r in ev.iterrows():
            ax[3].annotate(f"{r.peak_pu:g} pu / {r.duration_ms:g} ms", (r.timestamp, r.peak_pu), fontsize=8,
                           xytext=(4, 2), textcoords="offset points")
        ax[3].set_ylabel("through-fault\npeak (pu)")
        ax[3].set_ylim(0, 12)
    onset = t.loc[t["gt_fault"] == 1, "timestamp"]
    if len(onset):
        for a in ax:
            a.axvline(onset.iloc[0], color="m", lw=1.2)
        ax[0].annotate("fault start", (onset.iloc[0], ax[0].get_ylim()[1]), color="m", fontsize=9,
                       xytext=(4, -12), textcoords="offset points")
        if sid in ("S1",):
            for a in ax:
                a.fill_between(x, *a.get_ylim(), where=t["gt_fault"] == 1, color="m", alpha=0.08, lw=0)
    ax[-1].xaxis.set_major_locator(mdates.DayLocator(interval=2))
    ax[-1].xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    for a in ax:
        a.grid(alpha=0.25)
        a.margins(x=0)
    fig.suptitle(f"SIMULATED · Transformer-1 · scenario {sid} — {name} · April 2026, 15-min, seed 0", fontsize=11)
    fig.tight_layout()
    FIG.mkdir(parents=True, exist_ok=True)
    out = FIG / f"scenario_{sid}.png"
    fig.savefig(out, dpi=110)
    plt.close(fig)
    return out


if __name__ == "__main__":
    for sid in sys.argv[1:] or SCENARIO_IDS:
        print(plot(sid))
