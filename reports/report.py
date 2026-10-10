"""Reporting layer: one self-contained, print-ready HTML page, a full CSV and a JSON export of a run.

    html = build_html(run, brief, outlook)     # inline SVG charts, no external files, prints to PDF from the browser
    csv  = build_csv(run)                      # the whole time series with Health Index, residual and alert flags
    data = build_json(run, brief, outlook)

Everything is read from the run; nothing is typed in for show. Anything simulated says so on the first page, and the
limitations are part of the report, not an appendix nobody reads.
"""
from __future__ import annotations

import html as _html
import json
from datetime import datetime

import numpy as np
import pandas as pd

from contracts.models import Run

e = _html.escape
IST = "Asia/Kolkata"


# ---------------------------------------------------------------- small helpers
def _f(v, d=1, unit=""):
    return "n/a" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:.{d}f}{unit}"


def _span(run: Run) -> tuple[str, str]:
    if "timestamp" not in run.trend or run.trend.empty:
        return "n/a", "n/a"
    t = run.trend["timestamp"]
    return t.min().strftime("%d %b %Y %H:%M"), t.max().strftime("%d %b %Y %H:%M")


def _downsample(x: np.ndarray, y: np.ndarray, n: int = 500):
    ok = ~np.isnan(y)
    x, y = x[ok], y[ok]
    if len(y) <= n:
        return x, y
    idx = np.unique(np.linspace(0, len(y) - 1, n).astype(int))
    return x[idx], y[idx]


def _svg_lines(series: list[tuple[str, str, pd.Series, pd.Series]], width=760, height=210, title="", unit="", band: tuple | None = None) -> str:
    """series: (label, colour, times, values). Draws polylines on shared axes; optional shaded band between the first two."""
    ml, mr, mt, mb = 46, 12, 22, 24
    xs = [t.astype("int64").to_numpy() / 1e9 for _, _, t, _ in series if len(t)]
    ys = [v.to_numpy(dtype=float) for _, _, _, v in series if len(v)]
    if not xs:
        return ""
    x0, x1 = min(a.min() for a in xs), max(a.max() for a in xs)
    allv = np.concatenate([y[~np.isnan(y)] for y in ys]) if ys else np.array([0.0])
    if not len(allv):
        return ""
    lo, hi = float(allv.min()), float(allv.max())
    pad = max(1.0, (hi - lo) * 0.08)
    lo, hi = lo - pad, hi + pad
    sx = lambda t: ml + (t - x0) / max(x1 - x0, 1) * (width - ml - mr)          # noqa: E731
    sy = lambda v: mt + (1 - (v - lo) / (hi - lo)) * (height - mt - mb)         # noqa: E731
    out = [f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" aria-label="{e(title)}">',
           f'<text x="{ml}" y="14" font-size="11" fill="#444">{e(title)} ({e(unit)})</text>']
    for k in range(5):
        v = lo + (hi - lo) * k / 4
        out.append(f'<line x1="{ml}" x2="{width - mr}" y1="{sy(v):.1f}" y2="{sy(v):.1f}" stroke="#ddd"/>'
                   f'<text x="{ml - 6}" y="{sy(v) + 3:.1f}" font-size="10" text-anchor="end" fill="#666">{v:.0f}</text>')
    days = max(1, int((x1 - x0) / 86400))
    step = max(1, days // 8)
    for d in range(0, days + 1, step):
        t = x0 + d * 86400
        label = pd.Timestamp(t, unit="s", tz="UTC").tz_convert(IST).strftime("%d %b")
        out.append(f'<text x="{sx(t):.1f}" y="{height - 6}" font-size="10" text-anchor="middle" fill="#666">{label}</text>')
    if band and len(series) >= 2:
        (ta, va), (tb, vb) = band
        if len(ta) and len(tb):
            m = pd.merge_asof(pd.DataFrame({"t": ta, "a": va.to_numpy(float)}).sort_values("t"),
                              pd.DataFrame({"t": tb, "b": vb.to_numpy(float)}).sort_values("t"), on="t", direction="nearest").dropna()
            if len(m):
                tt = m["t"].astype("int64").to_numpy() / 1e9
                poly = [f"{sx(t):.1f},{sy(v):.1f}" for t, v in zip(tt, m["a"])] + [f"{sx(t):.1f},{sy(v):.1f}" for t, v in zip(tt[::-1], m["b"].to_numpy()[::-1])]
                out.append(f'<polygon points="{" ".join(poly)}" fill="#e0408f" fill-opacity="0.28"/>')
    for label, colour, t, v in series:
        tt, vv = _downsample(t.astype("int64").to_numpy() / 1e9, v.to_numpy(dtype=float))
        if len(vv) > 1:
            pts = " ".join(f"{sx(a):.1f},{sy(b):.1f}" for a, b in zip(tt, vv))
            out.append(f'<polyline points="{pts}" fill="none" stroke="{colour}" stroke-width="1.4"/>')
    lx = ml
    for label, colour, *_ in series:
        out.append(f'<rect x="{lx}" y="{height - mb + 12}" width="0" height="0"/>')
    out.append("</svg>")
    legend = " ".join(f'<span class="key"><i style="background:{c}"></i>{e(l)}</span>' for l, c, *_ in series)
    return "".join(out) + f'<div class="legend">{legend}</div>'


def _svg_ribbon(score: pd.Series, times: pd.Series, width=760, height=34) -> str:
    n = 160
    if len(score) < 2:
        return ""
    idx = np.linspace(0, len(score) - 1, n).astype(int)
    bw = width / n
    col = lambda s: "#2a9d6f" if s >= 80 else "#d8a600" if s >= 60 else "#d64550"       # noqa: E731
    rects = "".join(f'<rect x="{i * bw:.1f}" y="4" width="{bw + 0.6:.1f}" height="26" fill="{col(score.iloc[j])}"/>' for i, j in enumerate(idx))
    return f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" aria-label="Health Index over the period (green 80 and above, amber 60 to 79, red below 60)">{rects}</svg>'


# ---------------------------------------------------------------- HTML
CSS = """
:root{--ink:#14202e;--mute:#5a6b7d;--line:#d9e0e8;--twin:#0b86b8;--meas:#c77a00;--gap:#d63a86}
*{box-sizing:border-box}body{font:14px/1.5 "Barlow","Segoe UI",system-ui,sans-serif;color:var(--ink);margin:0;background:#eef2f6}
main{max-width:900px;margin:24px auto;background:#fff;padding:36px 44px;border:1px solid var(--line)}
h1{font-size:28px;margin:0 0 4px}h2{font-size:18px;margin:28px 0 8px;padding-top:10px;border-top:2px solid var(--ink)}h3{font-size:14px;margin:14px 0 4px}
.sub{color:var(--mute);margin:0}table{border-collapse:collapse;width:100%;margin:6px 0;font-size:13px}th,td{text-align:left;padding:5px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--mute);font-weight:600}.num{text-align:right;font-variant-numeric:tabular-nums}.pill{display:inline-block;padding:1px 9px;border-radius:99px;font-weight:600;font-size:12px;border:1px solid}
.green{color:#17754f;border-color:#2a9d6f;background:#e8f6ef}.yellow{color:#8a6a00;border-color:#d8a600;background:#fff6d9}.red{color:#a3222c;border-color:#d64550;background:#fdecee}.grey{color:#566;border-color:#aab;background:#f3f5f8}
.sim{background:#efe7ff;border:1px solid #b79cff;color:#4b2a9a;padding:8px 12px;margin:12px 0;font-weight:600}
.sentence{font-size:19px;line-height:1.35;margin:10px 0 4px}.legend{font-size:12px;color:var(--mute);margin:2px 0 8px}
.key{margin-right:14px}.key i{display:inline-block;width:12px;height:3px;margin-right:5px;vertical-align:middle}
.note{color:var(--mute);font-size:12.5px}.kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:8px 0}
.kpi{border:1px solid var(--line);padding:8px 12px}.kpi b{display:block;font-size:22px}.kpi span{color:var(--mute);font-size:12px}
ul{margin:4px 0 4px 18px;padding:0}footer{margin-top:30px;padding-top:10px;border-top:1px solid var(--line);color:var(--mute);font-size:12px}
@media print{body{background:#fff}main{border:0;margin:0;padding:0;max-width:none}h2{break-after:avoid}table,svg,.kpis{break-inside:avoid}}
"""


def _kpi(label: str, value: str, sub: str = "") -> str:
    return f'<div class="kpi"><b>{value}</b><span>{e(label)}{(" · " + e(sub)) if sub else ""}</span></div>'


def build_html(run: Run, brief: dict, outlook: dict | None) -> str:
    start, end = _span(run)
    a = run.asset
    tags = a.get("tags", {}) or {}
    simulated = bool(run.trend["simulated"].any()) if "simulated" in run.trend else False
    h = run.analysis.health
    band = str(h.band).lower()
    rul = (outlook or {}).get("rul")
    risk = (outlook or {}).get("trip_risk_30d")
    fc = (outlook or {}).get("forecast") or {}
    alerts = sorted(run.analysis.alerts, key=lambda x: x.timestamp)
    asset_alerts = [x for x in alerts if x.origin == "asset"]
    sensor_alerts = [x for x in alerts if x.origin == "sensor"]
    tr = run.trend
    parts = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
             f"<title>Condition report: {e(str(a.get('name', run.name)))}</title><style>{CSS}</style></head><body><main>"]
    parts.append(f"<h1>Condition report</h1><p class='sub'>{e(run.name)}<br>Period {e(start)} to {e(end)} IST · generated {datetime.now().astimezone().strftime('%d %b %Y %H:%M')}</p>")
    if simulated:
        parts.append("<div class='sim'>SIMULATED: this report describes generated data, not a real transformer. Fault scenarios are synthetic.</div>")
    if a.get("nameplate_source") == "estimated":
        parts.append("<div class='sim' style='background:#fdecee;border-color:#d64550;color:#a3222c'>The nameplate was estimated from the data: rating-dependent values are assumptions.</div>")

    parts.append("<h2>Summary</h2>")
    parts.append(f"<p class='sentence'>{e(brief.get('sentence', ''))}</p>")
    life = (run.summary.get("life_consumed_days") or {})
    parts.append("<div class='kpis'>"
                 + _kpi("Health Index at the end", f"{_f(h.score, 0)} <span class='pill {band}'>{e(str(h.band))}</span>", "capped by a critical alarm" if h.capped else "")
                 + _kpi("Alerts", f"{len(asset_alerts)}", f"asset · {len(sensor_alerts)} sensor/data")
                 + _kpi("Insulation life used", f"{_f(life.get('actual', life.get('expected')), 2)} days", "equivalent days in the period")
                 + _kpi("Remaining insulation life (median)", ("more than 40 years" if rul and rul["years_p50"] >= 40 else f"{_f(rul['years_p50'], 1)} years") if rul else "n/a", "model estimate")
                 + _kpi("Chance of a temperature limit in 30 days", f"{_f(risk['probability'] * 100, 1)} %" if risk else "n/a")
                 + _kpi("Peak hot spot", _f(tr["twin_hs_C"].max() if "twin_hs_C" in tr else None, 0, " °C"), "twin estimate")
                 + "</div>")

    parts.append("<h2>Asset and nameplate</h2><table><tr><th>Item</th><th class='num'>Value</th><th>Source</th></tr>")
    for k, label, unit in (("rating_kVA", "Rating", "kVA"), ("lv_voltage_V", "LV voltage", "V"), ("hv_voltage_V", "HV voltage", "V"), ("i_rated_A", "Rated current (LV)", "A"),
                           ("load_loss_W", "Load loss", "W"), ("no_load_loss_W", "No-load loss", "W"), ("top_oil_rise_K", "Top-oil rise at rated load", "K"),
                           ("winding_oil_gradient_K", "Winding-to-oil gradient", "K"), ("oil_time_constant_min", "Oil time constant", "min"),
                           ("years_in_service", "Years in service", "years")):
        if a.get(k) is not None:
            parts.append(f"<tr><td>{label}</td><td class='num'>{e(str(a[k]))} {unit}</td><td>{e(str(tags.get(k, 'config')))}</td></tr>")
    parts.append("</table><p class='note'>A nameplate value always beats a default. Values tagged Assumed or IEC default should be replaced from the real nameplate.</p>")

    parts.append("<h2>Health Index</h2>")
    hs = run.health_series
    if hs is not None and not hs.empty:
        parts.append(_svg_ribbon(hs["score"], hs["timestamp"]))
        parts.append("<table><tr><th>Sub-score (end of period)</th><th class='num'>Score</th><th class='num'>Weight</th></tr>")
        for k, v in h.components.items():
            parts.append(f"<tr><td>{e(k.replace('_', ' ').title())}</td><td class='num'>{v:.0f}</td><td class='num'>{h.weights.get(k, 0) * 100:.0f} %</td></tr>")
        parts.append("</table>")
    parts.append("<p class='note'>A transparent engineering score. Weights, curves and bands are engineering judgement, not a trained model, and have not been validated against field failures.</p>")

    parts.append("<h2>Temperatures: measured against the twin</h2>")
    if "twin_oil_C" in tr and "timestamp" in tr:
        t = tr["timestamp"]
        ser = [("Twin (physics)", "#0b86b8", t, tr["twin_oil_C"])]
        band_arg = None
        if run.mode == "full" and "OTI_C" in tr and tr["OTI_C"].notna().any():
            ser.append(("Measured", "#c77a00", t, tr["OTI_C"]))
            band_arg = ((t, tr["OTI_C"]), (t, tr["twin_oil_C"]))
        parts.append(_svg_lines(ser, title="Top-oil temperature", unit="°C", band=band_arg))
        if "twin_hs_C" in tr:
            parts.append(_svg_lines([("Hot spot (twin)", "#d63a86", t, tr["twin_hs_C"])], height=170, title="Hot-spot temperature", unit="°C"))
        if band_arg:
            res = tr["residual_oil_C"].dropna()
            parts.append(f"<p class='note'>Shaded: the gap between measured and twin. Over the period the gap averaged {_f(res.mean(), 1, ' K')} and reached {_f(res.abs().max(), 1, ' K')}; the twin's rolling error at the end was {_f(run.summary.get('fidelity_rmse_C_last'), 1, ' K')}.</p>")
    else:
        parts.append("<p class='note'>This dataset has no time series of load and ambient temperature, so no temperature trend is shown.</p>")

    parts.append("<h2>Alerts</h2>")
    if alerts:
        parts.append("<table><tr><th>Time (IST)</th><th>Severity</th><th>Origin</th><th>Type</th><th>Explanation</th></tr>")
        for x in alerts[:60]:
            cls = "red" if x.severity == "critical" else "yellow" if x.severity == "warning" else "grey"
            parts.append(f"<tr><td>{pd.Timestamp(x.timestamp).strftime('%d %b %H:%M')}</td><td><span class='pill {cls}'>{e(x.severity)}</span></td>"
                         f"<td>{'Sensor / data' if x.origin == 'sensor' else 'Asset'}</td><td>{e(x.type.replace('_', ' '))}</td><td>{e(x.explanation)}</td></tr>")
        parts.append("</table>")
        if len(alerts) > 60:
            parts.append(f"<p class='note'>The first 60 of {len(alerts)} alerts are listed; the CSV and JSON exports contain all of them.</p>")
        parts.append("<p class='note'>Sensor-origin alerts mean: check the device, not the transformer.</p>")
    else:
        parts.append("<p>No alerts in this period.</p>")

    parts.append("<h2>Diagnosis and maintenance recommendations</h2>")
    diag = [d for d in brief.get("diagnosis", []) if d["observable"] and d["evidence"] >= 0.15]
    if diag:
        parts.append("<table><tr><th>Most likely cause</th><th class='num'>Share of evidence</th><th>Why</th></tr>" + "".join(
            f"<tr><td>{e(d['label'])}</td><td class='num'>{d['share'] * 100:.0f} %</td><td>{e(d['why'])}</td></tr>" for d in diag) + "</table>")
    adv = brief.get("advice") or {}
    if adv:
        parts.append(f"<p><b>Priority: {e(str(adv.get('priority', '')))}.</b> {e(str(adv.get('schedule', '')))}</p>")
        if adv.get("actions"):
            parts.append("<table><tr><th>Action</th><th>Test</th><th>When</th><th>Why</th></tr>" + "".join(
                f"<tr><td>{e(x['action'])}</td><td>{e(x.get('test') or '')}</td><td>{e(x['urgency'])}</td><td>{e(x.get('why') or '')}</td></tr>" for x in adv["actions"]) + "</table>")
        parts.append(f"<p class='note'>{e(adv.get('note', ''))}</p>")

    parts.append("<h2>Outlook</h2>")
    if rul:
        parts.append(f"<p>Median remaining insulation life {'more than 40' if rul['years_p50'] >= 40 else _f(rul['years_p50'], 1)} years; one chance in ten of less than "
                     f"{'40+' if rul['years_p10'] >= 40 else _f(rul['years_p10'], 1)} years. Risk class: {e(rul['risk'])}.</p>"
                     f"<p class='note'>{e(rul['note'])} ({rul['inputs']['runs']} simulations; cooling factor {rul['inputs']['cooling_factor']}; consumed life {rul['inputs']['consumed_life_pct']} %.)</p>")
    if fc.get("available"):
        parts.append(f"<p>24 h forecast from the end of the data: peak top oil {_f(fc['peak_top_oil_C'], 0, ' °C')}, peak hot spot {_f(fc['peak_hot_spot_C'], 0, ' °C')}. "
                     f"<span class='note'>{e(fc['method'])} Band: {e(fc['band_basis'])}.</span></p>")
    if not rul and not fc.get("available"):
        parts.append("<p class='note'>No outlook: it needs a load and ambient-temperature time series.</p>")

    parts.append("<h2>Data quality and what the data supports</h2>")
    hr = run.health_report
    flags = hr.get("flag_counts_final") or hr.get("flag_counts") or {}
    if flags:
        parts.append("<table><tr><th>Flag</th><th class='num'>Rows</th></tr>" + "".join(f"<tr><td>{e(k)}</td><td class='num'>{v}</td></tr>" for k, v in flags.items()) + "</table>")
    else:
        parts.append("<p class='note'>No data-quality flags were recorded for this dataset.</p>")
    parts.append("<p>" + " ".join(f"<span class='pill {'green' if v else 'grey'}'>{'✓' if v else '✕'} {e(k.replace('_', ' '))}</span>" for k, v in run.capabilities.items()) + "</p>")
    for w in hr.get("warnings", []) or []:
        parts.append(f"<p class='note'>Note: {e(str(w))}</p>")

    parts.append("<h2>Method, assumptions and limitations</h2><ul>"
                 "<li><b>Twin.</b> IEC 60076-7 thermal model run on the measured load and ambient temperature; the difference from the oil-temperature sensor is the main anomaly signal.</li>"
                 "<li><b>Not fitted.</b> The model is driven by nameplate values and standard defaults, not fitted to this data, so a faulty sensor is not learned as normal.</li>"
                 "<li><b>Ageing.</b> Thermal ageing of normal Kraft paper, relative rate 2^((hot spot − 98 °C)/6). Remaining life is a Monte Carlo model outcome for the insulation, not a failure forecast.</li>"
                 "<li><b>Thresholds and weights</b> are engineering judgement and are configurable; standards references (IS 1180, IEC 60076-7 limits) are to be verified against the primary text.</li>"
                 "<li><b>Limits.</b> No moisture, partial-discharge or dissolved-gas analysis. Short circuits are seen only through an event log. Results on generated data are regression tests, not evidence of field performance.</li></ul>")
    parts.append("<footer>Generated by the transformer digital twin. Every figure above is computed from the dataset named at the top; none is typed in.</footer></main></body></html>")
    return "".join(parts)


# ---------------------------------------------------------------- CSV and JSON
def build_csv(run: Run) -> str:
    tr = run.trend.copy()
    drop = [c for c in tr.columns if c.startswith(("gt_", "alarm_"))]
    tr = tr.drop(columns=drop)
    if "timestamp" in tr:
        tr = tr.sort_values("timestamp").reset_index(drop=True)
        hs = run.health_series
        if hs is not None and not hs.empty:
            h = hs[["timestamp", "score"]].rename(columns={"score": "health_score"}).sort_values("timestamp")
            tr = pd.merge_asof(tr, h, on="timestamp", direction="backward")
            tr["health_band"] = np.where(tr["health_score"] >= 80, "green", np.where(tr["health_score"] >= 60, "yellow", "red"))
            tr.loc[tr["health_score"].isna(), "health_band"] = ""
        active = np.zeros(len(tr), dtype=int)
        crit = np.zeros(len(tr), dtype=int)
        types: list[set] = [set() for _ in range(len(tr))]
        ts = tr["timestamp"]
        for a in run.analysis.alerts:
            lo = ts.searchsorted(pd.Timestamp(a.timestamp), side="left")
            hi = ts.searchsorted(pd.Timestamp(a.timestamp) + pd.Timedelta(hours=24), side="left")
            active[lo:hi] += 1
            if a.severity == "critical":
                crit[lo:hi] += 1
            for i in range(lo, min(hi, lo + 400)):
                types[i].add(a.type)
        tr["alerts_active_24h"] = active
        tr["critical_alerts_active_24h"] = crit
        tr["alert_types"] = [";".join(sorted(s)) for s in types]
    return tr.to_csv(index=False, float_format="%.4g")


def build_json(run: Run, brief: dict, outlook: dict | None) -> dict:
    import dataclasses
    asset = {k: v for k, v in run.asset.items()}
    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "dataset": {"id": run.dataset_id, "name": run.name, "mode": run.mode, "span": list(_span(run)),
                    "simulated": bool(run.trend["simulated"].any()) if "simulated" in run.trend else False},
        "asset": asset, "capabilities": run.capabilities, "summary": run.summary,
        "health": dataclasses.asdict(run.analysis.health),
        "alerts": [dataclasses.asdict(a) for a in run.analysis.alerts],
        "recommendations": [dataclasses.asdict(r) for r in run.analysis.recommendations],
        "brief_at_end": brief, "outlook_at_end": outlook,
        "data_health": {k: v for k, v in run.health_report.items() if not isinstance(v, pd.DataFrame)},
        "limitations": ["Thermal model is not fitted to the data.", "Remaining life is a model outcome for the insulation, not a failure forecast.",
                        "Thresholds and weights are engineering judgement.", "Generated scenarios are synthetic."],
    }


def to_json_text(data: dict) -> str:
    return json.dumps(data, indent=1, default=str)
