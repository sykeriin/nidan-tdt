"""Ingestion fixtures (DATA_INGESTION_SPEC.md §5, Tier 1 subset) built from generated data, so truth is known.

    python -m sim.fixtures      # -> data/fixtures/

F1 canonical CSV · F2 Kaggle raw files (data/raw/kaggle, not copied) · F3 L1/L2/L3 + °F + DD/MM dates
F4 Excel: Trend + Events sheets · F8 kVA only, no temperatures · F6 line-line voltages + kA currents
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
GEN = ROOT / "data" / "generated"
FIX = ROOT / "data" / "fixtures"
I_RATED = 1391


def _n(days=7) -> pd.DataFrame:
    t = pd.read_csv(GEN / "trend_N.csv", parse_dates=["timestamp"])
    return t[t["timestamp"] < t["timestamp"].iloc[0] + pd.Timedelta(days=days)].reset_index(drop=True)


def _local(ts: pd.Series) -> pd.Series:
    return ts.dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)


def build(out=FIX) -> dict[str, Path]:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    n = _n()
    paths = {}

    paths["F1"] = out / "F1_canonical.csv"
    n.to_csv(paths["F1"], index=False)

    f3 = pd.DataFrame({
        "Date Time": _local(n["timestamp"]).dt.strftime("%d/%m/%Y %H:%M"),
        "L1 Current (A)": n["IR"], "L2 Current (A)": n["IY"], "L3 Current (A)": n["IB"],
        "L1 Voltage (V)": n["VR"], "L2 Voltage (V)": n["VY"], "L3 Voltage (V)": n["VB"],
        "Oil Temp (°F)": (n["OTI_C"] * 9 / 5 + 32).round(1), "Ambient (°F)": (n["ATI_C"] * 9 / 5 + 32).round(1)})
    paths["F3"] = out / "F3_l1l2l3_fahrenheit_ddmm.csv"
    f3.to_csv(paths["F3"], index=False, encoding="utf-8")

    s5 = pd.read_csv(GEN / "trend_S5.csv", parse_dates=["timestamp"])
    s5 = s5[s5["timestamp"] >= s5["timestamp"].iloc[0] + pd.Timedelta(days=23)].reset_index(drop=True)
    ev = pd.read_csv(GEN / "events_S5.csv", parse_dates=["timestamp"])
    trend_sheet = pd.DataFrame({
        "Timestamp": _local(s5["timestamp"]).dt.strftime("%d/%m/%Y %H:%M"),
        "IR (A)": s5["IR"], "IY (A)": s5["IY"], "IB (A)": s5["IB"],
        "VR (V)": s5["VR"], "VY (V)": s5["VY"], "VB (V)": s5["VB"], "OTI": s5["OTI_C"], "ATI": s5["ATI_C"]})
    event_sheet = pd.DataFrame({
        "Event Time": _local(ev["timestamp"]).dt.strftime("%d/%m/%Y %H:%M:%S"),
        "Event": "Through fault", "Phase": ev["phase"],
        "Peak Current (A)": (ev["peak_pu"] * I_RATED).round(0), "Duration (ms)": ev["duration_ms"]})
    paths["F4"] = out / "F4_excel_trend_events.xlsx"
    with pd.ExcelWriter(paths["F4"]) as xw:
        trend_sheet.to_excel(xw, sheet_name="Trend", index=False)
        event_sheet.to_excel(xw, sheet_name="Events", index=False)

    paths["F8"] = out / "F8_kva_only.csv"
    pd.DataFrame({"time": n["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%S%z"), "kVA": n["S_kVA"]}).to_csv(paths["F8"], index=False)

    sq3 = np.sqrt(3)
    f6 = pd.DataFrame({
        "Timestamp": _local(n["timestamp"]).dt.strftime("%Y-%m-%d %H:%M"),
        "I_R [kA]": (n["IR"] / 1000).round(5), "I_Y [kA]": (n["IY"] / 1000).round(5), "I_B [kA]": (n["IB"] / 1000).round(5),
        "V_RY": (n["VR"] * sq3).round(2), "V_YB": (n["VY"] * sq3).round(2), "V_BR": (n["VB"] * sq3).round(2),
        "Top Oil Temp": n["OTI_C"], "Ambient Temp": n["ATI_C"]})
    paths["F6"] = out / "F6_line_line_kA.csv"
    f6.to_csv(paths["F6"], index=False)

    paths["F2"] = ROOT / "data" / "raw" / "kaggle"
    return paths


if __name__ == "__main__":
    for k, v in build().items():
        print(k, v)
