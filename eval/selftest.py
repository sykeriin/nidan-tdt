"""Self-test: every validation number in the docs comes from here.

    python -m eval.selftest            # full run, about 3 minutes; writes data/validation.json and docs/TEST_REPORT.md
    python -m eval.selftest --quick    # 3 seeds instead of 10, about a minute

Seeds are fixed, so the numbers are reproducible. What is measured: false alarms on healthy months (two plant models),
detection delay and lead time for each injected fault, how often the diagnosis ranks the injected fault first, ingestion of
every fixture, the HTTP contract, speed on real-size data, closed-form physics against the library, and the frontend
type-check. What is NOT measured here: field accuracy (there is no field data with known faults) and long-run stability.
Everything generated is synthetic; results on it are regression evidence, not field performance.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SCENARIOS = ("S1", "S2", "S3", "S4a", "S4b", "S5")
EXPECTED_CLASS = {"S1": "overload", "S2": "cooling", "S3": "unbalance", "S4a": "oil", "S4b": "oil", "S5": "short_circuit"}
PLANTS = ("iec", "detailed")
PLANT_LABEL = {"iec": "standard (IEC) plant", "detailed": "detailed heat-balance plant"}


def _cleanup(ids):
    from dt import api
    for i in ids:
        api._MEM.pop(i, None)
        shutil.rmtree(api.RUNS / i, ignore_errors=True)


def _run(scenario: str, seed: int, plant: str, tag: str):
    """A full-pipeline run for one scenario, exactly as the app builds one (adapter, twin, analytics)."""
    from dt import api
    from twin import profile
    asset = profile.resolve({"rating_kVA": 1000, "lv_voltage_V": 415})
    did = f"u-st-{tag}"
    api.simulate(scenario, asset, None, seed=seed, name=did, dataset_id=did, plant=plant)
    return api.get_run(did), did


def _onset(run, scenario: str):
    if scenario == "S5":
        return run.events["timestamp"].min() if len(run.events) else None
    t = run.trend
    g = t.loc[t["gt_fault"] == 1, "timestamp"] if "gt_fault" in t else pd.Series(dtype="datetime64[ns]")
    return g.min() if len(g) else None


def _t1_false_alarms(seeds: int) -> dict:
    out = {}
    for plant in PLANTS:
        counts, rmse, bad_brief = [], [], []
        for seed in range(1, seeds + 1):
            run, did = _run("N", seed, plant, f"n{plant[0]}{seed}")
            asset_alerts = [a for a in run.analysis.alerts if a.origin == "asset" and a.severity != "info"]
            counts.append(len(asset_alerts))
            r = run.trend["residual_oil_C"].dropna()
            rmse.append(float(np.sqrt((r ** 2).mean())))
            from analytics import brief
            ts = run.trend["timestamp"]
            probe = [ts.iloc[int(len(ts) * f)] for f in np.linspace(0.15, 0.95, 12)]
            bad_brief.append(sum(brief.brief(run, t)["level"] != "good" for t in probe) / len(probe))
            _cleanup([did])
        out[plant] = {"seeds": seeds, "asset_alerts_per_month": counts, "total_false_alarms": int(sum(counts)),
                      "twin_rmse_K_mean": round(float(np.mean(rmse)), 2), "twin_rmse_K_max": round(float(np.max(rmse)), 2),
                      "brief_not_good_fraction": round(float(np.mean(bad_brief)), 3)}
    return out


def _t2_t3_detection_and_diagnosis(seeds: int) -> tuple[dict, dict]:
    from analytics import brief
    from eval.lead_time import alert_matches_fault, baseline_crossings
    from eval.scenarios import EXPECT, FAULT
    from analytics.common import load_thresholds
    th = load_thresholds()
    detect: dict = {}
    diag_hits: dict = defaultdict(lambda: [0, 0])
    confusion: dict = defaultdict(Counter)
    for plant in PLANTS:
        for sid in SCENARIOS:
            delays, lead, miss = [], [], 0
            for seed in range(0, seeds):
                run, did = _run(sid, seed, plant, f"{sid}{plant[0]}{seed}")
                onset = _onset(run, sid)
                fault = FAULT[sid]
                gt = {"fault": fault, "onset": onset, "end": run.trend["timestamp"].max(), "expect": list(EXPECT[fault])}
                matches = sorted((a for a in run.analysis.alerts if a.origin == "asset" and alert_matches_fault(a, gt)), key=lambda a: a.timestamp)
                if not matches or onset is None:
                    miss += 1
                    _cleanup([did])
                    continue
                first = matches[0]
                delays.append((first.timestamp - onset) / pd.Timedelta(hours=1))
                base = baseline_crossings(run.trend, th, since=onset)
                rules = {"overload": ("loading_alarm", "overcurrent"), "cooling_degradation": ("top_oil_warning",), "unbalance": ("unbalance_warning",),
                         "oil_leak": ("oil_level_low",), "oil_theft": ("oil_level_low",), "through_fault": ()}[fault]
                ts_ = [base.get(r) for r in rules if base.get(r) is not None]
                if ts_:
                    lead.append((min(ts_) - first.timestamp) / pd.Timedelta(hours=1))
                else:
                    lead.append(float("nan"))
                for h in (6, 24, 48):
                    t = first.timestamp + pd.Timedelta(hours=h)
                    if t <= run.trend["timestamp"].max():
                        top = brief.brief(run, t)["diagnosis"]
                        top = next((d for d in top if d["observable"]), None)
                        label = top["fault"] if top and top["evidence"] >= 0.3 else "none"
                        diag_hits[(plant, sid)][1] += 1
                        diag_hits[(plant, sid)][0] += int(label == EXPECTED_CLASS[sid])
                        confusion[(plant, EXPECTED_CLASS[sid])][label] += 1
                _cleanup([did])
            lead_arr = np.array(lead, dtype=float)
            never = int(np.isnan(lead_arr).sum())
            detect[f"{plant}/{sid}"] = {
                "plant": plant, "scenario": sid, "fault": fault, "runs": seeds, "missed": miss,
                "delay_h_median": None if not delays else round(float(np.median(delays)), 1),
                "delay_h_max": None if not delays else round(float(np.max(delays)), 1),
                "lead_vs_plain_threshold_h_median": None if len(lead_arr) == never else round(float(np.nanmedian(lead_arr)), 1),
                "plain_threshold_never_fires_in": never,
            }
    diag = {f"{p}/{s}": {"plant": p, "scenario": s, "expected": EXPECTED_CLASS[s], "correct": h[0], "of": h[1], "top1_accuracy": None if not h[1] else round(h[0] / h[1], 3)}
            for (p, s), h in diag_hits.items()}
    conf = {f"{p}/{c}": dict(v) for (p, c), v in confusion.items()}
    return detect, {"per_scenario": diag, "confusion": conf}


def _t5_adapter() -> dict:
    from ingest import adapter
    rows = {}
    for f in sorted((ROOT / "data" / "fixtures").glob("*")):
        if f.suffix.lower() not in (".csv", ".xlsx", ".tsv", ".xls"):
            continue
        t = time.time()
        try:
            ds = adapter.load([str(f)])
            rows[f.name] = {"ok": True, "mode": ds.mode, "rows": int(len(ds.trend)), "capabilities_on": int(sum(ds.capabilities.values())), "seconds": round(time.time() - t, 2)}
        except Exception as e:   # noqa: BLE001  the point is to record every failure
            rows[f.name] = {"ok": False, "error": str(e)[:160]}
    return {"files": rows, "all_ok": all(v["ok"] for v in rows.values()), "count": len(rows)}


def _t6_api() -> dict:
    from fastapi.testclient import TestClient
    from server import app as appmod
    c = TestClient(appmod.app)
    results = {}

    def hit(name, resp, ok=(200, 201)):
        results[name] = resp.status_code
        return resp.status_code in ok

    ids = [d["dataset_id"] for d in c.get("/api/datasets").json()]
    hit("GET /api/datasets", c.get("/api/datasets"))
    t = "2026-04-24T14:00:00"
    for did in ("N", "S2", "kaggle"):
        if did not in ids:
            continue
        ts = t if did != "kaggle" else "2019-09-01T12:00:00"
        hit(f"GET /api/datasets/{did}/run", c.get(f"/api/datasets/{did}/run"))
        hit(f"GET /api/datasets/{did}/state", c.get(f"/api/datasets/{did}/state", params={"t": ts}))
        hit(f"GET /api/datasets/{did}/brief", c.get(f"/api/datasets/{did}/brief", params={"t": ts}))
        hit(f"GET /api/datasets/{did}/outlook", c.get(f"/api/datasets/{did}/outlook", params={"t": ts}))
        for fmt in ("html", "csv", "json"):
            hit(f"GET /api/datasets/{did}/report?fmt={fmt}", c.get(f"/api/datasets/{did}/report", params={"fmt": fmt}))
    hit("GET /api/self-test", c.get("/api/self-test"))
    hit("GET /api/presets", c.get("/api/presets"))
    body = {"values": {"rating_kVA": 1000, "lv_voltage_V": 415}}
    hit("POST /api/profile", c.post("/api/profile", json=body))
    hit("POST /api/physics/chain", c.post("/api/physics/chain", json=body))
    hit("POST /api/physics/step", c.post("/api/physics/step", json=body))
    hit("POST /api/physics/detailed", c.post("/api/physics/detailed", json=body))
    hit("GET /api/physics/ageing-models", c.get("/api/physics/ageing-models"))
    hit("POST /api/datasets/S2/whatif", c.post("/api/datasets/S2/whatif", json={"load_mult": 1.1}))
    errors = {
        "unknown dataset -> 404": c.get("/api/datasets/nope/run").status_code == 404,
        "bad time -> 422": c.get("/api/datasets/S2/brief", params={"t": "x"}).status_code == 422,
        "bad report format -> 400": c.get("/api/datasets/S2/report", params={"fmt": "pdf"}).status_code == 400,
        "negative rating -> 400": c.post("/api/profile", json={"values": {"rating_kVA": -1}}).status_code == 400,
        "errors carry a readable detail": "detail" in c.get("/api/datasets/nope/run").json(),
    }
    return {"endpoints": results, "all_ok": all(v in (200, 201) for v in results.values()), "error_cases": errors, "errors_ok": all(errors.values())}


def _t7_performance() -> dict:
    from dt import api
    t = time.time()
    run = api._build_cached("kaggle")
    secs = time.time() - t
    rows = int(len(run.trend))
    t = time.time()
    api._build_cached("S2")
    s2 = time.time() - t
    return {"kaggle_rows": rows, "kaggle_seconds": round(secs, 1), "scenario_rows": 2880, "scenario_seconds": round(s2, 1),
            "note": "adapter output through twin, analytics and Health Index; excludes the Monte Carlo outlook"}


def _physics_check() -> dict:
    from twin import physics, profile
    worst = 0.0
    for raw in ({"rating_kVA": 250}, {"rating_kVA": 1000}, {"rating_kVA": 1250, "lv_voltage_V": 433, "top_oil_rise_K": 40}, {"rating_kVA": 1600}):
        a = profile.resolve(raw)
        for k in (0.0, 0.3, 0.7, 1.0, 1.25):
            worst = max(worst, physics.steady_chain(a, k, 32.0)["library_check"]["max_abs_diff_K"])
    return {"max_abs_difference_K": round(worst, 4), "ratings": [250, 1000, 1250, 1600], "loads_pu": [0.0, 0.3, 0.7, 1.0, 1.25],
            "meaning": "closed-form IEC 60076-7 equations shown on the Physics page against the thermal library's steady state"}


def _t10_frontend() -> dict:
    web = ROOT / "web"
    if not (web / "node_modules").exists():
        return {"ran": False, "reason": "web/node_modules not installed"}
    npx = "npx.cmd" if sys.platform.startswith("win") else "npx"
    try:
        r = subprocess.run([npx, "tsc", "-b"], cwd=web, capture_output=True, text=True, timeout=240)
        return {"ran": True, "typecheck_passed": r.returncode == 0, "output": (r.stdout + r.stderr)[-300:], "build_present": (web / "dist" / "index.html").exists()}
    except Exception as e:   # noqa: BLE001
        return {"ran": False, "reason": str(e)[:160]}


def run_all(quick: bool = False) -> dict:
    seeds_n, seeds_f = (3, 2) if quick else (10, 5)
    t0 = time.time()
    t2, t3 = None, None
    res: dict = {"generated": datetime.now().astimezone().isoformat(timespec="seconds"), "quick": quick,
                 "synthetic": True}
    res["T1_false_alarms"] = _t1_false_alarms(seeds_n)
    t2, t3 = _t2_t3_detection_and_diagnosis(seeds_f)
    res["T2_detection"] = t2
    res["T3_diagnosis"] = t3
    res["T5_adapter"] = _t5_adapter()
    res["T6_api"] = _t6_api()
    res["T7_performance"] = _t7_performance()
    res["T_physics"] = _physics_check()
    res["T10_frontend"] = _t10_frontend()
    res["not_measured"] = ["Field accuracy: there is no field data with known faults.", "Long-run (soak) stability.",
                           "Calibration recovery and hold-out error: the twin is not fitted to data, so there is nothing to recover or hold out."]
    res["seconds"] = round(time.time() - t0, 1)
    return res


# ---------------------------------------------------------------- report
def _fmt(v, unit=""):
    return "none fired" if v is None else f"{v}{unit}"


def to_markdown(r: dict) -> str:
    L = ["# Test report", "",
         f"Generated by `python -m eval.selftest{' --quick' if r['quick'] else ''}` on {r['generated']} ({r['seconds']} s). Seeds are fixed, so the numbers repeat.",
         "", "**Everything here is measured on generated (synthetic) data and on the repository's fixtures. These are regression results, not field performance.**", ""]
    t1 = r["T1_false_alarms"]
    L += ["## T1 False alarms on healthy months", "",
          "A healthy 30-day month at 15-minute resolution, different random seeds. An alert counts as false if it is an asset-origin warning or critical alert on a month with no injected fault. The 'looks unhealthy' column is how often the plain-language status was not 'good' at 12 probe times through the month.", "",
          "| Plant model | Months | False asset alerts (total) | Alerts per month | Twin error, mean RMSE (K) | Worst month (K) | Status not 'good' |", "|---|---|---|---|---|---|---|"]
    for p, v in t1.items():
        L.append(f"| {PLANT_LABEL[p]} | {v['seeds']} | {v['total_false_alarms']} | {v['asset_alerts_per_month']} | {v['twin_rmse_K_mean']} | {v['twin_rmse_K_max']} | {v['brief_not_good_fraction'] * 100:.0f} % |")
    L += ["", "The detailed plant is a different physical model from the twin (heat balance with temperature-dependent losses), so its twin error is real model-form error rather than perturbed parameters.", ""]
    L += ["## T2 Detection delay and lead time", "",
          "Delay is the time from the injected fault's onset to the first matching asset alert. Lead is how much earlier than a plain absolute-threshold alarm (no twin) the first alert came; negative means the plain threshold fired first. 'Never' counts runs where the plain threshold did not fire at all.", "",
          "| Plant | Scenario | Fault | Runs | Missed | Median delay (h) | Worst delay (h) | Median lead vs plain threshold (h) | Plain threshold never fires |", "|---|---|---|---|---|---|---|---|---|"]
    for v in r["T2_detection"].values():
        L.append(f"| {PLANT_LABEL[v['plant']]} | {v['scenario']} | {v['fault'].replace('_', ' ')} | {v['runs']} | {v['missed']} | {_fmt(v['delay_h_median'])} | {_fmt(v['delay_h_max'])} | {_fmt(v['lead_vs_plain_threshold_h_median'])} | {v['plain_threshold_never_fires_in']} of {v['runs']} |")
    L += ["", "Overload, unbalance and theft are caught at onset by plain rules and the twin adds no lead there; the twin's advantage is on cooling degradation and slow oil loss, where a threshold fires late or never. Through-faults are invisible to a trend-only baseline.", ""]
    d = r["T3_diagnosis"]
    L += ["## T3 Does the diagnosis rank the injected fault first?", "",
          "Evaluated 6, 24 and 48 hours after the first alert of each run (so it measures diagnosis once a fault has been detected, not detection itself). 'Top-1' is the share of those moments where the highest-evidence observable class was the injected one.", "",
          "| Plant | Scenario | Expected class | Correct | Moments | Top-1 accuracy |", "|---|---|---|---|---|---|"]
    for v in d["per_scenario"].values():
        L.append(f"| {PLANT_LABEL[v['plant']]} | {v['scenario']} | {v['expected'].replace('_', ' ')} | {v['correct']} | {v['of']} | {_fmt(None if v['top1_accuracy'] is None else round(v['top1_accuracy'] * 100), ' %') if v['top1_accuracy'] is not None else 'n/a'} |")
    tot_c = sum(v["correct"] for v in d["per_scenario"].values())
    tot = sum(v["of"] for v in d["per_scenario"].values())
    L += ["", f"Overall: {tot_c} of {tot} ({(tot_c / tot * 100 if tot else 0):.0f} %). Confusion (expected -> what was ranked first): "
          + "; ".join(f"{k}: {dict(v)}" for k, v in d["confusion"].items()), ""]
    a = r["T5_adapter"]
    L += ["## T5 Ingestion of every fixture", "", f"{sum(v['ok'] for v in a['files'].values())} of {a['count']} fixtures load through the adapter.", "",
          "| Fixture | Loaded | Mode | Rows | Capabilities on | Seconds |", "|---|---|---|---|---|---|"]
    for k, v in a["files"].items():
        L.append(f"| {k} | {'yes' if v['ok'] else 'NO: ' + v['error']} | {v.get('mode', '')} | {v.get('rows', '')} | {v.get('capabilities_on', '')} | {v.get('seconds', '')} |")
    t6 = r["T6_api"]
    L += ["", "## T6 HTTP contract", "", f"{sum(1 for x in t6['endpoints'].values() if x in (200, 201))} of {len(t6['endpoints'])} endpoint calls returned success; "
          f"error cases: {sum(t6['error_cases'].values())} of {len(t6['error_cases'])} behaved as specified (404, 422, 400 with a readable `detail`).", ""]
    p = r["T7_performance"]
    L += ["## T7 Speed", "", f"{p['kaggle_rows']:,} rows of real field data in {p['kaggle_seconds']} s, and a 2,880-row month in {p['scenario_seconds']} s. "
          "Both cover the adapter's output through the twin, analytics and Health Index; the Monte Carlo outlook is computed separately on request.", ""]
    ph = r["T_physics"]
    L += ["## Physics check", "", f"The closed-form equations on the Physics page agree with the thermal library to within {ph['max_abs_difference_K']} K across ratings {ph['ratings']} kVA and loads {ph['loads_pu']} pu.", ""]
    f = r["T10_frontend"]
    L += ["## T10 Frontend", "", ("TypeScript type-check " + ("passed" if f.get("typecheck_passed") else "FAILED") + f"; production build {'present' if f.get('build_present') else 'not present'}.") if f.get("ran") else f"Not run: {f.get('reason')}", ""]
    L += ["## Not measured", ""] + [f"- {x}" for x in r["not_measured"]]
    return "\n".join(L) + "\n"


def main() -> None:
    quick = "--quick" in sys.argv
    r = run_all(quick)
    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "data" / "validation.json").write_text(json.dumps(r, indent=1, default=str), encoding="utf-8")
    (ROOT / "docs" / "TEST_REPORT.md").write_text(to_markdown(r), encoding="utf-8")
    print(f"wrote data/validation.json and docs/TEST_REPORT.md in {r['seconds']} s")


if __name__ == "__main__":
    main()
