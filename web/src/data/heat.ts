// One perceptual heat scale (inferno-like) for every temperature on screen. Presentation mapping only.
import * as THREE from "three";

export const HEAT_MIN = 20; // °C
export const HEAT_MAX = 140;
const STOPS = ["#000004", "#1b0c41", "#4a0c6b", "#781c6d", "#a52c60", "#cf4446", "#ed6925", "#fb9b06", "#fcffa4"]
  .map((h) => new THREE.Color(h));

export function heatColor(c: number | null | undefined, out = new THREE.Color()): THREE.Color {
  if (c === null || c === undefined || Number.isNaN(c)) return out.set("#9A9C96");
  const u = Math.min(1, Math.max(0, (c - HEAT_MIN) / (HEAT_MAX - HEAT_MIN))) * (STOPS.length - 1);
  const i = Math.min(STOPS.length - 2, Math.floor(u));
  return out.copy(STOPS[i]).lerp(STOPS[i + 1], u - i);
}
export const heatCss = (c: number | null | undefined) => `#${heatColor(c).getHexString()}`;
export const heatGradient = () =>
  `linear-gradient(to top, ${STOPS.map((s, i) => `#${s.getHexString()} ${(i / (STOPS.length - 1)) * 100}%`).join(", ")})`;
export const heatPos = (c: number) => Math.min(1, Math.max(0, (c - HEAT_MIN) / (HEAT_MAX - HEAT_MIN)));
