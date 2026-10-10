"""End to end: every fixture and scenario through adapter -> twin -> analytics, batch and streaming.

Streaming = Replay -> TwinEngine.step -> StreamAnalyzer.update, compared with the batch analyze() on the same rows.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from analytics.common import load_thresholds
from analytics.pipeline import StreamAnalyzer, analyze, analyze_snapshot
from contracts.canonical import CAPABILITY_KEYS
from eval.scenarios import KAGGLE_LOSSES, SCENARIOS, capabilities, effective_caps, load_scenario, normal_reference
from ingest.adapter import load
from sim.replay import Replay
from twin.engine import TwinEngine

ROOT = Path(__file__).resolve().parent.parent
FX = ROOT / "data" / "fixtures"
TH = load_thresholds()
FIXTURES = {
    "F1": [FX / "F1_canonical.csv"],
    "F2": sorted((ROOT / "data" / "raw" / "kaggle").glob("*.csv")),
    "F3": [FX / "F3_l1l2l3_fahrenheit_ddmm.csv"],
    "F4": [FX / "F4_excel_trend_events.xlsx"],
    "F6": [FX / "F6_line_line_kA.csv"],
    "F8": [FX / "F8_kva_only.csv"],
    "F15": [FX / "F15_organizer_style.xlsx"],
    "F15r": [FX / "F15r_organizer_records_no_time.xlsx"],
}


def _ids(alerts):
    return [(a.id, a.type, a.severity, a.origin, a.simulated) for a in alerts]


@pytest.mark.parametrize("fid", list(FIXTURES))
def test_every_fixture_runs_end_to_end(fid):
    kaggle = fid == "F2"
    ds = load(FIXTURES[fid], asset=None if kaggle else "config/asset.yaml",
              schema="config/schema/kaggle.yaml" if kaggle else None, simulated=not kaggle)
    asset = {**ds.asset, **KAGGLE_LOSSES} if kaggle else "config/asset.yaml"
    twin = TwinEngine(asset).run(ds)
    caps = effective_caps(ds.capabilities, twin)
    th = load_thresholds(asset=ds.asset) if kaggle else TH
    if ds.mode == "snapshot":
        ranked = analyze_snapshot(twin, caps, th)
        assert len(ranked) == len(ds.trend) and ranked["score"].between(0, 100).all()
        assert ranked["score"].is_monotonic_increasing and ranked["rank"].iloc[0] == 1
        return
    res = analyze(twin, ds.events, caps, th)
    assert 0 <= res.health.score <= 100
    assert all(a.simulated == (not kaggle) for a in res.alerts)
    assert set(CAPABILITY_KEYS) <= set(ds.capabilities)
    if kaggle:
        assert not [a for a in res.alerts if a.type == "residual_drift"]
        asset = [a for a in res.alerts if a.origin == "asset"]
        assert not [a for a in asset if a.module == "oil"]                       # drifting gauge: sensor alerts only
        assert all("twin-estimated" in a.explanation for a in asset if a.type == "top_oil_high")  # never measured OTI


@pytest.fixture(scope="module")
def ref():
    return normal_reference(TH)


@pytest.mark.parametrize("sid", SCENARIOS)
def test_replay_step_stream_matches_batch(sid, ref):
    """Replay -> step -> StreamAnalyzer equals batch analyze() at checkpoints (including the end)."""
    batch_twin, events = load_scenario(sid)
    caps = capabilities(sid)
    base = batch_twin.drop(columns=[c for c in batch_twin.columns if c.startswith("gt_")])
    trend = load_scenario(sid)[0][[c for c in base.columns if not c.startswith(("twin_", "rise_", "aging_", "days_",
                                                                                "residual_", "fidelity_", "load_pu",
                                                                                "twin", "implausible", "hs_",
                                                                                "ageing_", "dt_min"))]]
    engine = TwinEngine()
    sa = StreamAnalyzer(caps, TH, residual_reference=ref)
    ev = events.sort_values("timestamp").to_dict("records")
    checkpoints = {len(trend) // 3, 2 * len(trend) // 3, len(trend) - 1}
    k = 0
    for i, row in enumerate(Replay(trend, speed=None)):
        new = []
        while k < len(ev) and ev[k]["timestamp"] <= row["timestamp"]:
            new.append(ev[k])
            k += 1
        state = engine.step(row)
        if i in checkpoints:
            streamed = sa.update(state, new)
            prefix = batch_twin.iloc[: i + 1]
            batch = analyze(prefix, events[events["timestamp"] <= row["timestamp"]], caps, TH, residual_reference=ref)
            assert _ids(streamed.alerts) == _ids(batch.alerts), (sid, i)
            assert streamed.health.score == pytest.approx(batch.health.score), (sid, i)
            assert streamed.health.band == batch.health.band
        else:
            sa._rows.append({**state.row, **state.twin, "timestamp": state.timestamp})   # buffer without re-analysing
            sa._events.extend(new)
