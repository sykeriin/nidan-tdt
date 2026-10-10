"""Lead-time and false-alarm tables on the generated scenarios N, S1-S5 (generator -> adapter -> twin -> analytics).

Usage: python -m eval.run_eval
Writes docs/figures/lead_time.csv and docs/figures/lead_time.md.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from analytics.common import load_thresholds
from analytics.pipeline import analyze
from eval.false_alarms import false_alarms
from eval.lead_time import lead_times
from eval.scenarios import SCENARIOS, capabilities, ground_truth, load_scenario, normal_reference

OUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "figures"
HEADER = ("SIMULATED: generated campus data for Transformer-1 (sim/generator.py, seed 0), measured through the "
          "adapter, the nominal twin and the analytics pipeline. The plant is deliberately different from the twin. "
          "These numbers test the detectors on synthetic faults; they are not field evidence.")
DAYS = 30


def run() -> tuple[pd.DataFrame, dict]:
    """Return (lead-time table for all scenarios, false-alarm dict per scenario)."""
    thresholds = load_thresholds()
    ref = normal_reference(thresholds)
    frames, fa = [], {}
    for sc in SCENARIOS:
        trend, events = load_scenario(sc)
        alerts = analyze(trend, events, capabilities(sc), thresholds, residual_reference=ref).alerts
        gt = ground_truth(sc)
        lt = lead_times(alerts, gt, trend, thresholds)
        if lt.empty:
            lt = pd.DataFrame([{"fault": "none (Normal)", "detected": False}], columns=lt.columns)
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
    """Render both tables with the SIMULATED header."""
    cols = list(table.columns)
    lines = [HEADER, "", "## Lead time per injected fault", "", "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in table.iterrows():
        lines.append("| " + " | ".join(_fmt(r[c]) for c in cols) + " |")
    lines += [
        "",
        "Positive lead_vs_baseline_h: the twin/analytics alerted before the plain threshold. 'none' in baseline_ts means "
        "the plain threshold never alarmed. lead_vs_onset_h is measured against the ground-truth onset; negative = "
        "detected after onset. Overload, unbalance and theft are caught at the same moment as a plain threshold: the "
        "twin adds lead on cooling degradation and the slow leak.",
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
    table.to_csv(OUT_DIR / "lead_time.csv", index=False)
    md = to_markdown(table, fa)
    (OUT_DIR / "lead_time.md").write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
