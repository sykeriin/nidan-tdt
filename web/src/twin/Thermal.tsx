// Mirror-mode thermal layer. Everything reads the replay clock in useFrame (refs, no React state per frame):
//   heat colour of oil (top-oil) and windings (hot-spot), twin ghost (blueprint ink) around the windings,
//   hot-spot marker, and the dimensioned "measured vs physics" tag at the oil surface.
// Values come from /frames; the only logic here is choosing which backend value drives which visual.
import { useFrame } from "@react-three/fiber";
import { Html } from "@react-three/drei";
import { useMemo, useRef } from "react";
import * as THREE from "three";
import { player } from "../player/player";
import { heatColor } from "../data/heat";
import { HEAT_MATS, LIMBS, Y0, H, W, D, tube } from "./Transformer";
import { TWIN } from "../theme";
import { trustOf } from "../data/fields";

const num = (v: unknown) => (typeof v === "number" ? v : null);

/** Which backend value drives each colour (see BINDINGS.md). A measured reading is used only when the backend's
 * flags call it trustworthy; otherwise the twin's value is shown and labelled as such. */
export function thermalValues(i = player.index, otiSuspect = false) {
  const otiRaw = num(player.value("OTI_C", i));
  const dq = (player.value("dq_flags", i) as string | null) ?? "";
  const sensorSuspect = otiRaw !== null && trustOf("OTI_C", otiRaw, dq, otiSuspect) === "suspect";
  const oti = sensorSuspect ? null : otiRaw;
  const twinOil = num(player.value("twin_oil_C", i));
  const hsActual = num(player.value("hs_ageing_C", i));
  const twinHs = num(player.value("twin_hs_C", i));
  return {
    oil: oti ?? twinOil, oilSource: oti !== null ? "measured" : "twin",
    hotSpot: hsActual ?? twinHs, hsSource: player.value("ageing_source", i) === "measured" ? "measured" : "twin",
    twinOil, twinHs, residual: num(player.value("residual_oil_C", i)),
    alert: player.value("fidelity_alert", i) === true,
    sensorSuspect, otiRaw,
  };
}

export function ThermalDriver({ otiSuspect }: { otiSuspect: boolean }) {
  const c = useMemo(() => new THREE.Color(), []);
  useFrame(() => {
    const v = thermalValues(player.index, otiSuspect);
    heatColor(v.oil, HEAT_MATS.oil.color);
    for (const ph of ["R", "Y", "B"] as const) HEAT_MATS.winding[ph].color.copy(heatColor(v.hotSpot, c));
  });
  return null;
}

/** The twin's prediction drawn over the measured model: blueprint-ink outlines of the windings, dashed when
 * the backend says measured and twin disagree (fidelity_alert / implausible_rise). */
export function TwinGhost({ otiSuspect }: { otiSuspect: boolean }) {
  const mats = useMemo(() => ({
    solid: new THREE.LineBasicMaterial({ color: TWIN, transparent: true, opacity: 0.85 }),
    dashed: new THREE.LineDashedMaterial({ color: TWIN, dashSize: 0.035, gapSize: 0.025, transparent: true, opacity: 0.95 }),
  }), []);
  const lines = useMemo(() => {
    const geo = new THREE.EdgesGeometry(tube(0.165, 0.245, 0.8), 30);
    return Object.values(LIMBS).map((x) => {
      const l = new THREE.LineSegments(geo, mats.solid);
      l.position.set(x, 0.85, 0);
      l.computeLineDistances();
      return l;
    });
  }, [mats]);
  useFrame(() => {
    const m = thermalValues(player.index, otiSuspect).alert ? mats.dashed : mats.solid;
    for (const l of lines) l.material = m;
  });
  return <group>{lines.map((l, i) => <primitive key={i} object={l} />)}</group>;
}

function fmt(v: number | null, d = 1) { return v === null ? "—" : v.toFixed(d); }

/** Hot-spot marker on the most loaded phase's winding top, and the residual tag at the oil surface. Their text is
 * written straight into the DOM from useFrame, so a playing replay never re-renders React. */
export function ThermalMarkers({ meterOnly, otiSuspect }: { meterOnly: boolean; otiSuspect: boolean }) {
  const hs = useRef<HTMLDivElement>(null);
  const tag = useRef<HTMLDivElement>(null);
  const marker = useRef<THREE.Group>(null);
  const last = useRef("");
  useFrame(() => {
    const v = thermalValues(player.index, otiSuspect);
    const i = player.index;
    const amps = (["R", "Y", "B"] as const).map((p) => num(player.value(`I${p}`, i)) ?? -1);
    const ph = (["R", "Y", "B"] as const)[amps.indexOf(Math.max(...amps))];
    if (marker.current) marker.current.position.set(LIMBS[ph], 1.25, 0.2);
    const key = `${i}|${ph}`;
    if (key === last.current || !hs.current || !tag.current) return; // Html children mount after the first frames
    last.current = key;
    if (hs.current) {
      hs.current.innerHTML =
        `<span class="mk-label">hot-spot, phase ${ph}</span>` +
        `<span class="mk-row"><b class="${v.hsSource === "measured" ? "m" : "t"}">${fmt(v.hotSpot)}</b> °C ` +
        `<i>${v.hsSource === "measured" ? "measured oil + gradient" : "estimated by twin"}</i></span>` +
        (v.hsSource === "measured" ? `<span class="mk-row"><b class="t">${fmt(v.twinHs)}</b> °C <i>twin</i></span>` : "");
    }
    if (tag.current) {
      const r = v.residual;
      tag.current.className = `residual-tag${v.sensorSuspect ? " suspect" : v.alert ? " alert" : ""}`;
      tag.current.innerHTML = v.sensorSuspect
        ? `<span class="mk-label">top-oil sensor (OTI): suspect</span>` +
          `<span class="mk-row"><b class="m">${fmt(v.otiRaw)}</b> °C measured <i>outside what physics allows</i></span>` +
          `<span class="mk-row"><b class="t">${fmt(v.twinOil)}</b> °C <i>twin, shown instead</i></span>` +
          `<span class="mk-dim">check the device, not the transformer</span>`
        : meterOnly || r === null
        ? `<span class="mk-label">top-oil</span><span class="mk-row"><b class="t">${fmt(v.twinOil)}</b> °C <i>estimated by twin</i></span>`
        : `<span class="mk-label">top-oil, measured vs physics</span>` +
          `<span class="mk-row"><b class="m">${fmt(v.oil)}</b> vs <b class="t">${fmt(v.twinOil)}</b> °C</span>` +
          `<span class="mk-dim">${r >= 0 ? "+" : "−"}${fmt(Math.abs(r))} K vs physics</span>` +
          `<span class="mk-drift">model drift: check cooling / recalibrate</span>`;
    }
  });
  return (
    <>
      <group ref={marker}>
        <mesh>
          <sphereGeometry args={[0.03, 16, 12]} />
          <meshBasicMaterial color="#1B1B18" />
        </mesh>
        <Html position={[0, 0, 0]} style={{ pointerEvents: "none" }} zIndexRange={[5, 0]}>
          <div className="hs-marker" ref={hs} />
        </Html>
      </group>
      <Html position={[W / 2 - 0.05, Y0 + H - 0.1, D / 2 - 0.05]} style={{ pointerEvents: "none" }} zIndexRange={[5, 0]}>
        <div className="residual-tag" ref={tag} />
      </Html>
    </>
  );
}
