// Life clock (right margin): hand position = cumulative insulation life used, 1 turn = 1 day of normal life.
// Blue hand: expected (healthy twin, days_aged_cum). Vermilion hand: actual (days_aged_actual_cum). When the
// vermilion hand runs ahead, the fault is costing life. Values from frames; the hand angle is presentation.
import { player, usePlayerIndex } from "../player/player";

const num = (v: unknown) => (typeof v === "number" ? v : null);
const R = 34;
const TICKS = Array.from({ length: 24 }, (_, i) => i);

export function LifeClock({ meterOnly, perDay = false }: { meterOnly: boolean; perDay?: boolean }) {
  const i = usePlayerIndex();
  if (i < 0) return null;
  const e = num(player.value("days_aged_cum", i));
  const a = meterOnly ? null : num(player.value("days_aged_actual_cum", i));
  const v = num(player.value("aging_rate_actual", i));
  const vExp = num(player.value("aging_rate", i));
  // replay: cumulative life, 1 turn = 1 day. Simulate: rate, a full turn = normal ageing (pegged beyond it)
  const f = (x: number | null) => (x === null ? "—" : x >= 1000 ? x.toExponential(1) : x >= 100 ? x.toFixed(0) : x.toFixed(2));
  const deg = (d: number) => (perDay ? Math.min(1, d) : d % 1) * 360;
  return (
    <figure className="lifeclock" aria-label="Insulation life clock">
      <figcaption>Life clock <span>{perDay ? "full turn = normal ageing (1 day per day)" : "paper insulation, 1 turn = 1 day"}</span></figcaption>
      <div className="lc-body">
        <svg width={2 * R + 8} height={2 * R + 8} viewBox={`${-R - 4} ${-R - 4} ${2 * R + 8} ${2 * R + 8}`} aria-hidden="true">
          <circle r={R} className="lc-face" />
          {TICKS.map((t) => (
            <line key={t} y1={-R} y2={t % 6 === 0 ? -R + 7 : -R + 3} transform={`rotate(${t * 15})`} className="lc-tick" />
          ))}
          {e !== null && <line y2={-R + 8} className="lc-hand t" transform={`rotate(${deg(e)})`} />}
          {a !== null && <line y2={-R + 3} className="lc-hand m" transform={`rotate(${deg(a)})`} />}
          <circle r={2.4} className="lc-pin" />
        </svg>
        <table className="lc-table">
          <tbody>
            <tr><th />
              <th className="t">{perDay ? "full cooling" : "expected"}</th>{!meterOnly && <th className="m">{perDay ? "this cooling" : "actual"}</th>}</tr>
            <tr><th scope="row">ageing</th>
              <td className="t">{f(vExp)}</td>{!meterOnly && <td className="m">{f(v)}</td>}</tr>
            <tr><th scope="row">{perDay ? "days / day" : "life used"}</th>
              <td className="t">{f(e)}</td>{!meterOnly && <td className="m">{f(a)}</td>}</tr>
          </tbody>
        </table>
      </div>
      <p className="lc-units">{perDay ? "days of paper life used per day at this steady state" : "ageing in × normal rate, life in days"}</p>
    </figure>
  );
}
