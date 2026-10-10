// EXPLAIN: a 60-second scripted camera walk through the physics chain, one caption per step.
// The tour state lives outside React (like the replay clock); the camera eases toward each pose in useFrame.
import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useRef, useSyncExternalStore } from "react";
import * as THREE from "three";

type V3 = [number, number, number];
export interface Step { title: string; caption: string; target: V3; dir: V3; zoom: number }

const DEFAULT_DIR: V3 = [6.1, 3.3, 7.4];
export const STEPS: Step[] = [
  { title: "Load", caption: "The current the campus draws leaves through the three LV bushings. Load factor K = I / I rated.",
    target: [-0.15, 1.95, 0.3], dir: [3, 2.2, 4], zoom: 2.1 },
  { title: "Losses", caption: "That current heats the copper windings in proportion to I²; the core adds a small constant no-load loss.",
    target: [0, 0.85, 0.2], dir: [4.5, 1.8, 5.5], zoom: 1.8 },
  { title: "Heat", caption: "Windings and core warm the oil around them. The arrows are sized by watts; the box bottom right keeps the balance.",
    target: [0, 1.0, 0.25], dir: [5, 2.5, 6], zoom: 1.45 },
  { title: "Oil", caption: "Hot oil rises through the windings, crosses the top and enters the radiators: natural circulation (ONAN).",
    target: [0.45, 1.0, 0.1], dir: [3, 2, 6], zoom: 1.35 },
  { title: "Radiators", caption: "In the fins the oil gives its heat to the air and sinks back, cooler, to the bottom of the tank.",
    target: [1.15, 0.85, 0], dir: [6, 2, 2.5], zoom: 1.9 },
  { title: "Air", caption: "The hotter the day, the less heat the radiators can shed: ambient sets the floor every temperature stands on.",
    target: [1.55, 1.0, 0.55], dir: [5, 2.5, 3], zoom: 1.7 },
  { title: "Temperature", caption: "Top-oil plus the winding gradient gives the hot-spot, the hottest point in the paper (thermometer, top left).",
    target: [0.1, 1.1, 0], dir: DEFAULT_DIR, zoom: 1 },
  { title: "Ageing", caption: "Every 6 K above 98 °C doubles how fast the paper insulation ages. The life clock (right) counts it.",
    target: [0, 1.0, 0.2], dir: DEFAULT_DIR, zoom: 1.35 },
  { title: "Twin vs reality", caption: "Blue is physics, vermilion is measured. When the oil runs hotter than physics allows, the gap is dimensioned: inspect cooling.",
    target: [0.75, 1.45, 0.35], dir: [6, 4, 7], zoom: 1.55 },
];
export const STEP_MS = 6500;

// ---- store
let step = -1;
const fns = new Set<() => void>();
const emit = () => fns.forEach((f) => f());
export const tour = {
  get step() { return step; },
  start() { step = 0; emit(); },
  stop() { step = -1; emit(); },
  go(n: number) { step = n < 0 || n >= STEPS.length ? -1 : n; emit(); },
};
export const useTourStep = () => useSyncExternalStore((f) => { fns.add(f); return () => fns.delete(f); }, () => step);

/** Inside the Canvas: eases camera, orbit target and zoom toward the current step; restores the view after. */
export function CameraTour() {
  const s = useTourStep();
  const { camera, controls } = useThree() as unknown as { camera: THREE.OrthographicCamera; controls: { target: THREE.Vector3; update: () => void } | null };
  const home = useRef<{ pos: THREE.Vector3; target: THREE.Vector3; zoom: number } | null>(null);
  const goal = useRef<{ pos: THREE.Vector3; target: THREE.Vector3; zoom: number } | null>(null);
  useEffect(() => {
    if (s >= 0 && !home.current && controls)
      home.current = { pos: camera.position.clone(), target: controls.target.clone(), zoom: camera.zoom };
    if (s < 0) { goal.current = home.current; home.current = null; return; }
    const st = STEPS[s], base = home.current!;
    const target = new THREE.Vector3(...st.target);
    goal.current = { target, pos: target.clone().add(new THREE.Vector3(...st.dir)), zoom: base.zoom * st.zoom };
  }, [s, camera, controls]);
  useFrame((_, dt) => {
    const g = goal.current;
    if (!g || !controls) return;
    const a = 1 - Math.exp(-dt * 2.2);
    camera.position.lerp(g.pos, a);
    controls.target.lerp(g.target, a);
    camera.zoom += (g.zoom - camera.zoom) * a;
    camera.updateProjectionMatrix();
    controls.update();
    if (s < 0 && camera.position.distanceTo(g.pos) < 0.01) goal.current = null; // back home: hand control back
  });
  return null;
}

/** Caption strip (field overlay) with step controls; advances every STEP_MS. */
export function TourCaption() {
  const s = useTourStep();
  useEffect(() => {
    if (s < 0) return;
    const id = window.setTimeout(() => tour.go(s + 1), STEP_MS);
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") tour.stop(); };
    window.addEventListener("keydown", key);
    return () => { window.clearTimeout(id); window.removeEventListener("keydown", key); };
  }, [s]);
  if (s < 0) return null;
  const st = STEPS[s];
  return (
    <div className="tour" role="region" aria-live="polite" aria-label="Explain tour">
      <div className="tour-progress">{STEPS.map((x, k) => <span key={x.title} className={k <= s ? "on" : ""} />)}</div>
      <p className="tour-step">{s + 1} / {STEPS.length}: <b>{st.title}</b></p>
      <p className="tour-cap">{st.caption}</p>
      <div className="tour-btns">
        <button onClick={() => tour.go(Math.max(0, s - 1))} disabled={s === 0}>Back</button>
        <button onClick={() => tour.go(s + 1)}>{s === STEPS.length - 1 ? "Finish" : "Next"}</button>
        <button onClick={() => tour.stop()}>Stop</button>
      </div>
    </div>
  );
}
