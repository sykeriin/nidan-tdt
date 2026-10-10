"""Clean the Kaggle files through the adapter and write data/clean/kaggle.parquet.

    python -m ingest.kaggle_clean

Uses config/schema/kaggle.yaml (mapping + date range). Flagged rows are kept.
Prints every count that goes into data/PROVENANCE.md.
"""
import json
from pathlib import Path

from ingest.adapter import load

ROOT = Path(__file__).resolve().parent.parent
FILES = ["CurrentVoltage", "Overview", "Power", "PowerFactor", "TotalPower"]


def main():
    paths = [ROOT / "data" / "raw" / "kaggle" / f"{f}.csv" for f in FILES]
    ds = load(paths, schema="config/schema/kaggle.yaml")
    out = ROOT / "data" / "clean" / "kaggle.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    ds.trend.to_parquet(out, index=False)
    h = ds.health_report
    report = {k: h[k] for k in ("tables", "dedupe", "merge", "interval", "rows_after_cleaning", "time_span",
                                "flag_counts", "derived", "enrichment", "capabilities", "mode",
                                "nameplate_source", "warnings")}
    report["asset"] = {k: ds.asset.get(k) for k in ("i_rated_A", "rating_kVA", "lv_voltage_V", "nameplate_source")}
    (out.parent / "kaggle_health_report.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    print(json.dumps(report, indent=1, default=str))
    print("wrote", out, ds.trend.shape)


if __name__ == "__main__":
    main()
