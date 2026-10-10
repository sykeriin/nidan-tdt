"""Replay (PRD §12.2): same seed -> same stream; replay + step() == batch run; timing follows speed."""
import numpy as np
import pandas as pd
import pytest

from ingest.adapter import load
from sim.replay import Replay
from twin.engine import TwinEngine
from twin.plot import ROOT, load_generated

COLS = ["twin_oil_C", "twin_hs_C", "residual_oil_C", "fidelity_rmse_C", "days_aged_actual_cum"]


@pytest.fixture(scope="module")
def n():
    return load_generated("N").iloc[:300].reset_index(drop=True)


def test_same_seed_same_stream(n):
    a = [r["timestamp"] for r in Replay(n, speed=None, seed=7, dropout=0.1)]
    b = [r["timestamp"] for r in Replay(n, speed=None, seed=7, dropout=0.1)]
    c = [r["timestamp"] for r in Replay(n, speed=None, seed=8, dropout=0.1)]
    assert a == b and a != c
    assert 0.8 * len(n) < len(a) < len(n)


def test_rows_are_canonical_and_tagged(n):
    row = next(iter(Replay(n, speed=None)))
    assert row["source"] == "replay" and row["replay_of"] == "generated_sim" and row["simulated"]
    assert {"timestamp", "I_mean", "amb_C", "OTI_C"} <= set(row)


def test_replay_through_step_equals_batch(n):
    e = TwinEngine()
    streamed = pd.DataFrame([e.step(r).twin for r in Replay(n, speed=None)])
    batch = TwinEngine().run(n)
    for c in COLS:
        np.testing.assert_allclose(streamed[c].to_numpy(float), batch[c].to_numpy(float), rtol=1e-9, atol=1e-9,
                                   equal_nan=True, err_msg=c)


def test_dropout_stream_equals_batch_on_surviving_rows(n):
    rp = Replay(n, speed=None, seed=3, dropout=0.2)
    e = TwinEngine()
    streamed = pd.DataFrame([e.step(r).twin for r in rp])
    batch = TwinEngine().run(n[rp.kept()].reset_index(drop=True))
    for c in COLS:
        np.testing.assert_allclose(streamed[c].to_numpy(float), batch[c].to_numpy(float), rtol=1e-9, atol=1e-9,
                                   equal_nan=True, err_msg=c)


def test_speed_controls_sleep(n):
    waits = []
    list(Replay(n.iloc[:5], speed=900, sleep=waits.append))
    assert waits == pytest.approx([1.0] * 4)          # 15-min rows at 900x -> 1 s apart


def test_replay_from_adapter_dataset():
    ds = load([ROOT / "data" / "fixtures" / "F3_l1l2l3_fahrenheit_ddmm.csv"], simulated=True)
    rows = list(Replay(ds, speed=None, start="2026-04-02", end="2026-04-02 23:59"))
    assert len(rows) == 96 and all(r["source"] == "replay" for r in rows)


def test_start_and_end_accept_tz_aware_and_naive_times():
    """The HTTP replay endpoint passes tz-aware times; plain naive times mean the data's own zone."""
    import pandas as pd
    from dt import api
    naive = [r.timestamp for r in api.replay("S2", speed=None, start="2026-04-19T00:00:00", end="2026-04-19T06:00:00")]
    aware = [r.timestamp for r in api.replay("S2", speed=None, start=pd.Timestamp("2026-04-19 00:00", tz="Asia/Kolkata"), end=pd.Timestamp("2026-04-19 00:30", tz="UTC"))]
    assert len(aware) == 25 and aware[0] == pd.Timestamp("2026-04-19 00:00", tz="Asia/Kolkata")
    assert len(naive) == 25
