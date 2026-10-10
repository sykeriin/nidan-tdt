"""Step 1 READ (Tier 1: CSV/TSV/TXT and Excel, all sheets)."""
import csv
import io
from pathlib import Path

import pandas as pd

ENCODINGS = ("utf-8-sig", "utf-8", "latin-1")
DELIMS = ",;\t|"


def _decode(raw: bytes) -> tuple[str, str]:
    for enc in ENCODINGS:
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    raise ValueError("undecodable file")


def _header_row(lines: list[str], delim: str) -> int:
    """First line whose field count matches the dominant field count (skips metadata rows on top)."""
    counts = [len(next(csv.reader([ln], delimiter=delim))) for ln in lines[:50] if ln.strip()]
    if not counts:
        return 0
    modal = max(set(counts), key=counts.count)
    for i, ln in enumerate(lines[:50]):
        if ln.strip() and len(next(csv.reader([ln], delimiter=delim))) == modal:
            return i
    return 0


def read_text(path: Path) -> list[tuple[str, pd.DataFrame, dict]]:
    text, enc = _decode(path.read_bytes())
    lines = text.splitlines()
    sample = "\n".join(lines[:50])
    try:
        delim = csv.Sniffer().sniff(sample, delimiters=DELIMS).delimiter
    except csv.Error:
        delim = max(DELIMS, key=sample.count)
    skip = _header_row(lines, delim)
    df = pd.read_csv(io.StringIO(text), sep=delim, skiprows=skip)
    return [(path.name, df, {"encoding": enc, "delimiter": delim, "skipped_rows": skip})]


def read_excel(path: Path) -> list[tuple[str, pd.DataFrame, dict]]:
    out = []
    for sheet, raw in pd.read_excel(path, sheet_name=None, header=None).items():
        raw = raw.dropna(how="all").dropna(axis=1, how="all")
        if raw.empty:
            continue
        # header = first row with at least half of the columns filled
        filled = raw.notna().sum(axis=1)
        hdr = raw.index[filled >= max(2, raw.shape[1] / 2)][0] if (filled >= 2).any() else raw.index[0]
        df = raw.loc[hdr:].iloc[1:].copy()
        df.columns = [str(c).strip() for c in raw.loc[hdr]]
        df = df.reset_index(drop=True).infer_objects()
        for c in df.columns:  # Excel gives object columns for mixed cells
            if pd.api.types.is_object_dtype(df[c]) or pd.api.types.is_string_dtype(df[c]):
                num = pd.to_numeric(df[c], errors="coerce")
                if num.notna().sum() >= 0.9 * df[c].notna().sum() and df[c].notna().any():
                    df[c] = num
        out.append((f"{path.name}:{sheet}", df, {"sheet": sheet, "skipped_rows": int(hdr)}))
    return out


def read(path) -> list[tuple[str, pd.DataFrame, dict]]:
    """Return [(table_name, raw_frame, read_info)] for one file."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext in (".csv", ".tsv", ".txt"):
        return read_text(path)
    if ext in (".xlsx", ".xlsm", ".xls"):
        return read_excel(path)
    raise ValueError(f"unsupported file type {ext} (Tier 1: CSV/Excel)")
