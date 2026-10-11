"""PDF condition report with a snapshot of the transformer as it looks right now.

    pdf = build_pdf(run, brief, outlook, condition=None, injections=None, snapshot_png=None, standard="...")

Everything is read from the run; the snapshot is whatever the browser captured from the 3D twin (PNG bytes) and is
placed on the first page. A simulated run says so on the first page.
"""
from __future__ import annotations

import io
from datetime import datetime

import numpy as np
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from contracts.models import Run

INK, MUTED, RULE = colors.HexColor("#1B1B18"), colors.HexColor("#6B6A63"), colors.HexColor("#D9D6CB")
STATUS = {"ok": colors.HexColor("#2E7D4F"), "watch": colors.HexColor("#B7791F"), "alarm": colors.HexColor("#B42318"), "na": MUTED}
STATUS_TEXT = {"ok": "OK", "watch": "Watch", "alarm": "Alarm", "na": "n/a"}


def _styles():
    ss = getSampleStyleSheet()
    base = ParagraphStyle("b", parent=ss["Normal"], fontName="Helvetica", fontSize=9, leading=12.5, textColor=INK)
    return {
        "b": base,
        "small": ParagraphStyle("s", parent=base, fontSize=7.8, leading=10, textColor=MUTED),
        "h1": ParagraphStyle("h1", parent=base, fontName="Helvetica-Bold", fontSize=19, leading=23),
        "h2": ParagraphStyle("h2", parent=base, fontName="Helvetica-Bold", fontSize=11.5, leading=15, spaceBefore=10, spaceAfter=4),
        "cell": ParagraphStyle("c", parent=base, fontSize=8, leading=10),
        "cellb": ParagraphStyle("cb", parent=base, fontName="Helvetica-Bold", fontSize=8, leading=10),
    }


def _chart_png(run: Run) -> bytes | None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    t = run.trend
    if "timestamp" not in t or t.empty or "OTI_C" not in t:
        return None
    t = t.tail(7 * 96)
    x = pd.to_datetime(t["timestamp"])
    fig, ax = plt.subplots(figsize=(7.6, 2.5), dpi=160)
    ax.plot(x, t["OTI_C"], color="#D8542A", lw=1.3, label="top oil, measured")
    if "twin_oil_C" in t:
        ax.plot(x, t["twin_oil_C"], color="#2457A6", lw=1.1, ls="--", label="top oil, twin")
    if "WTI_C" in t:
        ax.plot(x, t["WTI_C"], color="#8A6D1F", lw=0.9, alpha=0.8, label="winding")
    ax.set_ylabel("°C", fontsize=8)
    ax2 = ax.twinx()
    load = t["load_pu"] if "load_pu" in t else t.get("loading_pct", pd.Series(dtype=float)) / 100
    ax2.fill_between(x, 0, load, color="#1B1B18", alpha=0.08, lw=0)
    ax2.set_ylabel("load, pu", fontsize=8)
    ax2.set_ylim(0, max(1.2, float(np.nanmax(load)) * 1.1 if len(load) else 1.2))
    ax.tick_params(labelsize=7)
    ax2.tick_params(labelsize=7)
    ax.legend(fontsize=7, loc="upper left", frameon=False, ncol=3)
    for sp in ("top",):
        ax.spines[sp].set_visible(False)
        ax2.spines[sp].set_visible(False)
    fig.autofmt_xdate(rotation=0, ha="center")
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


def _state_png(run: Run, condition: list[dict] | None) -> bytes | None:
    """A drawn picture of the transformer state, used when the browser could not send a snapshot of the 3D twin."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle, Rectangle
    t = run.trend
    if t is None or t.empty:
        return None
    r = t.iloc[-1]
    num = lambda k: float(r[k]) if k in r and pd.notna(r[k]) else float("nan")   # noqa: E731
    oil, wti, amb, oli = num("OTI_C"), num("WTI_C"), num("amb_C"), num("OLI_pct")
    cmap = plt.get_cmap("inferno")
    col = lambda v: cmap(min(1, max(0, (v - 20) / 120))) if v == v else "#CFCCC0"   # noqa: E731
    fig, ax = plt.subplots(figsize=(7.6, 3.6), dpi=160)
    ax.set_xlim(0, 100); ax.set_ylim(0, 47); ax.set_aspect("equal"); ax.axis("off")
    ln = "#1B1B18"
    ax.add_patch(Rectangle((10, 4), 44, 26, fc=col(oil), ec=ln, lw=1.5, alpha=0.85))
    ax.add_patch(Rectangle((8, 30), 48, 2.4, fc="#CFCCC0", ec=ln, lw=1.2))
    for k in range(6):
        ax.add_patch(Rectangle((54 + k * 2, 7), 1.4, 21, fc=col(oil - 8), ec=ln, lw=0.8))
    for x, lab in zip((18, 30, 42), ("R", "Y", "B")):
        ax.add_patch(Rectangle((x - 1, 32.4), 2, 5, fc="#8A867A", ec=ln, lw=0.9))
        ax.text(x, 40, "HV " + lab, ha="center", fontsize=6)
    ax.add_patch(Rectangle((8, 40), 0, 0))
    ax.add_patch(Circle((60, 36), 1.4, fc=col(wti), ec=ln, lw=1))
    lvl = oli / 100 if oli == oli else 0.9
    ax.add_patch(Rectangle((11, 5), 3, 24 * lvl, fc="#2457A6", ec="none", alpha=0.9))
    ax.text(12.5, 2.2, f"oil level {oli:.0f} %" if oli == oli else "", fontsize=5.5, ha="left")
    lines = [f"Top oil {oil:.1f} °C", f"Winding {wti:.1f} °C", f"Ambient {amb:.1f} °C"]
    if "load_pu" in r and pd.notna(r["load_pu"]):
        lines.append(f"Load {float(r['load_pu']) * 100:.0f} %")
    if "H2O_ppm" in r and pd.notna(r["H2O_ppm"]):
        lines.append(f"Moisture {float(r['H2O_ppm']):.1f} ppm")
    for i, tx in enumerate(lines):
        ax.text(72, 33 - i * 5, tx, fontsize=8, fontweight="bold" if i == 0 else "normal")
    if condition:
        bad = [c["title"] for c in condition if c["status"] == "alarm"]
        ax.text(72, 33 - len(lines) * 5 - 1, ("In alarm: " + ", ".join(bad)) if bad else "All within limits", fontsize=6.6, color="#B42318" if bad else "#2E7D4F")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def _fit(png: bytes, max_w: float, max_h: float) -> Image:
    from reportlab.lib.utils import ImageReader
    w, h = ImageReader(io.BytesIO(png)).getSize()
    k = min(max_w / w, max_h / h)
    return Image(io.BytesIO(png), width=w * k, height=h * k)


def build_pdf(run: Run, brief: dict, outlook: dict | None, condition: list[dict] | None = None, injections: list[dict] | None = None,
              snapshot_png: bytes | None = None, standard: str = "IEC 60076-7 ageing model", cut_png: bytes | None = None) -> bytes:
    S = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
                            title=f"{run.name} condition report", author="Digital twin")
    W = A4[0] - 32 * mm
    el: list = []
    t_end = run.trend["timestamp"].max() if "timestamp" in run.trend and len(run.trend) else None
    simulated = bool(run.trend["simulated"].iloc[-1]) if "simulated" in run.trend and len(run.trend) else True
    asset = run.asset or {}

    el.append(Paragraph(f"{asset.get('name', run.name)}: condition report", S["h1"]))
    sub = f"{asset.get('site', '')} · {asset.get('rating_kVA', '')} kVA, {asset.get('hv_voltage_V', 0) / 1000:g}/{asset.get('lv_voltage_V', 0) / 1000:g} kV, {asset.get('vector_group', '')}, {asset.get('cooling', '')}"
    el.append(Paragraph(sub, S["small"]))
    when = t_end.strftime("%d %b %Y %H:%M") if t_end is not None else "n/a"
    el.append(Paragraph(f"State at {when} · report made {datetime.now().strftime('%d %b %Y %H:%M')} · Standard: {standard}", S["small"]))
    if simulated:
        el.append(Spacer(1, 3))
        el.append(Paragraph("<font color='#B7791F'><b>SIMULATED.</b></font> Every number in this report comes from a simulated transformer, not measurements from a real unit.", S["b"]))
    el.append(Spacer(1, 6))

    picture, drawn = snapshot_png, False
    if not picture:
        picture, drawn = _state_png(run, condition), True
    if picture and cut_png:
        # outside and cut open, side by side
        cap = ParagraphStyle("cap", parent=S["small"], alignment=1)
        tb = Table([[_fit(picture, W / 2 - 4, 92 * mm), _fit(cut_png, W / 2 - 4, 92 * mm)],
                    [Paragraph("Outside, as it looks now", cap), Paragraph("Cut open: core and windings in the oil, coloured by temperature", cap)]],
                   colWidths=[W / 2, W / 2])
        tb.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, 0), "MIDDLE"), ("BOTTOMPADDING", (0, 0), (-1, 0), 2)]))
        el.append(tb)
        el.append(Paragraph(f"Snapshots of the digital twin at {when}. Colours show temperature; arrows show power flow and cooling.", S["small"]))
        el.append(Spacer(1, 4))
    elif picture:
        el.append(_fit(picture, W, 96 * mm))
        el.append(Paragraph(f"Snapshot of the digital twin at {when}. Colours show temperature; arrows show power flow and cooling." if not drawn else
                            f"Drawn picture of the transformer state at {when} (the 3D snapshot was not available from the browser). Colour shows top-oil temperature.", S["small"]))
        el.append(Spacer(1, 4))

    el.append(Paragraph("Status", S["h2"]))
    el.append(Paragraph(brief.get("sentence", ""), S["b"]))
    adv = brief.get("advice") or {}
    if adv:
        el.append(Paragraph(f"<b>Next step:</b> {adv.get('schedule', '')} (priority {adv.get('priority', '')}).", S["b"]))
    h = brief.get("health") or {}
    if h:
        el.append(Paragraph(f"Health Index {h.get('score', 'n/a')} ({h.get('band', '')}).", S["b"]))
    diag = [d for d in brief.get("diagnosis") or [] if d.get("share", 0) > 0.05]
    for d in diag[:4]:
        el.append(Paragraph(f"• {d['label']}: {d['why']}", S["b"]))
    if condition:
        bad = [c["title"] for c in condition if c["status"] == "alarm"]
        warn = [c["title"] for c in condition if c["status"] == "watch"]
        if bad or warn:
            el.append(Paragraph("<b>Condition board:</b> " + (f"<font color='#B42318'><b>{len(bad)} in alarm</b></font> ({', '.join(bad)})" if bad else "")
                                + ("; " if bad and warn else "") + (f"{len(warn)} to watch ({', '.join(warn)})" if warn else "") + ".", S["b"]))
        else:
            el.append(Paragraph("<b>Condition board:</b> every quantity is within its limit.", S["b"]))
    if injections:
        el.append(Spacer(1, 3))
        el.append(Paragraph("<b>Active anomalies injected into the simulation:</b> " + ", ".join(f"{i['label']} ({i['since_h']} h)" for i in injections), S["b"]))

    if condition:
        el.append(Paragraph("Condition against limits", S["h2"]))
        rows = [[Paragraph("<b>Quantity</b>", S["cell"]), Paragraph("<b>Now</b>", S["cell"]), Paragraph("<b>Limit</b>", S["cell"]), Paragraph("<b>Status</b>", S["cell"])]]
        sty = [("LINEBELOW", (0, 0), (-1, 0), 0.8, INK), ("VALIGN", (0, 0), (-1, -1), "TOP"),
               ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
        for n, c in enumerate(condition, start=1):
            v = c["value"]
            val = "n/a" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:.2f}" if abs(v) < 100 else f"{v:.0f}"
            rows.append([Paragraph(f"<b>{c['title']}</b><br/><font size=7 color='#6B6A63'>{c['detail']}</font>", S["cell"]),
                         Paragraph(f"{val} {c['unit']}", S["cell"]), Paragraph(c["limit"], S["cell"]),
                         Paragraph(f"<font color='{STATUS[c['status']].hexval().replace('0x', '#')}'><b>{STATUS_TEXT[c['status']]}</b></font>", S["cell"])])
            sty.append(("LINEBELOW", (0, n), (-1, n), 0.3, RULE))
        tb = Table(rows, colWidths=[W * 0.42, W * 0.18, W * 0.28, W * 0.12], repeatRows=1)
        tb.setStyle(TableStyle(sty))
        el.append(tb)

    chart = _chart_png(run)
    if chart:
        el.append(Paragraph("Last seven days", S["h2"]))
        el.append(_fit(chart, W, 70 * mm))

    alerts = list(run.analysis.alerts)[-14:][::-1] if run.analysis else []
    el.append(Paragraph("Recent alerts", S["h2"]))
    if alerts:
        rows = [[Paragraph("<b>Time</b>", S["cell"]), Paragraph("<b>Alert</b>", S["cell"]), Paragraph("<b>Severity</b>", S["cell"]), Paragraph("<b>What it means</b>", S["cell"])]]
        for a in alerts:
            rows.append([Paragraph(pd.Timestamp(a.timestamp).strftime("%d %b %H:%M"), S["cell"]), Paragraph(a.type.replace("_", " "), S["cell"]),
                         Paragraph(a.severity, S["cell"]), Paragraph(a.explanation, S["cell"])])
        tb = Table(rows, colWidths=[W * 0.12, W * 0.2, W * 0.1, W * 0.58], repeatRows=1)
        tb.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, 0), 0.8, INK), ("LINEBELOW", (0, 1), (-1, -1), 0.3, RULE), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        el.append(tb)
    else:
        el.append(Paragraph("No alerts raised.", S["b"]))

    if outlook:
        r, k = outlook["rul"], outlook["trip_risk_30d"]
        el.append(Paragraph("Outlook", S["h2"]))
        el.append(KeepTogether([
            Paragraph(f"Remaining insulation life: about {r['years_p50']:.0f} years (10 to 90 percent range {r['years_p10']:.0f} to {r['years_p90']:.0f} years), "
                      f"from {r.get('runs', '')} Monte Carlo runs of the ageing model.", S["b"]),
            Paragraph(f"Probability the hot spot passes its limit within 30 days: {k['probability'] * 100:.1f} %.", S["b"])]))

    el.append(Paragraph("Limits of this report", S["h2"]))
    el.append(Paragraph("Limits follow the India profile in config/thresholds.yaml (IS 2026, IS 1180, IS 6600, IS 1866, CEA); values marked as practice or assumed there "
                        "must be confirmed with your utility. The ageing model is IEC 60076-7. This is engineering guidance, not a certified test report.", S["small"]))
    doc.build(el)
    return buf.getvalue()
