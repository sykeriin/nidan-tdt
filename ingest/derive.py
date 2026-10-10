"""Step 6 DERIVE ladder (spec §2.6). Every derived value gets __dq_DERIVED_<COL>.

Twin input must be LV amps. Per-unit is never passed on.
"""
import numpy as np
import pandas as pd

SQ3 = np.sqrt(3)
PH = ["IR", "IY", "IB"]
VLN = ["VR", "VY", "VB"]
VLL = ["VRY", "VYB", "VBR"]


def _has(df, c):
    return c in df.columns and df[c].notna().any()


def _flag(df, col, mask=None):
    m = df[col].notna() if mask is None else mask
    df[f"__dq_DERIVED_{col}"] = df.get(f"__dq_DERIVED_{col}", False) | m


def derive(df: pd.DataFrame, asset: dict) -> tuple[pd.DataFrame, list[str]]:
    df = df.copy()
    log = []
    i_rated = asset.get("i_rated_A")
    v_ll_nom = asset.get("lv_voltage_V", 415)

    # HV-side voltages (e.g. 11 kV, or a CPRI test "Applied_Voltage_kV") are not LV phase voltages: set aside
    for v in VLN + VLL:
        if _has(df, v) and df[v].median() > 1000:
            df[f"extra_{v.lower()}_hv"] = df.pop(v)
            log.append(f"{v}: median {df[f'extra_{v.lower()}_hv'].median():.0f} V looks HV-side; kept as extra, not used")
    # a single "voltage" mapped to line-line that actually holds phase-neutral values
    for vn, vl in zip(VLN, VLL):
        if _has(df, vl) and not _has(df, vn) and 180 <= df[vl].median() <= 270:
            df[vn] = df.pop(vl)
            log.append(f"{vl}: values look phase-neutral, used as {vn}")
    # voltages: L-L -> L-N; L-N columns that actually hold L-L values
    for v in VLN:
        if _has(df, v) and 330 <= df[v].median() <= 470:
            df[v] = df[v] / SQ3
            _flag(df, v)
            log.append(f"{v}: values look line-line, divided by sqrt(3)")
    if not any(_has(df, v) for v in VLN) and any(_has(df, v) for v in VLL):
        for vn, vl in zip(VLN, VLL):
            if _has(df, vl):
                df[vn] = df[vl] / SQ3
                _flag(df, vn)
        log.append("VR/VY/VB derived from line-line voltages / sqrt(3)")
    v_ll = df[[v for v in VLN if _has(df, v)]].mean(axis=1) * SQ3 if any(_has(df, v) for v in VLN) else None

    def v_ll_series():
        if v_ll is not None:
            return v_ll.where(v_ll > 100, v_ll_nom).fillna(v_ll_nom)
        return pd.Series(float(v_ll_nom), index=df.index)

    # currents
    if all(_has(df, c) for c in PH):
        pass
    elif _has(df, "I_total"):
        for c in PH:
            df[c] = df["I_total"]
            _flag(df, c)
        log.append("IR=IY=IB=I_total (unbalance disabled)")
    else:
        if not _has(df, "S_kVA") and _has(df, "P_kW") and _has(df, "PF"):
            df["S_kVA"] = df["P_kW"] / df["PF"].abs().where(df["PF"].abs() > 0.05)
            _flag(df, "S_kVA")
            log.append("S_kVA = P_kW / PF")
        if _has(df, "S_kVA"):
            i = df["S_kVA"] * 1000 / (SQ3 * v_ll_series())
            src = "measured V" if v_ll is not None else f"nameplate {v_ll_nom} V"
            log.append(f"IR=IY=IB derived from S_kVA using {src} (unbalance disabled)")
        elif _has(df, "loading_pct") and i_rated:
            i = df["loading_pct"] / 100 * i_rated
            log.append(f"IR=IY=IB derived from loading_pct x I_rated {i_rated} A (unbalance disabled)")
        else:
            i = None
        if i is not None:
            for c in PH:
                df[c] = i
                _flag(df, c)
    if all(_has(df, c) for c in PH):
        df["I_mean"] = df[PH].mean(axis=1)
    df = df.drop(columns=[c for c in ("I_total",) if c in df.columns])

    # S from V and I if missing
    if not _has(df, "S_kVA") and "I_mean" in df and any(_has(df, v) for v in VLN):
        vln = [v for v in VLN if _has(df, v)]
        if len(vln) == 3:
            df["S_kVA"] = sum(df[v] * df[c] for v, c in zip(VLN, PH)) / 1000
        else:
            df["S_kVA"] = SQ3 * v_ll_series() * df["I_mean"] / 1000
        _flag(df, "S_kVA")
        log.append("S_kVA derived from V and I")
    if not _has(df, "P_kW") and _has(df, "S_kVA") and _has(df, "PF"):
        df["P_kW"] = df["S_kVA"] * df["PF"]
        _flag(df, "P_kW")

    return df, log


def add_loading(df: pd.DataFrame, i_rated: float | None) -> pd.DataFrame:
    """loading_pct (required): keep a measured one, else I_mean / I_rated."""
    if "I_mean" in df and i_rated and not _has(df, "loading_pct"):
        df = df.copy()
        df["loading_pct"] = df["I_mean"] / i_rated * 100
        _flag(df, "loading_pct")
    return df
