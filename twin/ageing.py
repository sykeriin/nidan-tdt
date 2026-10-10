"""Thermal ageing of normal Kraft paper via the library (IEC 60076-7): relative rate 2^((θh − 98)/6)."""
import numpy as np
import pandas as pd
from transformer_thermal_model.aging import aging_rate_profile
from transformer_thermal_model.transformer import PaperInsulationType

PAPER = {"normal": PaperInsulationType.NORMAL, "thermally_upgraded": PaperInsulationType.THERMAL_UPGRADED}


def rate(hot_spot_C, insulation: str = "normal") -> np.ndarray:
    hs = np.atleast_1d(np.asarray(hot_spot_C, dtype=float))
    out = np.full(hs.shape, np.nan)
    ok = ~np.isnan(hs)
    if ok.any():
        idx = pd.date_range("2000-01-01", periods=int(ok.sum()), freq="min")
        out[ok] = aging_rate_profile(pd.Series(hs[ok], index=idx), PAPER[insulation]).to_numpy()
    return out
