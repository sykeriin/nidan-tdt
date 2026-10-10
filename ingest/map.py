"""Step 4 MAP: synonym-prefilled column -> canonical proposals with confidence."""
import difflib
import fnmatch
import re
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from contracts.canonical import TREND_COLUMNS, is_canonical
from ingest import units

SYNONYMS_PATH = Path(__file__).resolve().parent.parent / "config" / "synonyms.yaml"
ACCEPT = 0.6
INTERMEDIATE = {"I_total", "transformer_id"}  # consumed by derive/shape, not written out


def normalize(header) -> str:
    h = re.sub(r"[\(\[].*?[\)\]]", "", str(header).lower())          # strip "(°F)", "[kA]"
    h = re.sub(r"°\s*[cf]\b", "", h)
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", h)).strip("_")


def load_synonyms(path=SYNONYMS_PATH) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def _phase_scheme(norms: set[str]) -> str:
    return "abc" if norms & {"ia", "i_a", "ic", "i_c", "va", "v_a", "vc", "v_c"} else "ryb"


def _plausible(canonical: str, s: pd.Series, unit: str) -> bool:
    x = pd.to_numeric(s, errors="coerce").dropna()
    if x.empty:
        return False
    kind = units.KIND.get(canonical)
    binary = set(np.unique(x.round(3))) <= {0.0, 0.5, 1.0}
    if kind in ("temperature", "voltage", "current", "apparent", "active") and binary:
        return False  # 0/1 flags are not analog quantities (e.g. Kaggle WTI)
    v = units.convert(x, canonical, unit) if kind else x
    med = float(v.median())
    if kind == "temperature":
        return -10 <= med <= 150
    if kind == "voltage":
        return 100 <= med <= 300 or 330 <= med <= 470 or med > 1000
    if kind == "pf":
        return v.abs().quantile(0.9) <= 1.0
    if kind == "percent":
        return 0 <= med <= 150
    if kind == "freq":
        return 45 <= med <= 65
    return True


def propose(df: pd.DataFrame, synonyms: dict | None = None, skip=("timestamp",)) -> list[dict]:
    syn = synonyms or load_synonyms()
    lookup = {}
    for canon, words in syn.items():
        if canon in ("alarm", "ground_truth"):
            continue
        for w in words:
            lookup[w] = canon
    cols = [c for c in df.columns if c not in skip]
    norms = {c: normalize(c) for c in cols}
    scheme = _phase_scheme(set(norms.values()))
    out = []
    for c in cols:
        n = norms[c]
        canon, conf = None, 0.0
        if is_canonical(str(c)) and c not in INTERMEDIATE:
            canon, conf = str(c), 1.0
        elif any(fnmatch.fnmatch(n, p) for p in syn.get("ground_truth", [])) or n.startswith("gt_"):
            canon, conf = "gt_" + n.removeprefix("gt_"), 0.95
        elif any(fnmatch.fnmatch(n, p) for p in syn.get("alarm", [])):
            canon, conf = "alarm_" + n, 0.95
        elif n in ("ib", "i_b"):
            canon, conf = ("IY" if scheme == "abc" else "IB"), 0.85
        elif n in ("vb", "v_b"):
            canon, conf = ("VY" if scheme == "abc" else "VB"), 0.85
        elif n in lookup:
            canon, conf = lookup[n], 0.9
        elif units.split_unit_suffix(n)[1] and units.split_unit_suffix(n)[0] in lookup:
            canon, conf = lookup[units.split_unit_suffix(n)[0]], 0.85      # organizer style: Load_Current_A
        else:
            close = difflib.get_close_matches(n, list(lookup), n=1, cutoff=0.85)
            if close:
                canon, conf = lookup[close[0]], 0.65
        unit = units.detect(canon, df[c], str(c)) if canon else "-"
        if canon and canon in units.KIND and pd.api.types.is_numeric_dtype(pd.to_numeric(df[c], errors="coerce")):
            if not _plausible(canon, df[c], unit):
                conf *= 0.5
        kind = units.KIND.get(canon)
        out.append({"source": c, "canonical": canon if conf >= ACCEPT else None, "proposed": canon,
                    "confidence": round(conf, 2), "unit": unit,
                    "unit_options": units.OPTIONS.get(kind, []) if kind else []})
    # one source per canonical target: keep the most confident
    best = {}
    for p in out:
        t = p["canonical"]
        if t and not t.startswith(("alarm_", "gt_")) and (t not in best or p["confidence"] > best[t]["confidence"]):
            best[t] = p
    for p in out:
        t = p["canonical"]
        if t and not t.startswith(("alarm_", "gt_")) and best[t] is not p:
            p["canonical"] = None
    return out


def schema_from_proposals(proposals: list[dict]) -> dict:
    return {p["source"]: {"to": p["canonical"], "unit": p["unit"]} for p in proposals if p["canonical"]}


def apply(df: pd.DataFrame, columns: dict) -> tuple[pd.DataFrame, list[str], list[dict]]:
    """Rename + convert units. Unmapped numeric -> extra_<name>. Returns (frame, dropped, conversions)."""
    out = pd.DataFrame(index=df.index)
    dropped, conversions = [], []
    for c in df.columns:
        if c == "timestamp":
            out["timestamp"] = df[c]
            continue
        spec = columns.get(c) or columns.get(str(c))
        if spec and spec.get("to"):
            to, unit = spec["to"], spec.get("unit", "-")
            if to in units.KIND:
                out[to] = units.convert(df[c], to, unit)
                default = units.OPTIONS[units.KIND[to]][0]
                if unit not in ("-", default):
                    conversions.append({"column": str(c), "to": to, "from_unit": unit, "to_unit": default})
            elif to.startswith("alarm_"):
                out[to] = pd.to_numeric(df[c], errors="coerce")
            else:
                out[to] = df[c]
        elif pd.api.types.is_numeric_dtype(df[c]):
            out["extra_" + normalize(c)] = df[c]
        else:
            dropped.append(str(c))
    return out, dropped, conversions


def known_targets() -> set:
    return set(TREND_COLUMNS) | INTERMEDIATE
