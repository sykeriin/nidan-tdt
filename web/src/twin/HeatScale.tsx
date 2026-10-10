// The heat scale bar (°C), drawn like a drawing's legend, with the live temperatures marked on it.
// The gap between measured and twin top-oil is hatched and dimensioned: the "reality vs physics" story in one glance.
import { usePlayerIndex, player } from "../player/player";
import { HEAT_MAX, HEAT_MIN, heatGradient, heatPos } from "../data/heat";
import { trustOf } from "../data/fields";

const num = (v: unknown) => (typeof v === "number" ? v : null);
const TICKS = [20, 40, 60, 80, 100, 120, 140];

export function HeatScale({ meterOnly, otiSuspect }: { meterOnly: boolean; otiSuspect: boolean }) {
  const i = usePlayerIndex();
  if (i < 0) return null;
  const amb = num(player.value("amb_C"));
  const otiRaw = meterOnly ? null : num(player.value("OTI_C"));
  const suspect = otiRaw !== null && trustOf("OTI_C", otiRaw, (player.value("dq_flags") as string) ?? "", otiSuspect) === "suspect";
  const oti = suspect ? null : otiRaw; // never draw a gap to a reading the backend flags as untrustworthy
  const twinOil = num(player.value("twin_oil_C"));
  const hs = num(player.value("hs_ageing_C"));
  const twinHs = num(player.value("twin_hs_C"));
  const res = meterOnly || suspect ? null : num(player.value("residual_oil_C"));
  const H = 220;
  const y = (c: number) => H - heatPos(c) * H;
  const marks: { c: number | null; cls: string; label: string }[] = [
    { c: amb, cls: "amb", label: "ambient" },
    { c: twinOil, cls: "twin", label: "top-oil, twin" },
    { c: oti, cls: "meas", label: "top-oil, measured" },
    { c: twinHs, cls: "twin hollow", label: "hot-spot, twin" },
    { c: hs !== twinHs ? hs : null, cls: "meas hollow", label: "hot-spot, measured" },
  ];
  return (
    <figure className="heatscale" aria-label="Temperature scale">
      <figcaption>Temperature <span>°C</span></figcaption>
      {suspect && <p className="hs-suspect">Top-oil sensor {otiRaw!.toFixed(1)} °C: suspect, not plotted</p>}
      <div className="hs-body" style={{ height: H }}>
        <div className="hs-bar" style={{ background: heatGradient() }} />
        {TICKS.map((t) => <span key={t} className="hs-tick" style={{ top: y(t) }}>{t}</span>)}
        {oti !== null && twinOil !== null && Math.abs(oti - twinOil) >= 0.5 && (
          <div className="hs-gap" style={{ top: y(Math.max(oti, twinOil)), height: Math.abs(y(oti) - y(twinOil)) }}>
            <span className="hs-dim">{res !== null ? `${res >= 0 ? "+" : "−"}${Math.abs(res).toFixed(1)} K` : ""}</span>
          </div>
        )}
        {marks.filter((m) => m.c !== null && m.c >= HEAT_MIN - 5 && m.c <= HEAT_MAX + 5).map((m) => (
          <span key={m.label} className={`hs-mark ${m.cls}`} style={{ top: y(m.c!) }}>
            <em>{m.label} {m.c!.toFixed(1)}</em>
          </span>
        ))}
      </div>
    </figure>
  );
}
