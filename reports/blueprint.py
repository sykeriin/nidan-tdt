"""Technical blueprint and installation kit for one transformer, built from its asset profile and the India limits.

    build_zip(asset, thresholds, server_url) -> bytes      # the kit engineers install from
    build_pdf(asset, thresholds)             -> bytes      # the drawing sheets alone

The kit holds: a PDF of the drawing sheets and schedules (system architecture, instrumentation and wiring, software architecture, single-line diagram,
general arrangement, terminal and sensor schedules, alarm and trip settings, commissioning checklist), the machine-readable versions of the same schedules, the asset
profile and limits the software reads, and a gateway script that sends readings to the twin.

The drawings are issued sheets with a frame and title block. The general arrangement (DT-005) is a schematic: it shows what is fitted and where, not dimensions.
Take dimensions and weights from the manufacturer's drawing.
"""
from __future__ import annotations

import csv
import io
import zipfile
from datetime import datetime

import yaml

# tag, quantity, ingest column, unit, range, accuracy, location / device, signal, alarm key, trip key
SENSORS = [
    ("TT-101", "Top-oil temperature (OTI)", "OTI_C", "°C", "0 to 150", "±1 K", "Pocket in the tank cover, Pt100", "4-20 mA", "oti_alarm_C", "oti_trip_C"),
    ("TT-102", "Winding temperature (WTI)", "WTI_C", "°C", "0 to 180", "±2 K", "Thermal-image sensor, winding pocket", "4-20 mA", "wti_alarm_C", "wti_trip_C"),
    ("TT-103", "Ambient temperature", "ATI_C", "°C", "-10 to 60", "±0.5 K", "Shaded stand 1 m from the radiators, Pt100", "4-20 mA", "", ""),
    ("LT-101", "Oil level", "OLI_pct", "%", "0 to 100", "±2 %", "Magnetic level gauge on the conservator", "4-20 mA", "", ""),
    ("CT-201", "LV current, R phase", "IR", "A", "0 to 1600", "class 0.5", "CT on LV bushing 2U, 1600/5 A", "5 A", "", ""),
    ("CT-202", "LV current, Y phase", "IY", "A", "0 to 1600", "class 0.5", "CT on LV bushing 2V, 1600/5 A", "5 A", "", ""),
    ("CT-203", "LV current, B phase", "IB", "A", "0 to 1600", "class 0.5", "CT on LV bushing 2W, 1600/5 A", "5 A", "", ""),
    ("CT-204", "Neutral current", "IN", "A", "0 to 500", "class 1", "CT on the neutral bushing 2N", "5 A", "", ""),
    ("CT-205", "Tank earth current", "IEARTH_A", "A", "0 to 100", "±2 %", "Core-balance CT on the tank earthing strap", "0-1 A", "", ""),
    ("VT-201", "LV voltage, R-N", "VR", "V", "0 to 300", "class 0.5", "Direct input from the LV busbar", "230 V", "", ""),
    ("VT-202", "LV voltage, Y-N", "VY", "V", "0 to 300", "class 0.5", "Direct input from the LV busbar", "230 V", "", ""),
    ("VT-203", "LV voltage, B-N", "VB", "V", "0 to 300", "class 0.5", "Direct input from the LV busbar", "230 V", "", ""),
    ("PM-201", "Apparent / active / reactive power, PF", "S_kVA, P_kW, Q_kVAr, PF", "kVA, kW, kVAr", "0 to 1200", "class 0.5S", "Multifunction meter on the LV incomer", "RS-485 Modbus", "", ""),
    ("PM-202", "Supply frequency", "freq_Hz", "Hz", "45 to 55", "±0.05 Hz", "Multifunction meter on the LV incomer", "RS-485 Modbus", "", ""),
    ("AT-101", "Moisture in oil", "H2O_ppm", "ppm", "0 to 100", "±3 ppm", "Capacitive moisture probe in the oil circuit (optional)", "4-20 mA", "", ""),
    ("BR-101", "Breather silica gel saturation", "SILICA_pct", "%", "0 to 100", "estimate", "Colour read by camera or entered at inspection (optional)", "manual / image", "", ""),
]

# IS 2026 terminal marking, with the plant's R/Y/B/N names
TERMINALS = [
    ("1U", "HV", "R", "Line, 11 kV delta", "Cable box / bushing on the cover"),
    ("1V", "HV", "Y", "Line, 11 kV delta", "Cable box / bushing on the cover"),
    ("1W", "HV", "B", "Line, 11 kV delta", "Cable box / bushing on the cover"),
    ("2U", "LV", "R", "Line, 415 V star, 1391 A", "Bushing on the cover or LV box"),
    ("2V", "LV", "Y", "Line, 415 V star, 1391 A", "Bushing on the cover or LV box"),
    ("2W", "LV", "B", "Line, 415 V star, 1391 A", "Bushing on the cover or LV box"),
    ("2N", "LV", "N", "Neutral, solidly earthed", "Bushing on the cover or LV box"),
    ("E1/E2", "Tank", "PE", "Tank earthing, two pads on opposite corners", "Base of the tank"),
]


def _settings(th: dict) -> dict:
    return th["operating"].get("temperature_settings", {})


def sensor_rows(th: dict) -> list[list[str]]:
    ts = _settings(th)
    out = []
    for tag, qty, col, unit, rng, acc, loc, sig, alarm, trip in SENSORS:
        out.append([tag, qty, col, unit, rng, acc, loc, sig, str(ts.get(alarm, "")) if alarm else "", str(ts.get(trip, "")) if trip else ""])
    return out


def sensor_csv(th: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["tag", "quantity", "column", "unit", "range", "accuracy", "location_and_device", "signal", "alarm", "trip"])
    w.writerows(sensor_rows(th))
    return buf.getvalue()


def terminal_csv() -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["terminal_IS2026", "side", "plant_name", "function", "location"])
    w.writerows(TERMINALS)
    return buf.getvalue()


def settings_rows(th: dict) -> list[list[str]]:
    op, ts = th["operating"], _settings(th)
    return [
        ["Top-oil temperature (OTI)", f"{ts.get('oti_alarm_C', 85):g} °C", f"{ts.get('oti_trip_C', 95):g} °C", "Utility practice (CBIP style); confirm"],
        ["Winding temperature (WTI)", f"{ts.get('wti_alarm_C', 98):g} °C", f"{ts.get('wti_trip_C', 120):g} °C", "98 °C = normal ageing (IEC 60076-7 / IS 6600)"],
        ["Load", f"{op['loading_pu']['alarm']:g} pu", f"{op['overcurrent_pu']['alarm']:g} pu", "IS 6600 loading guide"],
        ["Voltage variation", f"±{op['voltage_band_pct']['limit']:g} %", "", "CEA supply voltage band"],
        ["Frequency", f"{op['frequency_Hz']['low']:g} to {op['frequency_Hz']['high']:g} Hz", "", "IEGC band"],
        ["Current unbalance", f"{op['current_unbalance_pct']['warning']:g} %", f"{op['current_unbalance_pct']['alarm']:g} %", "Assumed; confirm"],
        ["Oil level (low)", f"{op['oil_level_pct']['low']:g} %", "", "Assumed; confirm"],
        ["Moisture in oil", f"{op['moisture_ppm']['watch']:g} ppm", f"{op['moisture_ppm']['action']:g} ppm", "IS 1866 / IEC 60422"],
        ["Silica gel saturation", f"replace at {op['silica_gel_saturation_pct']['replace']:g} %", "", "Cobalt-chloride gel: blue dry, pink saturated"],
        ["Tank earth current", f"{op['earth_leakage_pct_of_rated']['warning']:g} % of rated", f"{op['earth_leakage_pct_of_rated']['alarm']:g} % of rated", "Assumed; confirm"],
        ["Short-circuit current", "", f"{op['short_circuit']['trip_pu']:g} pu", "IS 2026-5 withstand, about 1 / impedance"],
        ["Top-oil rise rate", f"{op['oil_rise_rate_K_per_h']['warning']:g} K/h", "", "Utility practice; confirm"],
    ]


CHECKLIST = [
    "Nameplate data matches config/asset.yaml (rating, voltages, vector group, losses, cooling, impedance).",
    "Tank earthed at both pads; neutral earth resistance measured and recorded.",
    "OTI and WTI contacts set to the alarm and trip values in the settings table and tested with a simulated rise.",
    "Buchholz relay, pressure relief device and oil level gauge wired and alarm-tested.",
    "CT ratios and polarity checked; CT secondaries never open; neutral and tank earth CTs wired.",
    "Gateway reaches the server; readings appear in the dashboard Live source with plausible values.",
    "Silica gel is blue (dry) and the oil seal cup is filled.",
    "Oil sample taken and moisture, breakdown voltage and dissolved gases recorded as the baseline.",
    "Alert delivery tested: an injected test alert reaches the engineer's phone.",
]


# ---------------------------------------------------------------- drawings (reports/drawings.py)
def sheets(asset: dict, th: dict, server_url: str = "http://SERVER:8000", svg: bool = False) -> list[tuple[str, bytes]]:
    """The five A3 drawing sheets as PNG (for the PDF) or SVG (for the kit)."""
    import matplotlib.pyplot as plt
    from reports import drawings as D
    out = []
    for name, fig in D.all_sheets(asset, th, server_url):
        buf = io.BytesIO()
        fig.savefig(buf, format="svg" if svg else "png", dpi=150)
        plt.close(fig)
        out.append((name, buf.getvalue()))
    return out


# ---------------------------------------------------------------- PDF
def build_pdf(asset: dict, th: dict, server_url: str = "http://SERVER:8000") -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A3, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    ss = getSampleStyleSheet()
    base = ParagraphStyle("b", parent=ss["Normal"], fontName="Helvetica", fontSize=9, leading=12)
    cell = ParagraphStyle("c", parent=base, fontSize=8, leading=10)
    cellb = ParagraphStyle("cb", parent=cell, fontName="Helvetica-Bold")
    h1 = ParagraphStyle("h1", parent=base, fontName="Helvetica-Bold", fontSize=18, leading=22)
    h2 = ParagraphStyle("h2", parent=base, fontName="Helvetica-Bold", fontSize=12, leading=16, spaceBefore=8, spaceAfter=4)
    small = ParagraphStyle("s", parent=base, fontSize=8, textColor=colors.HexColor("#6B6A63"))
    buf = io.BytesIO()
    page = landscape(A3)
    m = 6 * mm
    doc = SimpleDocTemplate(buf, pagesize=page, leftMargin=m, rightMargin=m, topMargin=m, bottomMargin=m,
                            title=f"{asset.get('name', 'Transformer')} technical blueprint")
    W, H = page[0] - 2 * m, page[1] - 2 * m

    def sheet_img(png: bytes) -> Image:
        w, h = ImageReader(io.BytesIO(png)).getSize()
        k = min((W - 14) / w, (H - 16) / h)
        return Image(io.BytesIO(png), width=w * k, height=h * k)

    def table(rows, widths, header=True):
        t = Table([[Paragraph(str(c), cellb if (header and i == 0) else cell) for c in r] for i, r in enumerate(rows)], colWidths=[(W - 24 * mm) * w for w in widths], repeatRows=1 if header else 0)
        st = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 1), (-1, -1), 0.3, colors.HexColor("#D9D6CB")),
              ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]
        if header:
            st.append(("LINEBELOW", (0, 0), (-1, 0), 0.9, colors.HexColor("#1B1B18")))
        t.setStyle(TableStyle(st))
        return t

    el: list = []
    for _, png in sheets(asset, th, server_url):          # DT-001 .. DT-005
        el += [sheet_img(png), PageBreak()]
    el += [Spacer(1, 6 * mm), Paragraph(f"{asset.get('name', 'Transformer')}: schedules and settings", h1),
           Paragraph(f"{asset.get('site', '')} · prepared {datetime.now().strftime('%d %b %Y')} · India profile (IS 2026, IS 1180, IS 6600, IS 1866, CEA). "
                     "Values tagged Assumed in config/asset.yaml must be replaced from the nameplate before use.", small), Spacer(1, 4)]
    name = [["Quantity", "Value", "Source tag"]]
    for label, key, unit in [("Rating", "rating_kVA", " kVA"), ("HV voltage", "hv_voltage_V", " V"), ("LV voltage", "lv_voltage_V", " V"), ("Rated LV current", "i_rated_A", " A"),
                             ("Vector group", "vector_group", ""), ("Cooling", "cooling", ""), ("Load loss", "load_loss_W", " W"), ("No-load loss", "no_load_loss_W", " W"),
                             ("Insulation", "insulation", ""), ("Top-oil rise", "top_oil_rise_K", " K"), ("Winding-oil gradient", "winding_oil_gradient_K", " K"),
                             ("Oil time constant", "oil_time_constant_min", " min"), ("Years in service", "years_in_service", " y"), ("Breather", "breather", "")]:
        if key in asset:
            name.append([label, f"{asset[key]}{unit}", "nameplate / datasheet"])
    el += [Paragraph("Nameplate and thermal data", h2), table(name, [0.25, 0.3, 0.45]), Spacer(1, 4),
           Paragraph("Terminal schedule (IS 2026 marking, with the plant's R, Y, B, N names)", h2),
           table([["Terminal", "Side", "Plant name", "Function", "Location"]] + [list(r) for r in TERMINALS], [0.1, 0.08, 0.1, 0.3, 0.42]), PageBreak(),
           Paragraph("Instrument and sensor schedule", h2),
           table([["Tag", "Quantity", "Column", "Unit", "Range", "Accuracy", "Location and device", "Signal", "Alarm", "Trip"]] + sensor_rows(th),
                 [0.05, 0.17, 0.1, 0.05, 0.07, 0.07, 0.25, 0.08, 0.05, 0.05]),
           Spacer(1, 6), Paragraph("Alarm and trip settings", h2),
           table([["Quantity", "Alarm / watch", "Trip / action", "Basis"]] + settings_rows(th), [0.25, 0.2, 0.2, 0.35]),
           Spacer(1, 6), Paragraph("Commissioning checklist", h2)]
    el += [Paragraph(f"☐ {c}", base) for c in CHECKLIST]
    doc.build(el)
    return buf.getvalue()


# ---------------------------------------------------------------- kit
GATEWAY = '''"""Send readings to the digital twin.

    python send_readings.py --server http://SERVER:8000 --session tx1 --csv readings.csv
    python send_readings.py --server http://SERVER:8000 --session tx1 --modbus 192.168.1.50:502

The CSV needs a timestamp column and any of the columns in sensor_schedule.csv. Readings are posted in batches to
POST /api/ingest and then appear in the dashboard as the dataset u-live-<session>.

Modbus mode is a reference implementation (pip install pymodbus). It reads the holding registers listed in
sensor_schedule.csv's "register" column if you add one; test it against your meter before relying on it.
"""
import argparse
import csv
import json
import time
import urllib.request


def post(server, session, rows):
    req = urllib.request.Request(server.rstrip("/") + "/api/ingest", data=json.dumps({"session": session, "rows": rows}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def convert(row):
    out = {}
    for k, v in row.items():
        if v is None or v == "":
            continue
        try:
            out[k] = float(v)
        except ValueError:
            out[k] = v
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", required=True)
    ap.add_argument("--session", required=True)
    ap.add_argument("--csv")
    ap.add_argument("--modbus")
    ap.add_argument("--batch", type=int, default=200)
    ap.add_argument("--interval", type=float, default=900, help="seconds between Modbus readings (15 minutes)")
    a = ap.parse_args()
    if a.csv:
        with open(a.csv, newline="", encoding="utf-8") as fh:
            rows = [convert(r) for r in csv.DictReader(fh)]
        for i in range(0, len(rows), a.batch):
            res = post(a.server, a.session, rows[i:i + a.batch])
            print("sent", min(i + a.batch, len(rows)), "of", len(rows), "->", res.get("dataset_id"), res.get("rows_total"))
    elif a.modbus:
        from pymodbus.client import ModbusTcpClient
        host, _, port = a.modbus.partition(":")
        client = ModbusTcpClient(host, port=int(port or 502))
        regs = {}
        with open("sensor_schedule.csv", newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r.get("register") and "," not in r["column"]:
                    regs[r["column"]] = (int(r["register"]), float(r.get("scale") or 1))
        while True:
            row = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
            for col, (reg, scale) in regs.items():
                rr = client.read_holding_registers(reg, count=1)
                if not rr.isError():
                    row[col] = rr.registers[0] * scale
            print(post(a.server, a.session, [row]))
            time.sleep(a.interval)
    else:
        ap.error("give --csv or --modbus")


if __name__ == "__main__":
    main()
'''


def readme(asset: dict, server_url: str) -> str:
    name = asset.get("name", "Transformer")
    return f"""# {name}: technical blueprint and installation kit

Built {datetime.now().strftime('%d %b %Y')} from the asset profile and the India limits (IS 2026, IS 1180, IS 6600, IS 1866, CEA).

## What is in this kit

| File | What it is |
|---|---|
| `transformer_blueprint.pdf` | Five A3 drawing sheets (DT-001 system architecture, DT-002 instrumentation and signal wiring, DT-003 software architecture and data flow, DT-004 single-line diagram, DT-005 general arrangement), then the schedules, settings and commissioning checklist |
| `drawings/DT-001 ... DT-005 .svg` | The five drawing sheets as editable vector files |
| `sensor_schedule.csv`, `terminal_schedule.csv` | The same schedules for your wiring and PLC teams |
| `asset.yaml` | The transformer profile the twin reads (rating, voltages, losses, thermal constants) |
| `thresholds_india.yaml` | The limits the alerts use, with the clause or practice each one comes from |
| `gateway/send_readings.py` | Sends readings from a CSV or a Modbus meter to the twin |

## 1. Install the twin software (one PC or server)

```
python -m venv .venv
.venv\\Scripts\\pip install -r requirements.txt       # use .venv/bin/pip on Linux
.venv\\Scripts\\python -m uvicorn server.app:app --host 0.0.0.0 --port 8000
```

Open `{server_url}` in a browser. The dashboard, the tablet view (`/?view=tablet`) and the phone alerts all use this one server.

## 2. Describe your transformer

Edit `asset.yaml` with the nameplate values (replace every entry tagged Assumed) and copy it to `config/asset.yaml` on the server. To monitor another transformer, copy
the file, change the name, ratings and losses, and start another server or session. Nothing else in the software is specific to one unit.

## 3. Fit the instruments

Follow `sensor_schedule.csv` and the drawings. The minimum that gives a useful twin is: top-oil temperature, winding temperature, ambient, three phase
currents, three phase voltages and the oil level. These are usually fitted already, so integration is mostly a gateway and wiring, not new hardware.
The twin calculates hot-spot temperature, ageing, losses, efficiency and the remaining life from them. Moisture, silica gel and tank earth current are optional extras.

## 4. Send readings

```
python gateway/send_readings.py --server {server_url} --session tx1 --csv readings.csv
```

The reading then appears as the dataset `u-live-tx1`. The three condition columns (`H2O_ppm`, `SILICA_pct`, `IEARTH_A`) and the efficiency columns are read by the
detectors when present in the table; for a real device feed they need adding to `config/synonyms.yaml` first. The simulated plant already provides them.

## 5. Set the relay contacts and test

Set the OTI and WTI alarm and trip contacts to the values in the settings table of the PDF. Work through the commissioning checklist on its last page. Install
the TX Alerts app on the engineer's phone and the twin screen on a tablet; set the Backend URL to `{server_url}` (several servers can be listed, separated by commas).

## What this kit does not do

- It is not a certified test report or a design drawing. Dimensions and masses come from the manufacturer.
- Limits marked Practice or Assumed in `thresholds_india.yaml` are common utility settings, not clauses; confirm them with your utility.
- The simulated transformer in the dashboard is for demonstration and training; it is not measured data.
"""


def thresholds_yaml(th: dict) -> str:
    keep = {"operating": th["operating"]}
    return ("# Limits used by the alerts. India profile: IS 2026, IS 1180, IS 6600, IS 1866, CEA.\n"
            "# [Standard] follows the cited clause; [Practice] is common utility practice; [Assumed] is a starting value. Confirm with your utility.\n"
            + yaml.safe_dump(keep, sort_keys=False))


def build_zip(asset: dict, th: dict, server_url: str = "http://SERVER:8000") -> bytes:
    a = {k: v for k, v in asset.items() if k not in ("tags", "profile_notes")}
    sched = sensor_csv(th)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README_INSTALL.md", readme(a, server_url))
        z.writestr("transformer_blueprint.pdf", build_pdf(a, th, server_url))
        for name, svg in sheets(a, th, server_url, svg=True):
            z.writestr(f"drawings/{name}.svg", svg)
        z.writestr("sensor_schedule.csv", sched)
        z.writestr("terminal_schedule.csv", terminal_csv())
        z.writestr("asset.yaml", yaml.safe_dump(a, sort_keys=False))
        z.writestr("thresholds_india.yaml", thresholds_yaml(th))
        z.writestr("gateway/send_readings.py", GATEWAY)
    return buf.getvalue()
