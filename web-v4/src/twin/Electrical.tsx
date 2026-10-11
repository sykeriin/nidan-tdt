// Electrical layer: current leaving through the LV bushings as dots running up each lead, speed ∝ the phase's
// load factor (I / I_rated; the division only scales an animation), one label per phase with its current, and
// the neutral current on the neutral bushing. Values from frames: IR, IY, IB, IN; I_rated from params.
// Through-fault layer: when the replay passes an event (run.events), the windings flash and a stamp gives
// its peak (pu) and duration (ms).
import { useFrame } from "@react-three/fiber";
import { Html } from "@react-three/drei";
import { useMemo, useRef } from "react";
import * as THREE from "three";
import { player } from "../player/player";
import { HEAT_MATS } from "./Transformer";

const num = (v: unknown) => (typeof v === "number" ? v : null);
const PH = [["R", -0.45], ["Y", -0.15], ["B", 0.15]] as const;
const N_X = 0.45, Z = 0.3, BASE = 1.95, LEN = 0.42, DOTS = 6;

export function Electrical({ iRated }: { iRated: number | null }) {
  const mesh = useRef<THREE.InstancedMesh>(null);
  const labels = useRef<(HTMLDivElement | null)[]>([]);
  const phase = useRef([0, 0, 0]);
  const o = useMemo(() => new THREE.Object3D(), []);
  useFrame((_, dt) => {
    const i = player.index;
    PH.forEach(([p, x], k) => {
      const amps = num(player.value(`I${p}`, i));
      const K = amps !== null && iRated ? amps / iRated : 0;
      phase.current[k] = (phase.current[k] + Math.min(dt, 0.05) * (0.15 + 1.2 * K)) % 1;
      for (let d = 0; d < DOTS; d++) {
        o.position.set(x, BASE + ((phase.current[k] + d / DOTS) % 1) * LEN, Z);
        o.scale.setScalar(amps === null ? 0 : 1);
        o.updateMatrix();
        mesh.current?.setMatrixAt(k * DOTS + d, o.matrix);
      }
      const el = labels.current[k];
      const txt = `${p} ${amps === null ? "—" : amps.toFixed(0)} A`;
      if (el && el.textContent !== txt) el.textContent = txt;
    });
    if (mesh.current) mesh.current.instanceMatrix.needsUpdate = true;
    const n = num(player.value("IN", i));
    const el = labels.current[3];
    const txt = n === null ? "N: not measured" : `N ${n.toFixed(1)} A`;
    if (el && el.textContent !== txt) el.textContent = txt;
  });
  return (
    <group>
      <instancedMesh ref={mesh} args={[undefined, undefined, PH.length * DOTS]} frustumCulled={false}>
        <boxGeometry args={[0.018, 0.03, 0.018]} />
        <meshBasicMaterial color="#1B1B18" />
      </instancedMesh>
      {PH.map(([p, x], k) => (
        <group key={p}>
          <mesh position={[x, BASE + LEN / 2, Z]}>
            <cylinderGeometry args={[0.004, 0.004, LEN, 6]} />
            <meshBasicMaterial color="#1B1B18" transparent opacity={0.5} />
          </mesh>
          <Html position={[x, BASE + LEN + 0.04, Z]} center style={{ pointerEvents: "none" }} zIndexRange={[4, 0]}>
            <div className="elec-label" ref={(el) => { labels.current[k] = el; }} />
          </Html>
        </group>
      ))}
      <Html position={[N_X, BASE + 0.12, Z]} center style={{ pointerEvents: "none" }} zIndexRange={[4, 0]}>
        <div className="elec-label n" ref={(el) => { labels.current[3] = el; }} />
      </Html>
    </group>
  );
}

type Ev = { timestamp: string; peak_pu?: number; duration_ms?: number; phase?: string };
const WINDOW_MS = 40 * 60_000; // data time around an event during which it is shown

export function ThroughFaults({ events }: { events: Ev[] }) {
  const ts = useMemo(() => events.map((e) => Date.parse(e.timestamp)), [events]);
  const stamp = useRef<HTMLDivElement>(null);
  const flash = useMemo(() => new THREE.Color("#FFF4C2"), []);
  const last = useRef(-1);
  useFrame(() => {
    let hit = -1, best = Infinity;
    ts.forEach((t, k) => { const d = Math.abs(player.t - t); if (d < WINDOW_MS && d < best) { best = d; hit = k; } });
    const strength = hit < 0 ? 0 : 1 - best / WINDOW_MS;
    for (const m of Object.values(HEAT_MATS.winding)) {
      m.emissive.copy(flash);
      m.emissiveIntensity = strength * 0.9;
    }
    if (hit !== last.current && stamp.current) {
      last.current = hit;
      const e = events[hit];
      stamp.current.style.display = hit < 0 ? "none" : "block";
      if (e) stamp.current.textContent =
        `Through-fault ${num(e.peak_pu)?.toFixed(1) ?? "—"} pu, ${num(e.duration_ms)?.toFixed(0) ?? "—"} ms${e.phase ? `, phase ${e.phase}` : ""}`;
    }
  });
  return (
    <Html position={[0, 0.85, 0.35]} center style={{ pointerEvents: "none" }} zIndexRange={[6, 0]}>
      <div className="tf-stamp" ref={stamp} style={{ display: "none" }} />
    </Html>
  );
}
