// The breather silica gel and the oil moisture, written next to the 3D model: colour swatch, saturation and what the colour means.
import { player, usePlayerIndex } from "../player/player";

const SCALE: [number, string, string][] = [[25, "#2F6FD6", "Blue: dry, working"], [50, "#7F5FC4", "Violet: taking up moisture"], [66, "#C45FA8", "Nearly spent"], [101, "#E26BA0", "Pink: saturated, replace"]];
const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);

export function GelBadge() {
  const i = usePlayerIndex();
  if (i < 0) return null;
  const pct = num(player.value("SILICA_pct")), ppm = num(player.value("H2O_ppm"));
  if (pct === null && ppm === null) return null;
  const s = SCALE.find(([top]) => (pct ?? 0) < top) ?? SCALE[SCALE.length - 1];
  return (
    <aside className="gel-badge" aria-label="Breather silica gel and oil moisture">
      <span className="gel-jar" style={{ background: s[1] }} />
      <div>
        <b>Silica gel {pct !== null ? `${pct.toFixed(0)} %` : "n/a"}</b>
        <span>{s[2]}</span>
        {ppm !== null && <span>Moisture in oil {ppm.toFixed(1)} ppm</span>}
      </div>
    </aside>
  );
}
