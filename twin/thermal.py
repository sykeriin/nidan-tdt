"""Thin wrapper over transformer-thermal-model (IEC 60076-7). Load is LV AMPS, never per-unit.

run_segment(): the library's public batch API, used by TwinEngine.run().
Stepper: carries the library's three state variables (top-oil, winding and oil hot-spot increments) and calls
the library's own per-step update functions, so streaming reproduces batch exactly (tests/test_engine.py).
"""
import numpy as np
import pandas as pd
from transformer_thermal_model.model import Model
from transformer_thermal_model.schemas import InputProfile, UserTransformerSpecifications
from transformer_thermal_model.schemas.thermal_model.initial_state import InitialLoad
from transformer_thermal_model.transformer import DistributionTransformer


def make_transformer(i_rated_A: float, load_loss_W: float, no_load_loss_W: float, **overrides) -> DistributionTransformer:
    specs = UserTransformerSpecifications(load_loss=load_loss_W, no_load_loss=no_load_loss_W,
                                          nom_load_sec_side=i_rated_A, **overrides)
    return DistributionTransformer(user_specs=specs)


def run_segment(tr: DistributionTransformer, ts: pd.Series, amps: np.ndarray, amb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Top-oil and hot-spot (°C) for one gap-free segment, starting from steady state at the first load."""
    if len(amps) < 2:
        st = Stepper(tr)
        return tuple(np.array([v]) for v in st.reset(float(amps[0]), float(amb[0])))
    prof = InputProfile.create(datetime_index=pd.DatetimeIndex(ts).tz_localize(None), load_profile=amps,
                               ambient_temperature_profile=amb)
    out = Model(temperature_profile=prof, transformer=tr, initial_condition=InitialLoad(initial_load=float(amps[0]))).run()
    df = out.convert_to_dataframe()
    return df["top_oil_temperature"].to_numpy(), df["hot_spot_temperature"].to_numpy()


class Stepper:
    """One-sample-at-a-time version of Model.run() (same library functions, same order of operations)."""

    def __init__(self, tr: DistributionTransformer):
        self.tr = tr
        idx = pd.date_range("2000-01-01", periods=2, freq="15min")
        dummy = InputProfile.create(datetime_index=idx, load_profile=[1.0, 1.0], ambient_temperature_profile=[20.0, 20.0])
        self.m = Model(temperature_profile=dummy, transformer=tr)  # only its per-step helpers are used
        self.top = self.hs_w = self.hs_o = None

    def reset(self, load_A: float, amb_C: float) -> tuple[float, float]:
        """Steady state at this load (library InitialLoad semantics)."""
        s = self.tr.specs
        self.top = self.tr._end_temperature_top_oil(np.array([load_A])) + amb_C
        inc = self.m._calculate_static_hot_spot_increase(np.array([load_A]))[0]
        self.hs_w = inc * s.winding_const_k21
        self.hs_o = inc * (s.winding_const_k21 - 1)
        return float(self.top), float(self.top + self.hs_w - self.hs_o)

    def step(self, load_A: float, amb_C: float, dt_min: float) -> tuple[float, float]:
        s, m = self.tr.specs, self.m
        f1 = m._calculate_f1(dt_min, s.time_const_oil)
        top_k = self.tr._end_temperature_top_oil(np.array([load_A]))
        self.top = m._update_top_oil_temp(self.top, amb_C, top_k, f1)
        static = m._calculate_static_hot_spot_increase(np.array([load_A]))[0]
        f2w = m._calculate_f2_winding(dt_min, s.time_const_windings_array)[0]
        f2o = m._calculate_f2_oil(dt_min, s.time_const_oil)
        self.hs_w = m._update_hot_spot_increase(self.hs_w, static * s.winding_const_k21, f2w)
        self.hs_o = m._update_hot_spot_increase(self.hs_o, static * (s.winding_const_k21 - 1), f2o)
        return float(self.top), float(self.top + self.hs_w - self.hs_o)
