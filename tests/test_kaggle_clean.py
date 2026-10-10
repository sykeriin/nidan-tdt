"""Kaggle cleaning (DATA_INGESTION_SPEC.md §2-3): merged, deduped, flagged, canonical, nothing deleted."""
from pathlib import Path

import pandas as pd
import pytest
import yaml

from contracts.canonical import validate

ROOT = Path(__file__).resolve().parent.parent
PARQUET = ROOT / "data" / "clean" / "kaggle.parquet"
RAW = ROOT / "data" / "raw" / "kaggle"
SCHEMA = yaml.safe_load((ROOT / "config" / "schema" / "kaggle.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def k():
    if not PARQUET.exists():
        from ingest import kaggle_clean
        kaggle_clean.main()
    return pd.read_parquet(PARQUET)


def codes(df, code):
    return df["dq_flags"].str.split(";").apply(lambda xs: code in xs)


def test_canonical_contract(k):
    assert validate(k) == []
    assert (k["source"] == "kaggle_real").all() and not k["simulated"].any()
    assert str(k["timestamp"].dt.tz) == "Asia/Kolkata"


def test_date_range(k):
    assert k["timestamp"].min() >= pd.Timestamp(SCHEMA["range"]["start"], tz="Asia/Kolkata")
    assert k["timestamp"].max() <= pd.Timestamp(SCHEMA["range"]["end"], tz="Asia/Kolkata")


def test_no_rows_deleted(k):
    """Every distinct timestamp from any file inside the range survives (flagged rows kept)."""
    ts = set()
    for f in RAW.glob("*.csv"):
        ts |= set(pd.to_datetime(pd.read_csv(f, usecols=["DeviceTimeStamp"])["DeviceTimeStamp"]))
    s = pd.Series(sorted(ts)).dt.tz_localize("Asia/Kolkata")
    lo = pd.Timestamp(SCHEMA["range"]["start"], tz="Asia/Kolkata")
    hi = pd.Timestamp(SCHEMA["range"]["end"], tz="Asia/Kolkata")
    assert len(k) == ((s >= lo) & (s <= hi)).sum()
    assert k["timestamp"].is_unique


def test_duplicates_flagged(k):
    assert codes(k, "DUP_CONFLICT").sum() > 0
    assert codes(k, "DUP_IDENT").sum() > 0


def test_rybnames_and_wti_is_not_a_temperature(k):
    for c in ("IR", "IY", "IB", "VR", "VY", "VB", "OTI_C", "ATI_C", "OLI_pct", "IN"):
        assert c in k
    assert "WTI_C" not in k
    assert set(k["alarm_WTI"].dropna().unique()) <= {0.0, 1.0}
    assert k["VR"].median() == pytest.approx(240, abs=10)  # phase-neutral


def test_oti_glitches_kept_and_flagged(k):
    hot = k["OTI_C"] > 150
    assert hot.sum() > 0 and codes(k, "RANGE_OTI_C")[hot].all()
    assert codes(k, "JUMP_OTI").sum() > 0
    assert codes(k, "GAP").sum() > 0


def test_saturated_oil_level_flagged_stuck(k):
    late = k[k["timestamp"] >= pd.Timestamp("2019-12-01", tz="Asia/Kolkata")]
    assert codes(late, "STUCK_OLI").mean() > 0.9


def test_estimated_rating_not_transformer1(k):
    i_rated = (k["I_mean"] / (k["loading_pct"] / 100)).median()
    assert 180 < i_rated < 260  # estimated from data, nowhere near Transformer-1's 1391 A
