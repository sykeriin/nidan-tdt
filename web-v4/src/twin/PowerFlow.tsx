// AC power flow layer: the supply comes in through the three HV bushings (arrows running down into the tank) and goes
// out through the three LV bushings (arrows running up and away). Both sides are AC, so each end carries a sine mark.
// Arrow speed follows the load factor (I / I_rated; the division only scales an animation). Labels show the output
// power from the measured V, I and power factor, and the input power as output plus the twin's losses.
import { useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";
import { player, usePlayerIndex } from "../player/player";

const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const HV_X = [-0.5, 0, 0.5], HV_Z = -0.15, HV_TOP = 2.98, HV_BOT = 2.58;
const LV_X = [-0.45, -0.15, 0.15], LV_Z = 0.3, LV_BOT = 2.3, LV_TOP = 2.72;
const N = 5;
const PH = ["R", "Y", "B"];
const LID = 1.585; // top face of the tank cover (TOP in Transformer.tsx plus half its thickness)

/** Stencil lettering painted on the cover next to each bushing, so the terminals read as part of the transformer. */
function Stencil({ text, color, x, z, w = 0.17, y = LID, upright = false }: { text: string; color: string; x: number; z: number; w?: number; y?: number; upright?: boolean }) {
  const tex = useMemo(() => {
    const c = document.createElement("canvas");
    c.width = Math.round(256 * (w / 0.17)); c.height = 256;
    const g = c.getContext("2d")!;
    g.font = `900 ${text.length > 1 ? 120 : 210}px Arial Narrow, Arial, sans-serif`;
    g.textAlign = "center"; g.textBaseline = "middle";
    g.lineJoin = "round"; g.lineWidth = 26; g.strokeStyle = "#1E2024"; g.strokeText(text, c.width / 2, 138);
    g.fillStyle = color; g.fillText(text, c.width / 2, 138);
    const t = new THREE.CanvasTexture(c); t.anisotropy = 8; return t;
  }, [text, color, w]);
  return (
    <mesh position={[x, y, z]} rotation={[upright ? 0 : -Math.PI / 2, 0, 0]} renderOrder={5}>
      <planeGeometry args={[w, 0.17]} />
      <meshBasicMaterial map={tex} transparent depthWrite={false} polygonOffset polygonOffsetFactor={-2} />
    </mesh>
  );
}

export function PowerFlow({ iRated }: { iRated: number | null }) {
  const down = useRef<THREE.InstancedMesh>(null);
  const up = useRef<THREE.InstancedMesh>(null);
  const t = useRef(0);
  const o = useMemo(() => new THREE.Object3D(), []);
  useFrame((_, dt) => {
    const i = player.index;
    const amps = ["IR", "IY", "IB"].map((k) => num(player.value(k, i)));
    const mean = amps.every((a) => a != null) ? (amps as number[]).reduce((a, b) => a + b, 0) / 3 : null;
    const K = mean != null && iRated ? mean / iRated : 0;
    t.current = (t.current + Math.min(dt, 0.05) * (0.12 + 0.9 * K)) % 1;
    const live = mean != null ? 1 : 0;
    for (let s = 0; s < 3; s++) {
      for (let n = 0; n < N; n++) {
        const f = (t.current + n / N) % 1;
        // input arrows run down into the tank, fading in at the top and out at the bottom
        o.position.set(HV_X[s], HV_TOP - f * (HV_TOP - HV_BOT), HV_Z);
        o.rotation.set(Math.PI, 0, 0);
        o.scale.setScalar(live * Math.sin(Math.PI * f) * (0.7 + 0.5 * Math.min(1.4, K)));
        o.updateMatrix();
        down.current?.setMatrixAt(s * N + n, o.matrix);
        // output arrows run up and out of the LV bushings
        o.position.set(LV_X[s], LV_BOT + f * (LV_TOP - LV_BOT), LV_Z);
        o.rotation.set(0, 0, 0);
        o.updateMatrix();
        up.current?.setMatrixAt(s * N + n, o.matrix);
      }
    }
    if (down.current) down.current.instanceMatrix.needsUpdate = true;
    if (up.current) up.current.instanceMatrix.needsUpdate = true;

  });
  return (
    <group>
      {/* HV letters sit on the conservator drum, above each HV bushing: the cover itself is hidden behind the bushings from the front */}
      {PH.map((p, i) => <Stencil key={"h" + p} text={"HV " + p} color="#8FBBFF" x={HV_X[i]} y={2.27} z={-0.29} w={0.34} upright />)}
      {PH.map((p, i) => <Stencil key={"l" + p} text={p} color="#FFA270" x={LV_X[i]} z={0.47} />)}
      <Stencil text="N" color="#F2F0E6" x={0.45} z={0.47} />
      <Stencil text="LV" color="#FFA270" x={-0.82} z={0.47} w={0.25} />
      <instancedMesh ref={down} args={[undefined, undefined, 3 * N]} frustumCulled={false}>
        <coneGeometry args={[0.05, 0.15, 12]} />
        <meshBasicMaterial color="#2457A6" />
      </instancedMesh>
      <instancedMesh ref={up} args={[undefined, undefined, 3 * N]} frustumCulled={false}>
        <coneGeometry args={[0.05, 0.15, 12]} />
        <meshBasicMaterial color="#D9480F" />
      </instancedMesh>
    </group>
  );
}

/** The numbers behind the arrows, as a card for the side column: output power from the measured V, I and power factor,
 *  input power as output plus the twin's losses. Swatches match the arrow colours. */
export function PowerFlowReadout() {
  usePlayerIndex();
  const i = player.index;
  const amps = ["IR", "IY", "IB"].map((k) => num(player.value(k, i)));
  const volts = ["VR", "VY", "VB"].map((k) => num(player.value(k, i)));
  const pf = num(player.value("PF", i));
  const loss = num(player.value("losses_total_W", i));
  const iAvg = amps.every((a) => a != null) ? (amps as number[]).reduce((a, b) => a + b, 0) / 3 : null;
  const vPh = volts.every((x) => x != null) ? (volts as number[]).reduce((a, b) => a + b, 0) / 3 : null;
  const pOut = iAvg != null && vPh != null ? (3 * vPh * iAvg * (pf ?? 1)) / 1000 : null; // kW: 3 phases x V x I x PF
  const pIn = pOut != null ? pOut + (loss ?? 0) / 1000 : null;
  const f = (v: number | null, d = 0) => (v == null ? "—" : v.toFixed(d));
  return (
    <section className="schedule pflow" aria-label="AC power flow">
      <header className="schedule-head"><h2>AC power flow</h2><span className="code">Schedule 4</span></header>
      <table>
        <tbody>
          <tr className="in"><th><i className="sw in" />AC in, HV 11 kV</th><td className="num">{f(pIn)}</td><td className="unit">kW</td></tr>
          <tr className="out"><th><i className="sw out" />AC out, LV 415 V</th><td className="num">{f(pOut)}</td><td className="unit">kW</td></tr>
          <tr><th>Output current</th><td className="num">{f(iAvg)}</td><td className="unit">A per phase</td></tr>
          <tr><th>Output voltage</th><td className="num">{f(vPh)}</td><td className="unit">V per phase</td></tr>
          <tr><th>Power factor</th><td className="num">{f(pf, 2)}</td><td className="unit" /></tr>
          <tr><th>Lost in the transformer</th><td className="num">{loss == null ? "—" : (loss / 1000).toFixed(2)}</td><td className="unit">kW est.</td></tr>
        </tbody>
      </table>
      <p className="pflow-note">Both sides are AC. Arrows run supply in (blue, down into the tank) to load out (orange, up and away); they speed up with load.</p>
    </section>
  );
}
