"""Smoke test: run the IEC 60076-7 library on Transformer-1 at rated current (1391 A).

    python -m twin.smoke

Constant load and ambient for 3 days from cold start (oil time constant 180 min),
so the last sample is steady state. Also runs the per-unit mistake (1.0 instead of
1391) to show what the amps bug looks like.
"""
from pathlib import Path

import pandas as pd
import yaml
from transformer_thermal_model.aging import aging_rate_profile
from transformer_thermal_model.model import Model
from transformer_thermal_model.schemas import InputProfile, UserTransformerSpecifications
from transformer_thermal_model.transformer import DistributionTransformer, PaperInsulationType

ASSET = Path(__file__).resolve().parent.parent / "config" / "asset.yaml"
AMBIENT_C = 30.0  # [Assumed] smoke-test constant, Bengaluru April afternoon


def load_asset(path=ASSET) -> dict:
    return {k: (v["value"] if isinstance(v, dict) else v) for k, v in yaml.safe_load(Path(path).read_text(encoding="utf-8")).items()}


def run_constant(load_A: float, asset: dict, ambient_C: float = AMBIENT_C, days: int = 3) -> pd.DataFrame:
    specs = UserTransformerSpecifications(
        load_loss=asset["load_loss_W"],
        no_load_loss=asset["no_load_loss_W"],
        nom_load_sec_side=asset["i_rated_A"],  # AMPS
    )
    idx = pd.date_range("2026-04-01", periods=days * 96, freq="15min")
    prof = InputProfile.create(
        datetime_index=idx,
        load_profile=[load_A] * len(idx),
        ambient_temperature_profile=[ambient_C] * len(idx),
    )
    out = Model(temperature_profile=prof, transformer=DistributionTransformer(user_specs=specs)).run()
    df = out.convert_to_dataframe()
    df["aging_rate"] = aging_rate_profile(out.hot_spot_temp_profile, PaperInsulationType.NORMAL)
    return df


def main() -> None:
    asset = load_asset()
    i_rated = asset["i_rated_A"]
    print(f"Transformer-1: {asset['rating_kVA']} kVA, {asset['lv_voltage_V']} V, I_rated {i_rated} A, "
          f"losses {asset['load_loss_W']}/{asset['no_load_loss_W']} W, ambient {AMBIENT_C} C, 3 days, 15-min\n")
    print(f"{'case':<28}{'load input':>12}{'top-oil C':>11}{'rise K':>8}{'hot-spot C':>12}{'ageing':>9}")
    for label, load in [("rated, amps (correct)", i_rated), ("1.0 pu passed as-is (BUG)", 1.0)]:
        last = run_constant(load, asset).iloc[-1]
        oil, hs = last["top_oil_temperature"], last["hot_spot_temperature"]
        print(f"{label:<28}{load:>12g}{oil:>11.1f}{oil - AMBIENT_C:>8.1f}{hs:>12.1f}{last['aging_rate']:>9.2f}")


if __name__ == "__main__":
    main()
