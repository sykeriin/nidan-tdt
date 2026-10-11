"""Engineering drawing sheets (A3 landscape, drawing frame and title block) for the transformer monitoring installation.

    DT-001  System architecture            field -> edge -> network -> twin server -> clients
    DT-002  Instrumentation and signal wiring   instruments, marshalling box terminals, gateway channels, cable schedule
    DT-003  Software architecture and data flow   what runs on the server and what each interface carries
    DT-004  Single-line diagram
    DT-005  General arrangement (schematic)

Each function returns a matplotlib Figure sized 420 x 297 mm with units in millimetres, so a sheet can be saved as SVG (vector) or
rendered to PNG for the PDF. Drawing numbers, tags and signal names match sensor_schedule.csv and terminal_schedule.csv.
"""
from __future__ import annotations

from datetime import datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Circle, FancyBboxPatch, Rectangle  # noqa: E402

INK, MUTED, RULE, PAPER = "#1B1B18", "#6B6A63", "#B9B6AA", "#FFFFFF"
BLUE, GREEN, AMBER, RED, TEAL = "#2457A6", "#2E7D4F", "#B7791F", "#B42318", "#1E7C80"
FIELD_C, EDGE_C, NET_C, SRV_C, CLI_C = "#F3E9DC", "#E8EDF5", "#EEF0E4", "#E7F0EC", "#F3E6EF"
SHEETS = 5


class Sheet:
    """A3 landscape drawing with a border, zone marks and a title block. Draw in millimetres on `ax`."""

    def __init__(self, no: str, title: str, n: int, asset: dict, scale: str = "NTS", status: str = "Issued for installation review"):
        self.fig = plt.figure(figsize=(420 / 25.4, 297 / 25.4), dpi=100)
        self.ax = self.fig.add_axes([0, 0, 1, 1])
        self.ax.set_xlim(0, 420)
        self.ax.set_ylim(0, 297)
        self.ax.axis("off")
        self._frame(no, title, n, asset, scale, status)

    # ---- frame
    def _frame(self, no, title, n, asset, scale, status):
        a = self.ax
        a.add_patch(Rectangle((4, 4), 412, 289, fc=PAPER, ec=INK, lw=0.6))
        a.add_patch(Rectangle((10, 10), 400, 277, fc="none", ec=INK, lw=1.4))
        for i in range(8):                                   # zone marks, columns 1-8 and rows A-F
            x = 10 + 400 * (i + 0.5) / 8
            a.text(x, 6.6, str(i + 1), ha="center", va="center", fontsize=6, color=MUTED)
            a.text(x, 290.4, str(i + 1), ha="center", va="center", fontsize=6, color=MUTED)
            if i:
                a.plot([10 + 400 * i / 8] * 2, [10, 12.2], color=INK, lw=0.5)
                a.plot([10 + 400 * i / 8] * 2, [284.8, 287], color=INK, lw=0.5)
        for j, ch in enumerate("FEDCBA"):
            y = 10 + 277 * (j + 0.5) / 6
            a.text(6.6, y, ch, ha="center", va="center", fontsize=6, color=MUTED)
            a.text(413.4, y, ch, ha="center", va="center", fontsize=6, color=MUTED)
        # title block, bottom right, 190 x 42 mm
        x0, y0, w, h = 220, 10, 190, 42
        a.add_patch(Rectangle((x0, y0), w, h, fc=PAPER, ec=INK, lw=1.2))
        a.plot([x0, x0 + w], [y0 + 26, y0 + 26], color=INK, lw=0.8)
        a.plot([x0, x0 + w], [y0 + 14, y0 + 14], color=INK, lw=0.5)
        a.plot([x0 + 120, x0 + 120], [y0, y0 + 26], color=INK, lw=0.5)
        a.plot([x0 + 150, x0 + 150], [y0, y0 + 14], color=INK, lw=0.5)
        a.text(x0 + 3, y0 + 36, f"{asset.get('name', 'Transformer')}: digital twin and condition monitoring", fontsize=10.5, fontweight="bold", va="center")
        a.text(x0 + 3, y0 + 30, f"{asset.get('site', '')} · {asset.get('rating_kVA', '')} kVA, {asset.get('hv_voltage_V', 0) / 1000:g}/{asset.get('lv_voltage_V', 0) / 1000:g} kV, "
                                f"{asset.get('vector_group', '')}, {asset.get('cooling', '')}", fontsize=6.6, va="center", color=MUTED)
        a.text(x0 + 3, y0 + 20, title, fontsize=11, fontweight="bold", va="center")
        a.text(x0 + 3, y0 + 8.5, f"Status: {status}", fontsize=6.2, va="center")
        a.text(x0 + 3, y0 + 3.5, "Values tagged Assumed in asset.yaml to be confirmed from the nameplate.", fontsize=5.6, va="center", color=MUTED)
        for tx, ty, label, val in ((x0 + 123, y0 + 22, "Drawing no.", no), (x0 + 123, y0 + 10, "Scale / size", f"{scale} / A3"),
                                   (x0 + 153, y0 + 10, "Sheet", f"{n} of {SHEETS}"), (x0 + 123, y0 + 3, "Rev / date", f"A / {datetime.now():%d %b %Y}")):
            a.text(tx, ty + 2.6, label, fontsize=5, color=MUTED, va="center")
            a.text(tx, ty - 0.6, val, fontsize=8, fontweight="bold", va="center")
        a.text(x0 + 153, y0 + 3, "Generated", fontsize=5, color=MUTED, va="center")

    # ---- primitives (millimetres)
    def box(self, x, y, w, h, title="", lines=(), fc=PAPER, ec=INK, lw=1.0, fs=7.2, tfs=8.2, bold=True, round_=1.2, align="center", tc=INK):
        self.ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={round_}", fc=fc, ec=ec, lw=lw))
        n = len(lines) + (1 if title else 0)
        step = min(4.2, (h - 3) / max(n, 1))
        ty = y + h - 2.8 - step * 0.35
        if title:
            tx = x + w / 2 if align == "center" else x + 2.2
            self.ax.text(tx, ty, title, ha=align, va="center", fontsize=tfs, fontweight="bold" if bold else "normal", color=tc)
            ty -= step * 1.1
        for ln in lines:
            tx = x + w / 2 if align == "center" else x + 2.2
            self.ax.text(tx, ty, ln, ha=align, va="center", fontsize=fs, color=INK)
            ty -= step
        return (x, y, w, h)

    def lane(self, x, y, w, h, title, fc):
        self.ax.add_patch(Rectangle((x, y), w, h, fc=fc, ec=RULE, lw=0.8, ls=(0, (4, 3))))
        self.ax.text(x + w / 2, y + h - 3.6, title, ha="center", va="center", fontsize=9, fontweight="bold", color=MUTED)

    def arrow(self, x1, y1, x2, y2, label="", color=INK, both=False, lw=1.3, ls="-", fs=6.4, dx=0, dy=1.8, ha="center", bg=True):
        self.ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                         arrowprops=dict(arrowstyle="<|-|>" if both else "-|>", color=color, lw=lw, ls=ls, shrinkA=0, shrinkB=0, mutation_scale=9))
        if label:
            mx, my = (x1 + x2) / 2 + dx, (y1 + y2) / 2 + dy
            self.ax.text(mx, my, label, ha=ha, va="center", fontsize=fs, color=color,
                         bbox=dict(fc=PAPER, ec="none", pad=0.6, alpha=0.92) if bg else None)

    def line(self, pts, color=INK, lw=1.2, ls="-"):
        self.ax.plot([p[0] for p in pts], [p[1] for p in pts], color=color, lw=lw, ls=ls, solid_capstyle="butt")

    def text(self, x, y, s, fs=7, bold=False, color=INK, ha="left", va="center", rot=0):
        self.ax.text(x, y, s, fontsize=fs, fontweight="bold" if bold else "normal", color=color, ha=ha, va=va, rotation=rot)

    def balloon(self, x, y, s, r=3.2):
        self.ax.add_patch(Circle((x, y), r, fc=PAPER, ec=INK, lw=1.0))
        self.ax.text(x, y, s, ha="center", va="center", fontsize=6.2, fontweight="bold")

    def tag(self, x, y, text, sub=""):
        """ISA-style instrument bubble with a tag above and a number below the line."""
        self.ax.add_patch(Circle((x, y), 5.2, fc=PAPER, ec=INK, lw=1.0))
        self.ax.plot([x - 5.2, x + 5.2], [y, y], color=INK, lw=0.6)
        a, b = (text.split("-") + [""])[:2]
        self.ax.text(x, y + 2.2, a, ha="center", va="center", fontsize=6.4, fontweight="bold")
        self.ax.text(x, y - 2.4, b, ha="center", va="center", fontsize=6.4)
        if sub:
            self.ax.text(x + 7.2, y, sub, ha="left", va="center", fontsize=6.2)

    def table(self, x, y, widths, rows, fs=6.2, rh=4.6, header=True):
        """Table with top-left at (x, y); rows are lists of strings."""
        cy = y
        for i, r in enumerate(rows):
            cx = x
            if header and i == 0:
                self.ax.add_patch(Rectangle((x, cy - rh), sum(widths), rh, fc="#ECEAE2", ec=INK, lw=0.6))
            for w, c in zip(widths, r):
                self.ax.add_patch(Rectangle((cx, cy - rh), w, rh, fc="none", ec=RULE, lw=0.4))
                self.ax.text(cx + 1.2, cy - rh / 2, c, fontsize=fs, va="center", fontweight="bold" if (header and i == 0) else "normal")
                cx += w
            cy -= rh
        return cy


# ====================================================================== DT-001 system architecture
def system_architecture(asset: dict, server_url: str = "http://SERVER:8000") -> plt.Figure:
    s = Sheet("DT-001", "System architecture", 1, asset)
    top, bot = 280, 56
    s.lane(14, bot, 84, top - bot, "FIELD (at the transformer)", FIELD_C)
    s.lane(103, bot, 66, top - bot, "EDGE (kiosk / panel)", EDGE_C)
    s.lane(174, bot, 40, top - bot, "NETWORK", NET_C)
    s.lane(219, bot, 106, top - bot, "TWIN SERVER (PC, VM or edge box)", SRV_C)
    s.lane(330, bot, 76, top - bot, "CLIENTS", CLI_C)

    # field
    s.box(18, 188, 70, 76, f"{asset.get('name', 'Transformer-1')}", [f"{asset.get('rating_kVA', '')} kVA  {asset.get('hv_voltage_V', 0) / 1000:g}/{asset.get('lv_voltage_V', 0) / 1000:g} kV",
                                                              f"{asset.get('vector_group', '')}  {asset.get('cooling', '')}", "oil-immersed, conservator, breather"], fc="#FFFFFF", lw=1.6)
    inst = [("TT-101", "OTI top oil", 255), ("TT-102", "WTI winding", 244), ("TT-103", "Ambient", 233), ("LT-101", "Oil level", 222),
            ("CT-201..204", "R Y B N current", 211), ("CT-205", "Tank earth", 200), ("VT-201..203", "R Y B voltage", 189)]
    for i, (tg, d, yy) in enumerate(inst):
        pass
    s.text(21, 240, "Instruments on the unit", 6.8, True, MUTED)
    ys = [233, 226, 219, 212, 205, 198, 191]
    for (tg, d, _), yy in zip(inst, ys):
        s.text(21, yy, f"{tg}", 6.6, True)
        s.text(46, yy, d, 6.4)
    s.box(18, 120, 70, 56, "Optional condition sensors", ["AT-101 moisture in oil (ppm)", "BR-101 silica gel colour", "relay contacts: Buchholz, PRD,", "OTI/WTI alarm and trip"], fc="#FFFFFF", fs=6.6)
    s.box(18, 62, 70, 50, "LV incomer", ["PM-201 multifunction meter", "S, P, Q, PF, frequency", "RS-485 Modbus RTU"], fc="#FFFFFF", fs=6.6)

    # edge
    s.box(111, 196, 54, 66, "Marshalling box MB-1", ["terminal strip TB1", "signal isolators", "surge protection", "fused 24 V DC"], fc="#FFFFFF", lw=1.3)
    s.box(111, 120, 54, 62, "Gateway GW-1", ["industrial PC or RTU", "AI 4-20 mA x 6, Pt100 x 3", "RS-485 Modbus RTU master", "sample 15 min, buffer on loss"], fc="#FFFFFF", lw=1.6)
    s.box(111, 62, 54, 44, "Supply", ["24 V DC from LT panel", "UPS 30 min", "earthed enclosure IP54"], fc="#FFFFFF")

    # network
    s.box(178, 150, 32, 70, "LAN / VPN", ["Ethernet", "Tailscale or", "site VPN", "TLS"], fc="#FFFFFF", fs=6.6)
    s.box(178, 100, 32, 40, "Optional", ["4G router", "when no LAN"], fc="#FFFFFF", fs=6.6, ec=MUTED)

    # server
    s.box(223, 232, 94, 38, "API  (FastAPI, port 8000)", ["POST /api/ingest   GET /api/datasets/{id}/...", "GET /api/live/stream   /api/status   /api/blueprint.zip"], fc="#FFFFFF", lw=1.4, fs=6.3, tfs=7.8)
    mods = [("Twin engine", "IEC 60076-7 thermal model", "top oil, hot spot, ageing"), ("Analytics", "IS 2026 / IS 1180 / CEA limits", "faults, alerts, sensor checks"),
            ("Health and life", "Health Index 0-100", "remaining life, Monte Carlo"), ("ML second opinion", "Isolation Forest, Prophet", "advisory only"),
            ("Reports", "PDF with 3D snapshot", "blueprint kit"), ("Store", "runs, readings (parquet)", "alert queue")]
    for i, (t, a, b) in enumerate(mods):
        s.box(223 + (i % 2) * 48, 192 - (i // 2) * 42, 46, 38, t, [a, b], fc="#FFFFFF", fs=6.2, tfs=7.4)
    s.box(223, 62, 94, 28, "Live plant simulator (SIMULATED)", ["demo source in place of field + edge; same API"], fc="#FFFFFF", ec=AMBER, fs=6.4, tfs=7.4)

    # clients
    s.box(337, 220, 66, 40, "Dashboard", ["browser, " + server_url.replace("http://", ""), "3D twin, Circuit, Diagnose,", "Simulate, Condition, Export"], fc="#FFFFFF", fs=6.2)
    s.box(337, 168, 66, 44, "Tablet twin", ["Android WebView or browser", "/?view=tablet", "inject faults, live alerts"], fc="#FFFFFF", fs=6.2)
    s.box(337, 116, 66, 44, "Phone: TX Alerts", ["Android app / PWA", "notification and response", "text for each alert"], fc="#FFFFFF", fs=6.2)
    s.box(337, 64, 66, 44, "Engineer", ["report PDF, blueprint kit", "CSV / JSON export", "gateway configuration"], fc="#FFFFFF", fs=6.2)

    # flows
    s.arrow(88, 230, 111, 230, "4-20 mA, Pt100", fs=5.6, dy=2.6)
    s.arrow(88, 148, 111, 148, "dry contacts", fs=5.6, dy=2.6)
    s.arrow(88, 84, 111, 84, "RS-485", fs=5.6, dy=2.6)
    s.arrow(138, 196, 138, 182, "", lw=1.2)
    s.arrow(165, 150, 178, 168, "Ethernet", fs=5.6, dx=2, dy=-4.5)
    s.arrow(210, 190, 223, 250, "HTTPS POST", fs=5.6, dx=-1.5, dy=0, ha="right")
    s.arrow(165, 128, 178, 122, "", ls="--", color=MUTED)
    s.arrow(210, 122, 223, 236, "", ls="--", color=MUTED)
    s.arrow(317, 252, 337, 242, "REST JSON", fs=5.6, dy=4.2)
    s.arrow(317, 190, 337, 190, "NDJSON stream", fs=5.6, dy=3)
    s.arrow(317, 136, 337, 136, "alert queue", fs=5.6, dy=3)
    s.arrow(317, 84, 337, 84, "download", fs=5.6, dy=3)
    s.arrow(270, 232, 270, 230, "")
    s.arrow(270, 192, 270, 232, "", both=True, lw=1.0)

    s.text(14, 50, "Notes", 7.4, True)
    for i, t in enumerate(["1. Field signals terminate in MB-1; only the gateway reaches the network. CT secondaries are never opened.",
                           "2. The twin server computes hot spot, ageing, losses, efficiency and life from the measured values; the clients never calculate engineering values.",
                           "3. The Isolation Forest and Prophet detectors are second opinions to the physics twin. Limits follow the India profile (IS 2026, IS 1180, IS 6600, IS 1866, CEA).",
                           "4. In the demonstration the live plant simulator replaces the field and edge columns; every client works unchanged."]):
        s.text(14, 45 - i * 5, t, 6.4)
    return s.fig


# ====================================================================== DT-002 instrumentation and wiring
def instrumentation(asset: dict, th: dict) -> plt.Figure:
    s = Sheet("DT-002", "Instrumentation and signal wiring", 2, asset)
    ts = th["operating"].get("temperature_settings", {})
    # transformer outline with instruments
    s.ax.add_patch(Rectangle((22, 110), 58, 100, fc="#E8E6DD", ec=INK, lw=1.6))
    s.ax.add_patch(Rectangle((20, 210), 62, 4, fc="#CFCCC0", ec=INK, lw=1.2))
    for k in range(4):
        s.ax.add_patch(Rectangle((80 + k * 3, 120), 2, 82, fc="#D9D6CB", ec=INK, lw=0.8))
    s.text(24, 264, "TRANSFORMER-1", 8.5, True)
    s.text(24, 259, "oil-immersed, conservator", 6.4, color=MUTED)
    s.ax.add_patch(Rectangle((28, 232), 38, 14, fc="#E8E6DD", ec=INK, lw=1))        # conservator
    s.text(31, 239, "conservator", 6.2)
    items = [("TT-101", "OTI  top oil", 250, "Pt100 in pocket"), ("TT-102", "WTI  winding", 232, "thermal image"),
             ("LT-101", "oil level", 214, "magnetic gauge"), ("TT-103", "ambient", 196, "shaded stand"),
             ("CT-205", "tank earth", 178, "core balance"), ("AT-101", "moisture (opt.)", 160, "oil probe")]
    for tg, d, y, n in items:
        s.tag(104, y, tg)
        s.text(112, y + 1.5, d, 6.4, True)
        s.text(112, y - 3, n, 5.8, color=MUTED)
    s.text(24, 104, "LV terminals", 7, True)
    for i, (t, x) in enumerate((("2U R", 26), ("2V Y", 38), ("2W B", 50), ("2N N", 62))):
        s.ax.add_patch(Circle((x + 3, 98), 2.2, fc="#8A867A", ec=INK, lw=0.8))
        s.text(x + 3, 92, t, 5.8, ha="center")
    for i, (tg, x) in enumerate((("CT-201", 29), ("CT-202", 41), ("CT-203", 53), ("CT-204", 65))):
        s.ax.add_patch(Circle((x, 84), 3.2, fc=PAPER, ec=INK, lw=1))
        s.text(x, 77, tg, 5.4, ha="center")
        s.line([(x, 95.8), (x, 87.2)], lw=0.9)
    s.text(24, 70, "VT-201..203  direct 230 V taps", 6, color=MUTED)
    s.box(22, 58, 58, 8, "PM-201 meter (RS-485)", [], fc="#FFFFFF", tfs=6.4)

    # marshalling box terminal strip
    s.box(150, 68, 104, 202, "Marshalling box MB-1  ·  terminal strip TB1", [], fc="#F8F7F3", lw=1.4, tfs=8)
    rows = [("TB1-1/2", "TT-101 OTI", "Pt100 3-wire", "AI-1"), ("TB1-3/4", "TT-102 WTI", "Pt100 3-wire", "AI-2"), ("TB1-5/6", "TT-103 ambient", "Pt100 3-wire", "AI-3"),
            ("TB1-7/8", "LT-101 oil level", "4-20 mA loop", "AI-4"), ("TB1-9/10", "CT-205 tank earth", "0-1 A", "AI-5"), ("TB1-11/12", "AT-101 moisture", "4-20 mA loop", "AI-6"),
            ("TB1-13/14", "CT-201 R current", "5 A, S1 S2", "PM-201"), ("TB1-15/16", "CT-202 Y current", "5 A, S1 S2", "PM-201"), ("TB1-17/18", "CT-203 B current", "5 A, S1 S2", "PM-201"),
            ("TB1-19/20", "CT-204 N current", "5 A, S1 S2", "PM-201"), ("TB1-21..24", "VT-201..203 + N", "230 V, 2 A fuse", "PM-201"),
            ("TB1-25/26", "OTI alarm contact", f"set {ts.get('oti_alarm_C', 85):g} C", "DI-1"), ("TB1-27/28", "OTI trip contact", f"set {ts.get('oti_trip_C', 95):g} C", "DI-2"),
            ("TB1-29/30", "WTI alarm contact", f"set {ts.get('wti_alarm_C', 98):g} C", "DI-3"), ("TB1-31/32", "WTI trip contact", f"set {ts.get('wti_trip_C', 120):g} C", "DI-4"),
            ("TB1-33/34", "Buchholz alarm / trip", "dry contact", "DI-5"), ("TB1-35/36", "Pressure relief device", "dry contact", "DI-6"),
            ("TB1-37/38", "24 V DC supply", "fused 2 A", "PSU"), ("TB1-39", "Earth bar", "PE", "PE")]
    s.table(153, 262, [18, 36, 26, 18], [("Terminal", "Signal", "Type", "To")] + rows, fs=5.8, rh=9.6)
    s.line([(80, 250), (150, 250)], lw=0.9)
    s.line([(80, 232), (150, 232)], lw=0.9)
    for y in (250, 232, 214, 196, 178, 160):
        s.line([(109.2, y), (150, y)], lw=0.8, color=MUTED)
        s.line([(82, y), (98.8, y)], lw=0.8, color=MUTED, ls="--")

    # gateway channels
    s.box(290, 150, 114, 120, "Gateway GW-1  (industrial PC / RTU)", [], fc="#EEF3FB", lw=1.4, tfs=8)
    chans = [("AI-1  Pt100", "OTI_C"), ("AI-2  Pt100", "WTI_C"), ("AI-3  Pt100", "ATI_C"), ("AI-4  4-20 mA", "OLI_pct"), ("AI-5  0-1 A", "IEARTH_A"), ("AI-6  4-20 mA", "H2O_ppm"),
             ("RS-485 PM-201", "IR IY IB IN VR VY VB S_kVA P_kW Q_kVAr PF freq_Hz"), ("DI-1..6", "relay contacts (events)")]
    s.table(293, 262, [38, 72], [("Input", "Ingest column")] + chans, fs=6, rh=8)
    s.arrow(254, 215, 290, 215, "signals 24 V", fs=5.8, dy=3)
    s.box(290, 66, 114, 70, "To the twin server", ["Ethernet RJ45 or 4G", f"POST /api/ingest  every 15 min", "rows buffered on the gateway if the link drops", "time source: NTP, IST"], fc="#FFFFFF", fs=6.4)
    s.arrow(347, 150, 347, 136, "", lw=1.3)

    # cable schedule
    s.text(24, 50, "Cable schedule (indicative)", 7.4, True)
    cab = [("C1", "Transformer to MB-1, temperatures", "2 x (3 x 1.5 mm2) screened"), ("C2", "Transformer to MB-1, level, moisture", "2 x (2 x 1.5 mm2) screened"),
           ("C3", "CTs to MB-1", "4 x 2 x 2.5 mm2"), ("C4", "MB-1 to GW-1", "multicore 1.0 mm2"), ("C5", "PM-201 to GW-1", "RS-485 screened pair"), ("C6", "GW-1 to network", "Cat 6")]
    s.table(24, 46, [12, 74, 48], [("No.", "From / to", "Type")] + [list(c) for c in cab], fs=5.8, rh=4.4)
    return s.fig


# ====================================================================== DT-003 software architecture and data flow
def software_architecture(asset: dict) -> plt.Figure:
    s = Sheet("DT-003", "Software architecture and data flow", 3, asset)
    cols = [("1  Ingest", 16, ["Gateway JSON rows", "adapter maps names, units", "cleaning, data-quality flags", "ingest/, POST /api/ingest"]),
            ("2  Twin engine", 94, ["IEC 60076-7 top-oil and hot-spot", "15-minute step, two time constants", "ageing rate, life used", "twin/engine.py, thermal.py"]),
            ("3  Analytics", 172, ["rules: loading, temperature, voltage", "residual drift (measured - twin)", "oil, moisture, earth leakage, turns", "sensor fault layer", "analytics/*.py"]),
            ("4  Health and outlook", 250, ["Health Index 0-100, weakest-link cap", "remaining life, Monte Carlo", "30-day trip risk, 24 h forecast", "twin/forecast.py"]),
            ("5  Interfaces", 328, ["REST JSON, NDJSON stream", "PDF report, blueprint kit", "alert queue for phones", "server/app.py, server/live.py"])]
    for t, x, ls in cols:
        s.box(x, 222, 76, 46, t, ls, fc="#FFFFFF", lw=1.3, fs=6.2, tfs=8.4)
    for x in (92, 170, 248, 326):
        s.arrow(x, 245, x + 2, 245, "", lw=1.6)
    s.text(16, 214, "What is calculated, and by what", 8, True)
    s.table(16, 210, [64, 120, 110, 90], [
        ("Quantity", "Method", "Limit or reference", "Module"),
        ("Top-oil and hot-spot temperature", "exponential response to load and ambient, IEC 60076-7", "98 C normal ageing, 120 C limit (IS 6600)", "twin/thermal.py"),
        ("Insulation ageing and life", "ageing rate 2^((hot spot - 98) / 6)", "180 000 h reference life", "twin/ageing.py"),
        ("Residual (measured - twin)", "persistent drift beyond normal scatter", "4 sigma, 2 h", "analytics/residual.py"),
        ("Loading, overcurrent, voltage", "rules with hysteresis", "1.0 / 1.2 pu, +-6 % (CEA)", "analytics/rules.py, electrical.py"),
        ("Oil level, leak, theft", "level trend and step with no thermal cause", "85 % low level", "analytics/oil.py"),
        ("Moisture, silica gel, earth leakage, turns", "limits on measured columns, winding vs twin", "20 / 30 ppm, 66 %, 0.5 / 2 %, 8 K", "analytics/standards.py"),
        ("Short circuit, through-fault stress", "event peak and cumulative i2t", "trip at 10 pu (IS 2026-5 / IS 1180)", "analytics/through_fault.py"),
        ("Efficiency", "output / (output + core + copper loss at winding temperature)", "0.5 point below nameplate expectation", "twin/condition.py"),
        ("Second opinion", "Isolation Forest on residual, load, unbalance, oil trend; Prophet forecast of top oil", "advisory", "twin/mlview.py"),
    ], fs=6, rh=7)
    s.text(16, 132, "Interfaces", 8, True)
    s.table(16, 128, [92, 116, 176], [
        ("Call", "Carries", "Used by"),
        ("POST /api/ingest", "readings in, as JSON rows", "gateway GW-1"),
        ("POST /api/live/sync, GET /api/datasets/live/...", "live source run, frames, findings, components", "dashboard"),
        ("GET /api/live/stream", "one tick per line (frame, alerts, injections)", "tablet twin"),
        ("GET /api/companion/test-alerts", "alert queue (live alerts flagged live: true)", "phone app, PWA"),
        ("GET /api/live/condition", "condition board against limits", "dashboard Condition page"),
        ("POST /api/datasets/{id}/report.pdf", "PDF report with the 3D snapshot", "dashboard Export"),
        ("GET /api/blueprint.zip", "drawings, schedules, asset and limits, gateway script", "engineer"),
        ("GET /api/status", "server time, ticker, newest alert number", "any client (health check)"),
    ], fs=6, rh=6.4)
    s.text(16, 58, "Time base: 15-minute samples; analytics window 7 days; live source keeps about 15 days. Time zone Asia/Kolkata.", 6.4)
    return s.fig


# ====================================================================== DT-004 single line
def single_line(asset: dict) -> plt.Figure:
    s = Sheet("DT-004", "Single-line diagram", 4, asset)
    hv, lv = asset.get("hv_voltage_V", 11000) / 1000, asset.get("lv_voltage_V", 415)
    y = 190
    s.line([(24, y), (70, y)], lw=2.4)
    s.text(24, y + 10, f"{hv:g} kV supply", 9, True)
    s.box(70, y - 10, 24, 20, "HV VCB", ["52-1"], fc="#FFFFFF", fs=6.8)
    s.line([(94, y), (140, y)], lw=2.4)
    for dx in (0, 7):
        s.ax.add_patch(Circle((114 + dx, y), 3.8, fc=PAPER, ec=INK, lw=1.2))
    s.text(121, y + 9, "protection CTs", 6.4, ha="center")
    s.ax.add_patch(Circle((158, y), 20, fc=PAPER, ec=INK, lw=1.8))
    s.ax.add_patch(Circle((182, y), 20, fc=PAPER, ec=INK, lw=1.8))
    s.text(170, y + 30, f"TX-1  {asset.get('rating_kVA', '')} kVA  {asset.get('vector_group', '')}  {asset.get('cooling', '')}", 9, True, ha="center")
    s.text(170, y - 30, f"{hv:g} kV / {lv / 1000:g} kV   Z = 5 % (assumed)", 7, ha="center", color=MUTED)
    s.line([(140, y), (138, y)], lw=2.4)
    s.line([(138, y), (138.1, y)], lw=2.4)
    s.line([(202, y), (260, y)], lw=2.4)
    for dx in (0, 7, 14):
        s.ax.add_patch(Circle((218 + dx, y), 3.6, fc=PAPER, ec=INK, lw=1.2))
    s.text(225, y + 9, "CT-201..203 (R Y B)", 6.4, ha="center")
    s.box(260, y - 10, 24, 20, "LV ACB", ["52-2"], fc="#FFFFFF", fs=6.8)
    s.line([(284, y), (396, y)], lw=4)
    s.text(396, y + 10, f"{lv:g} V busbar", 9, True, ha="right")
    for x, lab in ((310, "PM-201 meter"), (340, "campus load"), (372, "spare feeder")):
        s.line([(x, y), (x, y - 26)], lw=1.4)
        s.box(x - 14, y - 46, 28, 20, lab, [], fc="#FFFFFF", fs=6.4, tfs=6.8)
    s.line([(190, y - 20), (190, y - 50)], lw=1.4)
    s.line([(180, y - 50), (200, y - 50)], lw=1.8)
    s.line([(183, y - 54), (197, y - 54)], lw=1.4)
    s.line([(186, y - 58), (194, y - 58)], lw=1.1)
    s.text(206, y - 40, "2N solidly earthed (CT-204)", 6.6)
    s.line([(230, y - 20), (230, y - 70)], lw=1.0, ls="--", color=MUTED)
    s.text(234, y - 66, "tank earth strap with CT-205", 6.4, color=MUTED)
    s.text(24, 90, "Protection and alarms", 8, True)
    s.table(24, 86, [70, 60, 110], [("Device", "Setting", "Action"),
                                    ("OTI", "alarm 85 C, trip 95 C", "alarm, then trip HV VCB (practice, confirm)"),
                                    ("WTI", "alarm 98 C, trip 120 C", "alarm, then trip HV VCB (practice, confirm)"),
                                    ("Buchholz relay", "alarm / trip", "trip HV VCB on trip contact"),
                                    ("Pressure relief device", "operated", "trip HV VCB"),
                                    ("Overcurrent", "1.2 pu", "alarm; trip per relay curve")], fs=6.2, rh=6.4)
    return s.fig


# ====================================================================== DT-005 general arrangement
def general_arrangement(asset: dict) -> plt.Figure:
    s = Sheet("DT-005", "General arrangement (schematic, not to scale)", 5, asset, scale="NTS")
    ax = s.ax
    ox, oy, k = 30, 70, 3.9              # drawing origin and scale (mm per drawing unit), over the 105 x 66 unit layout used before
    R = lambda x, y, w, h, fc, lw=1.1: ax.add_patch(Rectangle((ox + x * k, oy + y * k), w * k, h * k, fc=fc, ec=INK, lw=lw))   # noqa: E731
    C = lambda x, y, r, fc="white": ax.add_patch(Circle((ox + x * k, oy + y * k), r * k, fc=fc, ec=INK, lw=1.0))   # noqa: E731
    R(19, 2, 55, 4, "#BDBAAE")
    R(22, 6, 46, 30, "#E8E6DD", 1.6)
    R(20, 36, 54, 2.4, "#CFCCC0", 1.3)
    for i in range(7):
        R(68 + i * 2.1, 9, 1.5, 25, "#D9D6CB", 0.9)
    R(67.5, 31, 16, 1.2, "#9A978C", 0.7)
    R(67.5, 11, 16, 1.2, "#9A978C", 0.7)
    for x, lab in zip((35, 44, 53), ("1U R", "1V Y", "1W B")):
        R(x - 1.1, 38.4, 2.2, 4, "#8A867A", 0.9)
        for j in range(5):
            R(x - 2.4, 42.4 + j * 2.2, 4.8, 1.4, "#F4F1E8", 0.8)
        s.text(ox + x * k, oy + 55.8 * k, lab, 8, True, ha="center")
    for x, lab in zip((62, 66, 70, 73.5), ("2U R", "2V Y", "2W B", "2N N")):
        R(x - 0.9, 38.4, 1.8, 3, "#8A867A", 0.9)
        for j in range(2):
            R(x - 1.7, 41 + j * 1.9, 3.4, 1.2, "#F4F1E8", 0.8)
        s.text(ox + x * k, oy + 46.8 * k, lab, 7, True, ha="center")
    R(9, 46, 22, 7, "#E8E6DD", 1.2)
    R(19, 38.4, 2, 7.6, "#BDBAAE", 0.9)
    R(18, 41, 4, 3, "#9A978C", 0.9)
    C(28, 49.5, 1.5)
    R(10.4, 36, 1.2, 10, "#BDBAAE", 0.9)
    R(8.6, 30, 4.8, 6, "#9FB8E6", 1.1)
    R(9.2, 28.6, 3.6, 1.4, "#CFCCC0", 0.9)
    R(57.2, 38.4, 1.6, 3, "#C9A227", 0.9)
    C(25.2, 29, 2.1)
    C(25.2, 23, 2.1)
    R(33, 22, 14, 8, "white", 1.0)
    R(55, 26, 5, 6, "#BDBAAE", 1.0)
    R(19, 12, 3, 1.6, "#2E7D4F", 0.9)
    C(45, 9.5, 1.1, "#9A978C")
    pts = [(1, 44, 61, 44, 53.5), (2, 67.5, 61, 67.5, 44.5), (3, 6, 60, 12, 52.5), (4, 25, 60, 28, 51), (5, 4, 46, 18, 42.5), (6, 3, 37, 8.6, 33), (7, 16.5, 32, 23.1, 29.6),
           (8, 12, 22, 23.2, 23.2), (9, 62, 18, 58, 26), (10, 58, 55, 58, 42), (11, 92, 24, 82.8, 22), (12, 40, 15, 40, 22), (13, 10, 13, 19.2, 12.8), (14, 45, 1.8, 45, 8.4)]
    for n, x, y, tx, ty in pts:
        s.line([(ox + x * k, oy + y * k), (ox + tx * k, oy + ty * k)], color=MUTED, lw=0.7)
        s.balloon(ox + x * k, oy + y * k, str(n), 3.4)
    leg = ["HV bushings 1U 1V 1W (R Y B)", "LV bushings 2U 2V 2W 2N", "Conservator", "Oil level gauge LT-101", "Buchholz relay", "Breather, silica gel, oil seal cup",
           "Top-oil indicator TT-101", "Winding indicator TT-102", "Off-circuit tap changer", "Pressure relief device", "Radiators", "Rating and diagram plate",
           "Tank earthing pad (CT-205 on strap)", "Drain valve and sampling point"]
    s.text(326, 270, "Legend", 8, True)
    for i, t in enumerate(leg):
        s.balloon(332, 262 - i * 9.2, str(i + 1), 3.0)
        s.text(338, 262 - i * 9.2, t, 6.6)
    s.text(30, 62, "Schematic only: dimensions, masses and oil volume are on the manufacturer's general arrangement drawing.", 6.6, color=MUTED)
    return s.fig


def all_sheets(asset: dict, th: dict, server_url: str = "http://SERVER:8000") -> list[tuple[str, plt.Figure]]:
    return [("DT-001_system_architecture", system_architecture(asset, server_url)), ("DT-002_instrumentation_wiring", instrumentation(asset, th)),
            ("DT-003_software_architecture", software_architecture(asset)), ("DT-004_single_line", single_line(asset)),
            ("DT-005_general_arrangement", general_arrangement(asset))]
