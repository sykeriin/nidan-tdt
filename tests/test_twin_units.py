"""Amps regression (FINAL_PRD §3.3, §15): the library's load input is LV amps.

Per-unit is silently read as amps and gives near-ambient temperatures. These tests
fail if anyone feeds per-unit, or if asset.yaml's rated current drifts from the rating.
"""
import math

import pytest

from twin.smoke import AMBIENT_C, load_asset, run_constant


@pytest.fixture(scope="module")
def asset():
    return load_asset()


def test_rated_current_matches_rating(asset):
    expected = asset["rating_kVA"] * 1000 / (math.sqrt(3) * asset["lv_voltage_V"])
    assert asset["i_rated_A"] == pytest.approx(expected, abs=1.0)


def test_rated_amps_gives_rated_top_oil_rise(asset):
    # ONAN defaults: 60 K top-oil rise + 10 K ambient surcharge at rated load, steady state.
    oil = run_constant(asset["i_rated_A"], asset).iloc[-1]["top_oil_temperature"]
    assert oil - AMBIENT_C == pytest.approx(70.0, abs=2.0)


def test_per_unit_input_is_near_ambient(asset):
    # Documents the pitfall: 1.0 "pu" is read as 1 A, so only no-load loss heats the oil.
    oil = run_constant(1.0, asset).iloc[-1]["top_oil_temperature"]
    assert oil - AMBIENT_C < 25.0


def test_amps_vs_per_unit_gap_is_large(asset):
    amps = run_constant(asset["i_rated_A"], asset).iloc[-1]["top_oil_temperature"]
    pu = run_constant(1.0, asset).iloc[-1]["top_oil_temperature"]
    assert amps - pu > 40.0
