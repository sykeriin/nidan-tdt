"""Physics plausibility check (replaces the fitted twin): catches a top-oil sensor that can't be reading top-oil."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from contracts.canonical import validate
from ingest.enrich import load_weather
from twin.plausibility import BANDS, add_flags, check, steady_rise

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def normal():
    t = pd.read_csv(ROOT / "data" / "generated" / "trend_N.csv", parse_dates=["timestamp"])
    t["timestamp"] = t["timestamp"].dt.tz_convert("Asia/Kolkata")
    t["dq_flags"] = t["dq_flags"].fillna("")
    return t


@pytest.fixture(scope="module")
def kaggle():
    return pd.read_parquet(ROOT / "data" / "clean" / "kaggle.parquet")


def test_steady_state_matches_library_defaults():
    # nominal band = library ONAN defaults: 60 K + 10 K surcharge at rated load
    assert steady_rise(1.0, **BANDS["nominal"]) == pytest.approx(70.0)
    assert steady_rise(0.5, **BANDS["low"]) < steady_rise(0.5, **BANDS["nominal"]) < steady_rise(0.5, **BANDS["high"])


def test_normal_is_plausible(normal):
    r = check(normal, 1391, load_weather())
    assert r.verdict == {"OTI_C": "plausible", "ATI_C": "plausible"}
    assert r.summary["rise"]["implausible_fraction"] < 0.02
    assert r.summary["ambient"]["mismatch_rows"] == 0


def test_oti_not_reading_top_oil_is_caught(normal):
    bad = normal.copy()
    bad["OTI_C"] = bad["ATI_C"] + 2.0          # what the Kaggle sensor looks like
    r = check(bad, 1391)
    assert r.verdict["OTI_C"] == "suspect"
    assert r.summary["rise"]["below_band"] > 0.9 * r.summary["rise"]["evaluable_rows"]


def test_runaway_rise_is_caught(normal):
    hot = normal.copy()
    hot["OTI_C"] = hot["ATI_C"] + 120          # far above even a lossy kiosk unit
    assert check(hot, 1391).verdict["OTI_C"] == "suspect"


def test_ambient_offset_is_caught(normal):
    off = normal.copy()
    off["ATI_C"] = off["ATI_C"] + 12           # e.g. sensor inside a hot enclosure
    r = check(off, 1391, load_weather())
    assert r.verdict["ATI_C"] == "suspect"
    assert r.summary["ambient"]["mismatch_rows"] > 0


def test_no_oti_means_not_checked(normal):
    r = check(normal.drop(columns=["OTI_C"]), 1391)
    assert r.verdict["OTI_C"] == "not checked"
    assert not r.rows["implausible"].any()


def test_flags_added_without_dropping_rows(normal):
    bad = normal.copy()
    bad["OTI_C"] = bad["ATI_C"] + 2.0
    out = add_flags(bad, check(bad, 1391))
    assert len(out) == len(bad)
    assert out["dq_flags"].str.contains("IMPLAUSIBLE_RISE").mean() > 0.9
    assert validate(out) == []


def test_kaggle_verdict_and_flags(kaggle):
    """The real finding: Kaggle OTI is too close to ambient for any oil-immersed unit at that load."""
    r = check(kaggle, 214.7, load_weather(site="hyderabad"))
    assert r.verdict == {"OTI_C": "suspect", "ATI_C": "plausible"}
    s = r.summary["rise"]
    assert s["observed_rise_median_K"] < s["predicted_low_median_K"] - 4
    assert s["below_band_vs_weather_fraction"] > 0.5      # also true against Open-Meteo air temperature
    assert r.summary["rating_sensitivity"]["x5"] > s["observed_rise_median_K"] + 2   # a bigger nameplate doesn't rescue it
    assert kaggle["dq_flags"].str.contains("IMPLAUSIBLE_RISE").sum() == s["implausible_rows"]
    assert validate(kaggle) == []


def test_runs_offline(no_network, normal):
    assert check(normal, 1391, load_weather()).verdict["OTI_C"] == "plausible"
