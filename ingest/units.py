"""Step 5 UNITS: detect (header hint, then magnitude) and convert to canonical units."""
import re

import numpy as np
import pandas as pd

KIND = {
    **{c: "current" for c in ("IR", "IY", "IB", "IN", "I_total")},
    **{c: "voltage" for c in ("VR", "VY", "VB", "VRY", "VYB", "VBR")},
    **{c: "temperature" for c in ("OTI_C", "WTI_C", "ATI_C")},
    "S_kVA": "apparent", "P_kW": "active", "Q_kVAr": "reactive",
    "PF": "pf", "OLI_pct": "percent", "RH_pct": "percent", "loading_pct": "percent", "freq_Hz": "freq",
}
OPTIONS = {
    "current": ["A", "kA"], "voltage": ["V", "kV"], "temperature": ["C", "F", "K"],
    "apparent": ["kVA", "VA", "MVA"], "active": ["kW", "W", "MW"], "reactive": ["kVAr", "VAr", "MVAr"],
    "pf": ["fraction", "percent"], "percent": ["percent", "fraction"], "freq": ["Hz"],
}
FACTOR = {"A": 1, "kA": 1000, "V": 1, "kV": 1000, "kVA": 1, "VA": 1e-3, "MVA": 1e3, "kW": 1, "W": 1e-3,
          "MW": 1e3, "kVAr": 1, "VAr": 1e-3, "MVAr": 1e3, "fraction_pf": 1, "percent_pf": 0.01,
          "percent": 1, "fraction": 100, "Hz": 1}

_HINTS = [  # (regex on raw header, unit) - order matters (kVA before VA, kA before A ...)
    (r"°\s*f|\bdeg\s*f\b|\(f\)|\[f\]|fahrenheit", "F"), (r"°\s*c|\bdeg\s*c\b|\(c\)|\[c\]|celsius", "C"),
    (r"\(k\)|\[k\]|kelvin", "K"), (r"\bmva\b", "MVA"), (r"\bkva\b", "kVA"), (r"\bva\b", "VA"),
    (r"\bmvar\b", "MVAr"), (r"\bkvar\b", "kVAr"), (r"\bvar\b", "VAr"), (r"\bmw\b", "MW"), (r"\bkw\b", "kW"),
    (r"\bw\b", "W"), (r"\bka\b", "kA"), (r"\ba\b|amps?\b", "A"), (r"\bkv\b", "kV"), (r"\bv\b|volts?\b", "V"),
    (r"%", "percent"),
]


def header_hint(header: str) -> str | None:
    """Unit named in the header, e.g. 'Oil Temp (°F)', 'I_R [kA]'."""
    h = str(header).lower()
    m = re.findall(r"[\(\[]([^\)\]]*)[\)\]]", h)
    for part in m + [h]:  # bracketed units first, then the whole header
        for rx, unit in _HINTS:
            if re.search(rx, part):
                return unit
    return None


def detect(canonical: str, s: pd.Series, header: str = "") -> str:
    kind = KIND.get(canonical)
    if kind is None:
        return "-"
    opts = OPTIONS[kind]
    hint = header_hint(header)
    if hint in opts:
        return hint
    if hint == "percent" and kind == "pf":
        return "percent"
    x = pd.to_numeric(s, errors="coerce")
    x = x[x > 0] if kind in ("current", "voltage", "apparent") else x
    if x.dropna().empty:
        return opts[0]
    med, mx = float(np.nanmedian(x)), float(np.nanmax(x))
    if kind == "current":
        return "kA" if mx < 5 else "A"
    if kind == "voltage":
        return "kV" if med < 1.5 else "V"
    if kind == "temperature":
        return "K" if med > 250 else "F" if med > 80 else "C"
    if kind == "pf":
        return "percent" if med > 1.5 else "fraction"
    if kind == "percent":
        return "fraction" if mx <= 1.5 and canonical != "RH_pct" else "percent"
    return opts[0]


def convert(s: pd.Series, canonical: str, unit: str) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce").astype(float)
    kind = KIND.get(canonical)
    if kind == "temperature":
        return {"C": x, "F": (x - 32) * 5 / 9, "K": x - 273.15}[unit]
    if kind == "pf":
        return x * FACTOR[f"{unit}_pf"]
    if kind is None or unit == "-":
        return x
    return x * FACTOR[unit]
