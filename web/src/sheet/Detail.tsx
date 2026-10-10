// Detail view for a pinned part, docked at the right of the field like a detail on a drawing.
// From GET /components at the cursor: quantities, the governing equation(s) with live values substituted,
// findings on the part and recommended tests. Mini time-history: the same quantities from frames (3 days).
import { useMemo } from "react";
import { player, usePlayerIndex } from "../player/player";
import { useComponents, type PartView } from "../api/client";
import { PART, type PartId } from "../twin/parts";

const num = (v: unknown) => (typeof v === "number" ? v : null);
const LETTERS = "BCDEFGHJKLMNPQRSTUVW"; // detail letters (A is the section)
export const detailLetter = (pinned: PartId[], id: PartId) => LETTERS[pinned.indexOf(id) % LETTERS.length];
const HIST_DAYS = 3;

function Spark({ k }: { k: string }) {
  const i = usePlayerIndex();
  const f = player.frames;
  const d = useMemo(() => {
    if (!f || i < 0 || !f.cols[k]) return null;
    const t1 = f.t[i], t0 = t1 - HIST_DAYS * 86_400_000;
    let j = i;
    while (j > 0 && f.t[j - 1] >= t0) j--;
    const vals: [number, number][] = [];
    for (let n = j; n <= i; n++) { const v = num(f.cols[k][n]); if (v !== null) vals.push([f.t[n], v]); }
    if (vals.length < 2) return null;
    let lo = Infinity, hi = -Infinity;
    for (const [, v] of vals) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
    const W = 60, H = 18, span = hi - lo || 1;
    return vals.map(([t, v], n) => `${n ? "L" : "M"}${(((t - t0) / (t1 - t0)) * W).toFixed(1)} ${(H - 1 - ((v - lo) / span) * (H - 2)).toFixed(1)}`).join("");
  }, [f, i, k]);
  return <svg className="spark" width={60} height={18} aria-hidden="true">{d && <path d={d} />}</svg>;
}

function PartDetail({ id, view, letter }: { id: PartId; view: PartView | undefined; letter: string }) {
  const part = PART[id];
  const inFrames = (k: string) => !!player.frames?.cols[k];
  return (
    <article className="detail-part" aria-label={`Detail ${letter}: ${part.name}`}>
      <header><span className="detail-letter">{letter}</span><h3>{part.name}</h3></header>
      <p className="detail-role">{part.role}</p>
      {!view ? <p className="field-note">Reading the twin…</p> : <>
        {view.quantities.length > 0 && (
          <table className="detail-q">
            <tbody>
              {view.quantities.map((q) => (
                <tr key={q.key + q.label} className={`k-${q.kind}`}>
                  <th scope="row">{q.label}{q.kind === "twin" && <span className="who"> twin</span>}</th>
                  <td className="num">{q.value === null ? "—" : q.value.toFixed(q.digits)}</td>
                  <td className="unit">{q.unit}{q.estimated && <span className="est"> est.</span>}</td>
                  <td className="hist">{inFrames(q.key) && <Spark k={q.key} />}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {view.equations.map((e) => (
          <section key={e.name} className="eqn">
            <h4>{e.name}{e.estimated && <span className="est"> est.</span>}</h4>
            <p className="eq-sym">{e.symbolic}</p>
            <p className="eq-live">{e.substituted ?? "—"}</p>
            <table className="eq-terms">
              <tbody>
                {e.terms.map((t) => (
                  <tr key={t.symbol}>
                    <th scope="row">{t.symbol}</th>
                    <td className="num">{t.value === null ? "—" : t.value.toFixed(t.digits)}</td>
                    <td className="unit">{t.unit}{t.estimated && <span className="est"> est.</span>}</td>
                    <td className="meaning">{t.meaning}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {e.note && <p className="eq-note">{e.note}</p>}
          </section>
        ))}
        {view.alerts.length > 0 && (
          <section className="findings">
            <h4>Findings, last 24 h</h4>
            <ul>
              {view.alerts.map((a) => (
                <li key={a.id} className={`sev-${a.severity} org-${a.origin}`}>
                  <span className="sev">{a.origin === "sensor" ? "sensor" : a.severity}</span> {a.explanation}
                </li>
              ))}
            </ul>
          </section>
        )}
        {view.tests.length > 0 && (
          <section className="tests"><h4>Recommended test</h4><ul>{view.tests.map((t) => <li key={t}>{t}</li>)}</ul></section>
        )}
      </>}
    </article>
  );
}

export function Detail({ dataset, pinned, onClose }: { dataset: string; pinned: PartId[]; onClose: () => void }) {
  const i = usePlayerIndex();
  const t = player.frames && i >= 0 ? player.frames.iso[i] : null;
  const q = useComponents(dataset, t, pinned.length > 0);
  if (!pinned.length) return null;
  return (
    <aside className="detail" aria-label="Detail views of pinned parts">
      <div className="detail-head">
        <h2>Detail views</h2>
        <button className="unpin" onClick={onClose} aria-label="Unpin all parts">×</button>
      </div>
      {q.error && <p className="field-error">{(q.error as Error).message}</p>}
      <div className="detail-scroll">
        {[...pinned].reverse().map((id) => (
          <PartDetail key={id} id={id} view={q.data?.parts[id]} letter={detailLetter(pinned, id)} />
        ))}
      </div>
    </aside>
  );
}
