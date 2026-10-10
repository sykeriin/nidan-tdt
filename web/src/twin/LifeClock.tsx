// Life clock (right margin): hand position = cumulative insulation life used, 1 turn = 1 day of normal life.
// Blue hand: expected (healthy twin, days_aged_cum). Vermilion hand: actual (days_aged_actual_cum). When the
// vermilion hand runs ahead, the fault is costing life. Values from frames; the hand angle is presentation.
import { player, usePlayerIndex } from "../player/player";

const num = (v: unknown) => (typeof v === "number" ? v : null);
const R = 34;
const TICKS = Array.from({ length: 24 }, (_, i) => i);

export function LifeClock({ meterOnly }: { meterOnly: boolean }) {
  const i = usePlayerIndex();
  if (i < 0) return null;
  const e = num(player.value("days_aged_cum", i));
  const a = meterOnly ? null : num(player.value("days_aged_actual_cum", i));
  const v = num(player.value("aging_rate_actual", i));
  const vExp = num(player.value("aging_rate", i));
  const deg = (d: number) => (d % 1) * 360;
  return (
    <figure className="lifeclock" aria-label="Insulation life clock">
      <figcaption>Life clock <span>paper insulation, 1 turn = 1 day</span></figcaption>
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
              <th className="t">expected</th>{!meterOnly && <th className="m">actual</th>}</tr>
            <tr><th scope="row">ageing</th>
              <td className="t">{vExp === null ? "—" : vExp.toFixed(2)}</td>{!meterOnly && <td className="m">{v === null ? "—" : v.toFixed(2)}</td>}</tr>
            <tr><th scope="row">life used</th>
              <td className="t">{e === null ? "—" : e.toFixed(2)}</td>{!meterOnly && <td className="m">{a === null ? "—" : a.toFixed(2)}</td>}</tr>
          </tbody>
        </table>
      </div>
      <p className="lc-units">ageing in × normal rate, life in days</p>
    </figure>
  );
}
