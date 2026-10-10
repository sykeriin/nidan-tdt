"""TEST-ONLY loader for the real Kaggle transformer data. Stand-in until P1's ingestion adapter exists.

The dataset is third-party and licensed "copyright-authors": it is read from DT_KAGGLE_DIR at test time and is
NEVER copied into the repository. No rows are written to any committed file and no samples are embedded in tests.

Mapping (FINAL_PRD / DATA_INGESTION_SPEC synonyms): OTI->OTI_C, WTI->WTI_C, ATI->ATI_C and amb_C, OLI->OLI_pct,
IL1/IL2/IL3->IR/IY/IB, VL1/VL2/VL3->VR/VY/VB, I_mean = mean(IR,IY,IB). loading_pct is left absent (rating unknown).
OTI_A, OTI_T and MOG_A are device alarm outputs (label leakage): they are never read.
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

DEFAULT_DIR = r"C:\Apps\Power\dt-twin\data\raw\kaggle"
TZ = "Asia/Kolkata"
OVERVIEW_MAP = {"OTI": "OTI_C", "WTI": "WTI_C", "ATI": "ATI_C", "OLI": "OLI_pct"}  # OTI_A/OTI_T/MOG_A deliberately absent
CURVOLT_MAP = {"IL1": "IR", "IL2": "IY", "IL3": "IB", "VL1": "VR", "VL2": "VY", "VL3": "VB"}


def kaggle_dir() -> Path:
    return Path(os.environ.get("DT_KAGGLE_DIR", DEFAULT_DIR))


def available() -> bool:
    d = kaggle_dir()
    return (d / "Overview.csv").is_file() and (d / "CurrentVoltage.csv").is_file()


def _read(path: Path, mapping: dict[str, str], info: dict, tag: str) -> pd.DataFrame:
    raw = pd.read_csv(path, usecols=["DeviceTimeStamp", *mapping])  # only the mapped columns are ever read
    raw["timestamp"] = pd.to_datetime(raw.pop("DeviceTimeStamp")).dt.tz_localize(TZ)
    raw = raw.rename(columns=mapping)
    info[f"{tag}_rows"] = len(raw)
    dup1 = int(raw.timestamp.duplicated().sum())
    raw = raw.groupby("timestamp", as_index=False).median(numeric_only=True)  # median of duplicate timestamps
    raw["timestamp"] = raw.timestamp.dt.round("15min")
    dup2 = int(raw.timestamp.duplicated().sum())
    raw = raw.groupby("timestamp", as_index=False).median(numeric_only=True)
    info[f"{tag}_duplicate_timestamps_removed"] = dup1
    info[f"{tag}_rows_merged_by_15min_rounding"] = dup2
    return raw


def load_kaggle(directory: str | Path | None = None) -> tuple[pd.DataFrame, dict]:
    """Return (canonical-ish trend frame, info dict with the dedupe counts)."""
    d = Path(directory) if directory else kaggle_dir()
    info: dict = {}
    ov = _read(d / "Overview.csv", OVERVIEW_MAP, info, "overview")
    cv = _read(d / "CurrentVoltage.csv", CURVOLT_MAP, info, "currentvoltage")
    df = ov.merge(cv, on="timestamp", how="outer").sort_values("timestamp").reset_index(drop=True)
    df["amb_C"] = df["ATI_C"]
    df["I_mean"] = df[["IR", "IY", "IB"]].mean(axis=1, skipna=False)
    df["source"] = "kaggle_real"
    df["simulated"] = False
    info["rows"] = len(df)
    return df, info
