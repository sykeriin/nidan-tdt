// Life clock on the active part: hand position = cumulative insulation life used (1 turn = 1 day of normal life).
// Blue hand: expected (healthy twin, days_aged_cum). Vermilion hand: actual (days_aged_actual_cum). When the
// vermilion hand runs ahead, the fault is costing life. Ageing rate V and both totals are printed beneath, with
// expected vs actual drawn as two dimension lines. All values from frames; the hand angle is presentation.
import { useFrame } from "@react-three/fiber";
import { Html } from "@react-three/drei";
import { useRef } from "react";
import { player } from "../player/player";

const num = (v: unknown) => (typeof v === "number" ? v : null);
const R = 30;
const LX = 120, LY = 150; // box offset from the winding it reads (px)
const TICKS = Array.from({ length: 24 }, (_, i) => i);

export function LifeClock({ meterOnly }: { meterOnly: boolean }) {
  const exp = useRef<SVGLineElement>(null);
  const act = useRef<SVGLineElement>(null);
  const text = useRef<HTMLDivElement>(null);
  const dimE = useRef<SVGLineElement>(null);
  const dimA = useRef<SVGLineElement>(null);
  const last = useRef(-2);

  useFrame(() => {
    const i = player.index;
    if (i === last.current || !text.current) return;
    last.current = i;
    const e = num(player.value("days_aged_cum", i));
    const a = num(player.value("days_aged_actual_cum", i));
    const v = num(player.value("aging_rate_actual", i));
    const src = player.value("ageing_source", i) === "measured" ? "measured" : "twin";
    const hand = (el: SVGLineElement | null, d: number | null) => {
      if (!el) return;
      el.style.visibility = d === null ? "hidden" : "visible";
      el.setAttribute("transform", `rotate(${((d ?? 0) % 1) * 360})`);
    };
    hand(exp.current, e);
    hand(act.current, meterOnly ? null : a);
    const span = Math.max(e ?? 0, a ?? 0) || 1;
    dimE.current?.setAttribute("x2", String(4 + 118 * ((e ?? 0) / span)));
    dimA.current?.setAttribute("x2", String(4 + 118 * ((a ?? 0) / span)));
    if (dimA.current) dimA.current.style.visibility = meterOnly ? "hidden" : "visible";
    text.current.innerHTML =
      `<span class="lc-v"><b class="${src === "measured" ? "m" : "t"}">${v === null ? "—" : v.toFixed(2)}</b> × normal ageing</span>` +
      `<span class="lc-row t">expected ${e === null ? "—" : e.toFixed(2)} d</span>` +
      (meterOnly ? "" : `<span class="lc-row m">actual ${a === null ? "—" : a.toFixed(2)} d</span>`);
  });

  return (
    <Html position={[0.62, 0.5, 0.24]} style={{ pointerEvents: "none" }} zIndexRange={[4, 0]}>
      <svg className="lc-leader" width={LX + 2} height={LY + 2} aria-hidden="true"><circle cx={1} cy={1} r={2.5} /><polyline points={`1,1 ${LX - 30},${LY} ${LX},${LY}`} /></svg>
      <figure className="lifeclock" aria-label="Insulation life clock" style={{ left: LX, top: LY - 12 }}>
        <figcaption>Life clock <span>1 turn = 1 day of paper life</span></figcaption>
        <div className="lc-body">
          <svg width={2 * R + 8} height={2 * R + 8} viewBox={`${-R - 4} ${-R - 4} ${2 * R + 8} ${2 * R + 8}`} aria-hidden="true">
            <circle r={R} className="lc-face" />
            {TICKS.map((t) => (
              <line key={t} y1={-R} y2={t % 6 === 0 ? -R + 6 : -R + 3} transform={`rotate(${t * 15})`} className="lc-tick" />
            ))}
            <line ref={exp} y2={-R + 7} className="lc-hand t" />
            <line ref={act} y2={-R + 3} className="lc-hand m" />
            <circle r={2.2} className="lc-pin" />
          </svg>
          <div className="lc-text" ref={text} />
        </div>
        <svg className="lc-dims" width={150} height={20} aria-hidden="true">
          <line x1={4} x2={122} y1={5} y2={5} ref={dimE} className="lc-dim t" />
          <line x1={4} x2={122} y1={14} y2={14} ref={dimA} className="lc-dim m" />
        </svg>
      </figure>
    </Html>
  );
}
