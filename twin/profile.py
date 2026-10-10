"""Generic distribution-transformer profile: any rating in, a complete tagged parameter set out.

The twin is a physics model driven by a handful of nameplate numbers. This module turns whatever the user knows
(kVA and LV voltage at minimum) into everything the model needs, and records where each value came from:

    Confirmed / User input   typed or read from the nameplate
    Calculated               exact arithmetic on other values (rated current)
    Derived                  solved from other nameplate numbers under a stated assumption (loss split)
    IEC 60076-7 default      the standard's distribution-transformer value, used when the nameplate is silent
    Assumed                  our choice; replace from the nameplate or a datasheet

A nameplate value always beats a default. Nothing here is fitted to data.
"""
from __future__ import annotations

from datetime import date

import numpy as np

# profile key -> (UserTransformerSpecifications argument, IEC 60076-7 default for a distribution transformer, unit, label)
THERMAL = {
    "top_oil_rise_K": ("top_oil_temp_rise", 60.0, "K", "Top-oil temperature rise at rated load"),
    "amb_temp_surcharge_K": ("amb_temp_surcharge", 10.0, "K", "Ambient surcharge (enclosure allowance)"),
    "winding_oil_gradient_K": ("winding_oil_gradient", 23.0, "K", "Winding-to-oil gradient at rated load"),
    "hot_spot_factor": ("hot_spot_fac", 1.2, "", "Hot-spot factor H"),
    "oil_time_constant_min": ("time_const_oil", 180.0, "min", "Oil thermal time constant"),
    "winding_time_constant_min": ("time_const_windings", 4.0, "min", "Winding thermal time constant"),
    "oil_exponent_x": ("oil_exp_x", 0.8, "", "Oil exponent x"),
    "winding_exponent_y": ("winding_exp_y", 1.6, "", "Winding exponent y"),
}
IEC_TAG = "IEC 60076-7 default"

# Typical losses per kVA when the nameplate has none. [Assumed] Replace from the nameplate or a datasheet.
LOAD_LOSS_W_PER_KVA = 10.0
NO_LOAD_LOSS_W_PER_KVA = 1.1

INPUT_FIELDS = (
    "name", "site", "rating_kVA", "lv_voltage_V", "hv_voltage_V", "vector_group", "cooling", "i_rated_A",
    "load_loss_W", "no_load_loss_W", "total_loss_100_W", "total_loss_50_W", "winding_rise_K", "impedance_pct",
    "insulation", "years_in_service", "manufacture_year", "manufacture_month", "breather", "oil_mass_kg", "total_mass_kg",
    "oil_volume_L", *THERMAL,
)


def _num(a: dict, key: str, what: str, positive: bool = True) -> float | None:
    v = a.get(key)
    if v is None or v == "":
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{what} must be a number, got {v!r}") from None
    if not np.isfinite(f) or (positive and f <= 0):
        raise ValueError(f"{what} must be a positive number, got {v!r}")
    return f


def split_losses(total_100_W: float, total_50_W: float) -> tuple[float, float]:
    """(load loss at rated load, no-load loss) from the max total losses at 100 % and 50 % load.

    total(K) = P0 + K^2 * Pk, so Pk = (total100 - total50) / 0.75 and P0 = total100 - Pk. Assumes the two quoted
    totals are at the same temperature and that load loss scales with the square of the load.
    """
    if total_100_W <= total_50_W:
        raise ValueError("total losses at 100 % load must be larger than at 50 % load")
    pk = (total_100_W - total_50_W) / 0.75
    p0 = total_100_W - pk
    if p0 <= 0:
        raise ValueError("the two total-loss figures are inconsistent (they give a negative no-load loss)")
    return pk, p0


def complete(asset: dict, today: date | None = None) -> dict:
    """Fill in everything derivable, without overwriting what is given. Adds `tags` and `profile_notes`."""
    a = dict(asset)
    tags = dict(a.get("tags") or {})
    notes: list[str] = list(a.get("profile_notes") or [])

    def put(key, value, tag, note=None):
        a[key] = value
        tags[key] = tag
        if note:
            notes.append(note)

    for k in INPUT_FIELDS:                       # given values without a tag are user input
        if a.get(k) not in (None, "") and k not in tags:
            tags[k] = "User input"

    kva = _num(a, "rating_kVA", "rating (kVA)")
    volts = _num(a, "lv_voltage_V", "LV voltage (V)")
    if volts is None:
        put("lv_voltage_V", 415.0, "Assumed", "LV voltage not given: assumed 415 V.")
        volts = 415.0
    i_rated = _num(a, "i_rated_A", "rated current (A)")
    if i_rated is None and kva is not None:
        i_rated = round(float(kva * 1000 / (np.sqrt(3) * volts)), 1)
        put("i_rated_A", i_rated, "Calculated")
    if kva is None and i_rated is not None:
        put("rating_kVA", round(float(i_rated * np.sqrt(3) * volts / 1000), 1), "Calculated")
        kva = a["rating_kVA"]

    ll, nll = _num(a, "load_loss_W", "load loss (W)"), _num(a, "no_load_loss_W", "no-load loss (W)")
    t100, t50 = _num(a, "total_loss_100_W", "total loss at 100 % load (W)"), _num(a, "total_loss_50_W", "total loss at 50 % load (W)")
    if ll is None or nll is None:
        if t100 is not None and t50 is not None:
            pk, p0 = split_losses(t100, t50)
            put("load_loss_W", round(pk, 1), "Derived",
                f"Load loss {pk:.0f} W and no-load loss {p0:.0f} W solved from the total losses at 100 % ({t100:.0f} W) and "
                f"50 % ({t50:.0f} W) load, assuming load loss scales with load squared. Verify against the datasheet.")
            put("no_load_loss_W", round(p0, 1), "Derived")
            a["losses_source"] = "derived from total losses at 50 % and 100 % load"
        elif kva is not None:
            put("load_loss_W", round(LOAD_LOSS_W_PER_KVA * kva, 1), "Assumed",
                f"Losses not given: typical {LOAD_LOSS_W_PER_KVA:g} W/kVA load loss and {NO_LOAD_LOSS_W_PER_KVA:g} W/kVA "
                "no-load loss assumed. Replace from the nameplate.")
            put("no_load_loss_W", round(NO_LOAD_LOSS_W_PER_KVA * kva, 1), "Assumed")
            a["losses_source"] = "assumed: typical W per kVA"

    for key, (_, default, _, _) in THERMAL.items():
        if _num(a, key, key, positive=False) is None:
            put(key, default, IEC_TAG)

    if not a.get("insulation"):
        put("insulation", "normal", "Assumed", "Insulation assumed to be normal (non-upgraded) Kraft paper.")

    if a.get("manufacture_year") and not a.get("years_in_service"):
        y = int(a["manufacture_year"])
        m = int(a.get("manufacture_month") or 6)
        now = today or date.today()
        put("years_in_service", round(max(0.0, (now.year - y) + (now.month - m) / 12), 1), "Calculated",
            f"In service about {max(0.0, (now.year - y) + (now.month - m) / 12):.1f} years since {m:02d}/{y}.")

    a["tags"] = tags
    a["profile_notes"] = notes
    return a


def thermal_kwargs(asset: dict) -> dict:
    """Overrides for the thermal library, only for the parameters this profile actually carries."""
    out = {}
    for key, (arg, _, _, _) in THERMAL.items():
        v = asset.get(key)
        if v is not None and v == v:
            out[arg] = float(v)
    return out


def resolve(raw: dict, today: date | None = None) -> dict:
    """UI entry point: validate a typed profile and return the complete tagged one."""
    if _num(raw, "rating_kVA", "rating (kVA)") is None and _num(raw, "i_rated_A", "rated current (A)") is None:
        raise ValueError("enter the rating (kVA) or the rated current (A)")
    a = complete({k: v for k, v in raw.items() if v not in (None, "")}, today)
    a.setdefault("nameplate_source", "user input")
    return a
