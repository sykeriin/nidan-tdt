"""A second, independent thermal-electrical model: heat balance with temperature-dependent losses and oil viscosity.

The standard IEC 60076-7 model the twin runs is a first-order lag towards an exponent formula. This model starts one
level down, from the heat balance of the oil, so it behaves differently where the standard's simplifications show:

    C_th * d(theta_oil)/dt = P_total(theta_winding, K, V)  -  Q_out(theta_oil)
    Q_out  = P_total,rated * (rise / rise_rated)^(1/x)                                          natural-convection cooling (x = 0.8, i.e. rise ~ heat^0.8)
    P_total = P_core * V^2  +  P_I2R * K^2 * (T_w + 234.5)/(T_w,R + 234.5)                    copper: resistance rises with temperature
                             +  (P_eddy + P_stray) * K^2 * KF * (T_w,R + 234.5)/(T_w + 234.5)   eddy and stray fall with temperature
    nu(theta) ~ exp(D / (theta + 273)), D = 2797.3 K                                          mineral-oil viscosity law
    hot-spot rise: first-order lag (winding time constant) towards H * g_R * K^y * (nu(theta_oil)/nu_rated)^(1/4)
                   (colder, thicker oil gives a larger winding-to-oil gradient: IEEE C57.91 Annex G)

At rated load and rated ambient this reproduces the IEC result exactly; elsewhere it differs for physical reasons:
  - the cooling law is nonlinear (heat removed ~ rise^(1/x)), so the oil responds faster when it is far from steady state
    than a fixed-time-constant exponential does;
  - winding copper loss climbs with temperature and eddy/stray loss falls, so a hot day or a heavy load runs warmer;
  - the winding-to-oil gradient grows when the oil is cold and viscous;
  - harmonic currents (K-factor) add eddy loss, and the core loss follows the voltage.

Loss split, the viscosity constant D and the 1/4 viscosity exponents are textbook or modelling choices, tagged
assumed. Nothing is fitted to data and nothing here is validated against a heat-run test.
"""
from __future__ import annotations

import numpy as np

from twin import profile

COPPER_T0 = 234.5          # K, temperature constant of copper resistance
VISC_D = 2797.3            # K, mineral-oil viscosity constant [To verify against IEEE C57.91 Annex G]
VISC_EXP = 0.25            # winding-to-oil gradient scales with viscosity^(1/4), the laminar boundary-layer law [Assumed]
LOSS_SPLIT = {"i2r": 0.88, "eddy": 0.08, "stray": 0.04}   # fractions of rated load loss at rated temperature [Assumed]
AMBIENT_RATED_C = 30.0
# Specific heats, Wh/(kg K): mineral oil ~1.88 kJ/kg K, steel 0.49, copper/iron core-and-coil ~0.43 [typical values]
C_OIL, C_STEEL, C_CORE_COIL = 0.522, 0.136, 0.12
TANK_FRACTION_OF_DRY_MASS = 0.30                           # [Assumed] share of non-oil mass that is tank and fittings


def _nu(theta_C):
    """Oil viscosity up to a constant (only ratios are used)."""
    return np.exp(VISC_D / (np.asarray(theta_C, dtype=float) + 273.0))


def implied_time_constant_h(asset: dict) -> dict | None:
    """Oil time constant implied by the nameplate masses, IEEE C57.91 style: tau = C_th * rated rise / rated losses."""
    a = profile.complete(asset)
    m_oil, m_tot = a.get("oil_mass_kg"), a.get("total_mass_kg")
    if not m_oil or not m_tot or m_tot <= m_oil:
        return None
    dry = float(m_tot) - float(m_oil)
    c_th = float(m_oil) * C_OIL + dry * TANK_FRACTION_OF_DRY_MASS * C_STEEL + dry * (1 - TANK_FRACTION_OF_DRY_MASS) * C_CORE_COIL
    rise = float(a["top_oil_rise_K"]) + float(a["amb_temp_surcharge_K"])
    p_t = float(a["load_loss_W"]) + float(a["no_load_loss_W"])
    return {"thermal_capacity_Wh_per_K": round(c_th, 0), "tau_h": round(c_th * rise / p_t, 2),
            "note": "From the nameplate oil and total mass with typical specific heats and an assumed tank/core split. Treat it as an upper "
                    "bound: not all of that mass reaches the top-oil temperature. The profile's own time constant (IEC default 3 h) is used unless this is switched on."}


class DetailedModel:
    def __init__(self, asset: dict, use_mass_capacity: bool = False):
        a = profile.complete(asset)
        self.a = a
        self.p_nl = float(a["no_load_loss_W"])
        pk = float(a["load_loss_W"])
        self.p_w, self.p_e, self.p_s = pk * LOSS_SPLIT["i2r"], pk * LOSS_SPLIT["eddy"], pk * LOSS_SPLIT["stray"]
        self.p_t_rated = self.p_nl + pk
        self.rise_r = float(a["top_oil_rise_K"]) + float(a["amb_temp_surcharge_K"])    # same effective rated rise as the twin
        self.x = float(a["oil_exponent_x"])
        self.y = float(a["winding_exponent_y"])
        self.H = float(a["hot_spot_factor"])
        self.g_r = float(a["winding_oil_gradient_K"])
        self.tau_w = float(a["winding_time_constant_min"])
        tau_oil_h = float(a["oil_time_constant_min"]) / 60.0
        implied = implied_time_constant_h(a) if use_mass_capacity else None
        self.c_th = implied["thermal_capacity_Wh_per_K"] if implied else tau_oil_h * self.p_t_rated / self.rise_r
        self.theta_oil_rated = AMBIENT_RATED_C + self.rise_r
        self.theta_w_rated = self.theta_oil_rated + self.g_r                      # winding temperature at which the loss split is quoted
        self.nu_rated = float(_nu(self.theta_oil_rated))

    # ------------------------------------------------------------ pieces of the physics
    def winding_temp(self, theta_oil, K):
        return theta_oil + self.g_r * K ** self.y

    def losses(self, theta_oil, K, kfactor=1.0, v_pu=1.0) -> dict:
        tw = self.winding_temp(theta_oil, K)
        ratio = (tw + COPPER_T0) / (self.theta_w_rated + COPPER_T0)
        core = self.p_nl * v_pu ** 2
        i2r = self.p_w * K ** 2 * ratio
        eddy = self.p_e * K ** 2 * kfactor / ratio
        stray = self.p_s * K ** 2 * kfactor / ratio
        return {"core": core, "i2r": i2r, "eddy": eddy, "stray": stray, "total": core + i2r + eddy + stray, "winding_temp_C": tw}

    def _cooling(self, rise, theta_oil, rise_mult):
        """Heat removed by the tank and radiators (W). Exponent 1/x: laminar natural convection, rise ~ heat^0.8."""
        return self.p_t_rated * (np.maximum(rise, 0.0) / (self.rise_r * rise_mult)) ** (1.0 / self.x)

    def _gradient_target(self, theta_oil, K, hot_spot_fac):
        return hot_spot_fac * self.g_r * K ** self.y * (_nu(theta_oil) / self.nu_rated) ** VISC_EXP

    def steady_state(self, K, amb, rise_mult=1.0, kfactor=1.0, v_pu=1.0, hot_spot_fac=None):
        """(top oil, hot spot, loss breakdown) at a constant load, by fixed-point iteration."""
        H = self.H if hot_spot_fac is None else hot_spot_fac
        theta = amb + self.rise_r * (K ** 2 + 0.1) ** self.x                                 # any start; it converges
        for _ in range(60):
            L = self.losses(theta, K, kfactor, v_pu)
            rise = self.rise_r * rise_mult * (L["total"] / self.p_t_rated) ** self.x
            nxt = amb + rise
            if abs(nxt - theta) < 1e-7:
                theta = nxt
                break
            theta = 0.5 * theta + 0.5 * nxt
        L = self.losses(theta, K, kfactor, v_pu)
        return float(theta), float(theta + self._gradient_target(theta, K, H)), L

    # ------------------------------------------------------------ time stepping
    def simulate(self, amps, amb, dt_min, i_rated: float, rise_mult: float = 1.0, hot_spot_fac: float | None = None,
                 kfactor: float = 1.0, v_pu=None, init_K: float | None = None, init_amb: float | None = None) -> dict:
        """Integrate the heat balance. amps/amb/dt_min are arrays (dt_min[i] is the step that ends at sample i; dt_min[0] unused).
        Returns top_oil_C, hot_spot_C and the loss components per sample."""
        amps = np.asarray(amps, dtype=float)
        n = len(amps)
        amb = np.broadcast_to(np.asarray(amb, dtype=float), (n,))
        dt = np.broadcast_to(np.asarray(dt_min, dtype=float), (n,))
        vp = np.ones(n) if v_pu is None else np.broadcast_to(np.asarray(v_pu, dtype=float), (n,))
        H = self.H if hot_spot_fac is None else hot_spot_fac
        K = amps / i_rated
        k0 = K[0] if init_K is None else init_K
        a0 = amb[0] if init_amb is None else init_amb
        theta, hs0, _ = self.steady_state(k0, a0, rise_mult, kfactor, vp[0], H)
        grad = hs0 - theta
        oil, hs = np.empty(n), np.empty(n)
        comp = {k: np.empty(n) for k in ("core", "i2r", "eddy", "stray")}
        for i in range(n):
            if i > 0:
                remaining, h = float(dt[i]), 1.0                       # sub-steps of at most 1 minute
                while remaining > 1e-9:
                    h = min(1.0, remaining)
                    L = self.losses(theta, K[i], kfactor, vp[i])
                    rise = theta - amb[i]
                    theta += h * 60.0 * (L["total"] - float(self._cooling(rise, theta, rise_mult))) / (self.c_th * 3600.0)
                    target = self._gradient_target(theta, K[i], H)
                    grad = target + (grad - target) * np.exp(-h / self.tau_w)
                    remaining -= h
            L = self.losses(theta, K[i], kfactor, vp[i])
            oil[i], hs[i] = theta, theta + grad
            for k in comp:
                comp[k][i] = L[k]
        return {"top_oil_C": oil, "hot_spot_C": hs, **comp}


def effective_time_constant_min(t_min, oil, start: float, end: float) -> float | None:
    """Minutes for the oil to cover 63.2 % of a step, from a simulated response."""
    t_min, oil = np.asarray(t_min, dtype=float), np.asarray(oil, dtype=float)
    target = start + 0.632 * (end - start)
    ok = (oil >= target) if end > start else (oil <= target)
    return float(t_min[ok.argmax()]) if ok.any() else None


# ---------------------------------------------------------------- ageing models, side by side
R_GAS = 8.314


def arrhenius_rate(hot_spot_C, ea_kj_mol: float, ref_C: float = 98.0):
    """Relative ageing rate from the Arrhenius law, 1.0 at ref_C."""
    t = np.asarray(hot_spot_C, dtype=float) + 273.15
    return np.exp(ea_kj_mol * 1000.0 / R_GAS * (1.0 / (ref_C + 273.15) - 1.0 / t))


def ageing_models(lo: float = 70.0, hi: float = 160.0, step: float = 2.0) -> dict:
    hs = np.arange(lo, hi + step, step)
    clip = lambda v: [round(float(x), 5) for x in np.minimum(v, 1e5)]  # noqa: E731
    # Activation energy that makes the Arrhenius law match the IEC 6 K rule at its reference temperature
    ea_equiv = np.log(2) / 6.0 * R_GAS * (98.0 + 273.15) ** 2 / 1000.0
    return {"hot_spot_C": [float(h) for h in hs], "unit": "relative ageing rate (1.0 = design)",
            "models": [
                {"id": "iec_normal", "label": "IEC 60076-7, normal paper (doubles every 6 K above 98 °C)", "rate": clip(2.0 ** ((hs - 98.0) / 6.0))},
                {"id": "iec_upgraded", "label": "IEC 60076-7, thermally upgraded paper (reference 110 °C)", "rate": clip(2.0 ** ((hs - 110.0) / 6.0))},
                {"id": "arrhenius_111", "label": "Arrhenius, 111 kJ/mol (dry, low oxygen)", "rate": clip(arrhenius_rate(hs, 111.0))},
                {"id": "arrhenius_equiv", "label": f"Arrhenius, {ea_equiv:.0f} kJ/mol (matches the 6 K rule at 98 °C)", "rate": clip(arrhenius_rate(hs, ea_equiv))},
            ],
            "note": "The 6 K rule is a straight line in log scale; the Arrhenius law curves, so the two part company away from the "
                    "reference temperature. Activation energies are literature ranges, not measured for this unit."}
