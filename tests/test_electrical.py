import numpy as np
import pandas as pd

from analytics import electrical
from analytics.common import load_thresholds
from eval.scenarios import ground_truth, load_scenario, capabilities

TH = load_thresholds()
SEVERE = {"warning", "critical"}
V = TH["reference"]["v_ln_nominal_v"]


def _frame(**cols):
    n = len(next(iter(cols.values())))
    df = pd.DataFrame(cols)
    df.insert(0, "timestamp", pd.date_range("2026-01-01", periods=n, freq="15min", tz="Asia/Kolkata"))
    df["simulated"] = True
    return df


def test_unbalance_formula():
    df = _frame(IR=[110.0], IY=[90.0], IB=[100.0])
    assert electrical.unbalance_pct(df).iloc[0] == 10.0


def test_unbalance_nan_when_phase_missing():
    df = _frame(IR=[100.0], IY=[100.0])
    assert electrical.unbalance_pct(df).isna().all()
    df2 = _frame(IR=[100.0, np.nan], IY=[100.0, 100.0], IB=[100.0, 100.0])
    u = electrical.unbalance_pct(df2)
    assert u.iloc[0] == 0.0 and np.isnan(u.iloc[1])


def test_normal_has_no_alerts():
    trend, _ = load_scenario("N")
    assert [a for a in electrical.detect(trend, TH, capabilities()) if a.severity in SEVERE] == []


def test_unbalance_scenario_flags_current_unbalance():
    trend, _ = load_scenario("S3")
    alerts = electrical.detect(trend, TH, capabilities())
    cu = [a for a in alerts if a.type == "current_unbalance"]
    assert cu and all(a.severity == "warning" for a in cu)
    assert "no neutral" in cu[0].explanation
    assert cu[0].module == "electrical"


def test_unbalance_alerts_only_from_onset():
    trend, _ = load_scenario("S3")
    cu = [a for a in electrical.detect(trend, TH, capabilities()) if a.type == "current_unbalance"]
    onset = ground_truth("S3")[0]["onset"]
    assert cu and all(a.timestamp >= onset for a in cu)
    assert onset <= cu[0].timestamp <= onset + pd.Timedelta(hours=2)


def test_thresholds_and_hysteresis():
    # 12 % then hovering 9.8-10.4 % (above the 9.5 clear level), then 25 % -> warning once, critical once
    bump = [100 + 12.0, 100 + 10.4, 100 + 9.8, 100 + 10.2]
    ir = np.array([100.0] * 2 + bump + [100.0] * 2 + [140.0] + [100.0])
    df = _frame(IR=ir + 0.0, IY=np.full(len(ir), 100.0), IB=np.full(len(ir), 100.0))
    df["IY"] = 2 * 100.0 - df["IR"] + 100.0 - 100.0  # keep the mean at 100 A
    df["IB"] = 100.0
    alerts = [a for a in electrical.detect(df, TH, capabilities()) if a.type == "current_unbalance"]
    assert [a.severity for a in alerts][-1] == "critical"
    assert sum(a.severity == "warning" for a in alerts) <= 2


def test_no_chatter_around_warning_level():
    n = 20
    dev = np.array([10.5, 9.8] * (n // 2))
    df = _frame(IR=100.0 + dev, IY=100.0 - dev, IB=np.full(n, 100.0))
    alerts = [a for a in electrical.detect(df, TH, capabilities()) if a.type == "current_unbalance"]
    assert len(alerts) == 1


def test_voltage_alerts():
    v = np.array([1.0, 1.0, 1.08, 1.08, 1.0, 0.9, 0.9, 1.0]) * V
    df = _frame(IR=np.full(8, 100.0), IY=np.full(8, 100.0), IB=np.full(8, 100.0), VR=v, VY=v, VB=v)
    types = [a.type for a in electrical.detect(df, TH, capabilities())]
    assert types.count("voltage_high") == 1 and types.count("voltage_low") == 1
    assert "voltage_unbalance" not in types


def test_voltage_unbalance():
    n = 6
    df = _frame(VR=np.full(n, V * 1.0), VY=np.full(n, V * 1.0), VB=np.full(n, V * 0.94))
    a = [x for x in electrical.detect(df, TH, capabilities()) if x.type == "voltage_unbalance"]
    assert len(a) == 1 and a[0].severity == "critical"


def test_caps_gate_and_missing_channels():
    trend, _ = load_scenario("S3")
    caps = capabilities() | {"unbalance": False, "voltage_quality": False}
    assert electrical.detect(trend, TH, caps) == []
    no_v = trend.drop(columns=["VR", "VY", "VB"])
    types = {a.type for a in electrical.detect(no_v, TH, capabilities())}
    assert types == {"current_unbalance"}
    assert electrical.detect(trend.iloc[0:0], TH, capabilities()) == []
    assert electrical.detect(trend[["timestamp"]], TH, capabilities()) == []


def test_nan_voltage_channel_disables_voltage_rules():
    trend, _ = load_scenario("N")
    trend[["VR", "VY", "VB"]] = np.nan
    assert electrical.detect(trend, TH, capabilities()) == []
