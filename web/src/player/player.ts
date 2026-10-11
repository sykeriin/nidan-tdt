// Replay clock. Lives outside React: 3D reads it every frame through refs; React components subscribe to
// "the sample changed" only (a few times a second), never to every animation frame.
import { useSyncExternalStore } from "react";

export type Cell = number | string | boolean | null;
export interface Frames {
  dataset: string;
  t: number[]; // epoch ms, ascending
  iso: string[]; // backend timestamps, ISO with offset (shown as-is)
  cols: Record<string, Cell[]>;
}

type Fn = () => void;

class Player {
  frames: Frames | null = null;
  t = 0;
  playing = false;
  rev = 0; // bumps whenever new frames are loaded (replay data, or a Simulate result): views re-read values
  speed = 1440; // data-seconds per wall-second
  private idx = 0;
  private indexFns = new Set<Fn>();
  private tickFns = new Set<Fn>();
  private last = 0;
  private raf = 0;

  load(f: Frames, t0?: number) {
    this.pause();
    this.frames = f;
    this.rev++;
    this.t = t0 ?? f.t[0];
    this.idx = -1;
    this.sync(true);
  }
  /** Live feed (Tablet view): add one sample and move the clock to it. Keeps the last `max` samples. */
  append(iso: string, row: Record<string, Cell>, dataset = "LIVE", max = 1500) {
    let f = this.frames;
    if (!f || f.dataset !== dataset) { f = { dataset, t: [], iso: [], cols: {} }; this.frames = f; }
    const n = f.t.length;
    for (const k of Object.keys(row)) if (!(k in f.cols)) f.cols[k] = new Array(n).fill(null);
    f.t.push(Date.parse(iso));
    f.iso.push(iso);
    for (const k of Object.keys(f.cols)) f.cols[k].push(k in row ? row[k] : null);
    if (f.t.length > max) {
      const cut = f.t.length - max;
      f.t.splice(0, cut);
      f.iso.splice(0, cut);
      for (const k in f.cols) f.cols[k].splice(0, cut);
    }
    this.playing = false;
    this.rev++;
    this.t = f.t[f.t.length - 1];
    this.idx = f.t.length - 1;
    this.notify(this.indexFns);
    this.notify(this.tickFns);
  }
  /** Drop all samples (a restarted live session). */
  clear() {
    this.pause();
    this.frames = null;
    this.idx = -1;
    this.rev++;
    this.notify(this.indexFns);
  }
  get index() { return this.idx; }
  get start() { return this.frames?.t[0] ?? 0; }
  get end() { return this.frames ? this.frames.t[this.frames.t.length - 1] : 0; }

  value(key: string, i = this.idx): Cell {
    return this.frames?.cols[key]?.[i] ?? null;
  }
  row(i = this.idx): Record<string, Cell> {
    const out: Record<string, Cell> = {};
    if (!this.frames || i < 0) return out;
    for (const k in this.frames.cols) out[k] = this.frames.cols[k][i];
    return out;
  }

  seek(t: number) {
    this.t = Math.min(this.end, Math.max(this.start, t));
    this.sync(true);
  }
  setSpeed(s: number) { this.speed = s; this.notify(this.tickFns); }
  play() {
    if (!this.frames || this.playing) return;
    if (this.t >= this.end) this.t = this.start;
    this.playing = true;
    this.last = performance.now();
    this.raf = requestAnimationFrame(this.loop);
    this.notify(this.tickFns);
  }
  pause() {
    this.playing = false;
    cancelAnimationFrame(this.raf);
    this.notify(this.tickFns);
  }
  private loop = (now: number) => {
    if (!this.playing) return;
    const dt = Math.min(250, now - this.last); // a hidden tab must not jump the clock
    this.last = now;
    this.t += dt * this.speed;
    if (this.t >= this.end) { this.t = this.end; this.playing = false; }
    this.sync(false);
    if (this.playing) this.raf = requestAnimationFrame(this.loop);
  };

  // index = last sample at or before t (binary search); listeners fire only when it changes
  private sync(force: boolean) {
    const f = this.frames;
    if (f) {
      let lo = 0, hi = f.t.length - 1;
      while (lo < hi) {
        const mid = (lo + hi + 1) >> 1;
        if (f.t[mid] <= this.t) lo = mid; else hi = mid - 1;
      }
      if (lo !== this.idx || force) { this.idx = lo; this.notify(this.indexFns); }
    }
    this.notify(this.tickFns);
  }
  private notify(fns: Set<Fn>) { fns.forEach((fn) => fn()); }
  onIndex(fn: Fn) { this.indexFns.add(fn); return () => { this.indexFns.delete(fn); }; }
  onTick(fn: Fn) { this.tickFns.add(fn); return () => { this.tickFns.delete(fn); }; }
}

export const player = new Player();

/** React: re-render when the current sample changes. */
export function usePlayerIndex(): number {
  useSyncExternalStore((fn) => player.onIndex(fn), () => player.rev); // new data at the same index re-renders too
  return useSyncExternalStore((fn) => player.onIndex(fn), () => player.index);
}
/** React: re-render on play/pause/speed changes (and ticks; use sparingly). */
export function usePlayerTick(): string {
  return useSyncExternalStore((fn) => player.onTick(fn), () => `${player.playing}|${player.speed}`);
}
