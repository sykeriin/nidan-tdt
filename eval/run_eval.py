"""Run the detectors on every mock scenario and write the lead-time and false-alarm tables.

Usage: python -m eval.run_eval
Writes docs/figures/lead_time_mock.csv and docs/figures/lead_time_mock.md.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pandas as pd

from analytics.common import load_thresholds, strip_quarantined
from analytics.pipeline import analyze
from eval.false_alarms import false_alarms
from eval.lead_time import lead_times
from tests.mock_data import SCENARIOS, ground_truth, make_mock, mock_caps

OUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "figures"
HEADER = "MOCK DATA, simulated: results below prove the detectors on a stand-in dataset, not on real or P2-generated data."
DAYS = 30


def _residual_reference(thresholds: dict) -> dict | None:
    """Calibrate the residual detector on the Normal mock, if the pipeline accepts a reference."""
    if "residual_reference" not in inspect.signature(analyze).parameters:
        return None
    from analytics import residual

    normal, _ = make_mock("N")
    return residual.calibrate(strip_quarantined(normal), thresholds)


def run() -> tuple[pd.DataFrame, dict]:
    """Return (lead-time table for all scenarios, false-alarm dict per scenario)."""
    thresholds = load_thresholds()
    caps = mock_caps()
    ref = _residual_reference(thresholds)
    kwargs = {"residual_reference": ref} if ref is not None else {}
    frames, fa = [], {}
    for sc in SCENARIOS:
        trend, events = make_mock(sc)
        alerts = analyze(trend, events, caps, thresholds, **kwargs).alerts
        gt = ground_truth(sc)
        lt = lead_times(alerts, gt, trend, thresholds)
        lt.insert(0, "scenario", sc)
        frames.append(lt)
        fa[sc] = false_alarms(alerts, gt, days=DAYS)
    return pd.concat(frames, ignore_index=True), fa


def _fmt(x: object) -> str:
    if x is None or x is pd.NaT or (isinstance(x, float) and pd.isna(x)):
        return "none"
    if isinstance(x, float):
        return f"{x:.2f}"
    if isinstance(x, pd.Timestamp):
        return x.strftime("%Y-%m-%d %H:%M")
    return str(x)


def to_markdown(table: pd.DataFrame, fa: dict) -> str:
    """Render both tables with the mock-data header."""
    cols = list(table.columns)
    lines = [HEADER, "", "## Lead time per injected fault", "", "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in table.iterrows():
        lines.append("| " + " | ".join(_fmt(r[c]) for c in cols) + " |")
    lines += [
        "",
        "Positive lead_vs_baseline_h: the twin alerted before the plain threshold. 'none' in baseline_ts means the plain "
        "threshold never alarmed, so there is no lead number to quote. Negative lead_vs_onset_h: detected after onset.",
        "",
        "## False alarms (warning/critical alerts matching no injected fault)",
        "",
        "| scenario | false alarms | true positives | alerts/week | by type |",
        "|---|---|---|---|---|",
    ]
    for sc, v in fa.items():
        lines.append(f"| {sc} | {v['count']} | {v['true_positive_count']} | {v['alerts_per_week']:.2f} | {v['by_type'] or 'none'} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    table, fa = run()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    table.to_csv(OUT_DIR / "lead_time_mock.csv", index=False)
    md = to_markdown(table, fa)
    (OUT_DIR / "lead_time_mock.md").write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
