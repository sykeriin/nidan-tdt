// Heat balance (field, bottom right): where the heat comes from and where it goes, as one drawn line.
// heat in = core (losses_noload_W) + windings (losses_load_W); out = to air (heat_dissipated_W);
// the difference is held by oil and steel (heat_stored_W). All backend values, all est.
import { player, usePlayerIndex } from "../player/player";
import { kW } from "../twin/HeatFlow";

const num = (v: unknown) => (typeof v === "number" ? v : null);

export function HeatBalance() {
  const i = usePlayerIndex();
  if (i < 0) return null;
  const v = (k: string) => num(player.value(k, i));
  const core = v("losses_noload_W"), wind = v("losses_load_W"), tot = v("losses_total_W");
  const out = v("heat_dissipated_W"), st = v("heat_stored_W");
  if (tot === null) return null;
  const state = st === null ? "" : Math.abs(st) < 50 ? "steady: heat in = heat out" : st > 0 ? "oil heating up" : "oil cooling down";
  return (
    <figure className="heatbal" aria-label="Heat balance">
      <figcaption>Heat balance <span className="est">est.</span></figcaption>
      <table>
        <tbody>
          <tr><th scope="row">core</th><td className="num">{kW(core)}</td></tr>
          <tr><th scope="row">+ windings</th><td className="num">{kW(wind)}</td></tr>
          <tr className="sum"><th scope="row">= heat in</th><td className="num">{kW(tot)}</td></tr>
          <tr><th scope="row">− to air</th><td className="num">{kW(out)}</td></tr>
          <tr className="sum"><th scope="row">= stored</th><td className="num">{st === null ? "—" : `${st >= 0 ? "+" : "−"}${kW(Math.abs(st))}`}</td></tr>
        </tbody>
      </table>
      <p>{state}</p>
    </figure>
  );
}
