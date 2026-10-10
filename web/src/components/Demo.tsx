// Guided demo: a narrated tour that drives the real app (dataset, page, replay position) so the story can be told
// without touching anything. Every number in the captions is read from the data being shown.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { useSession } from '../context/Session'
import { alertMs } from '../lib/derive'
import type { Alert } from '../api/client'

type Pos = { ratio: number } | { alert: string[]; offsetH: number }

interface Step {
  title: string
  route: string
  dataset?: string
  start?: Pos
  play?: { until: Pos; speed: number; maxS: number }
  dwellS: number
  text: (c: Ctx) => string
}

interface Ctx { alerts: Alert[]; fmt: (ms: number) => string }

const day = (ms: number) => new Date(ms + 5.5 * 3600_000).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', timeZone: 'UTC' })
const first = (alerts: Alert[], types: string[]) => alerts.find((a) => types.includes(a.type) && a.origin === 'asset')

const STEPS: Step[] = [
  {
    title: 'A healthy month', route: '/', dataset: 'N', start: { ratio: 0.55 }, dwellS: 8,
    text: () => 'Load follows the working day, the sensors and the twin agree, and the gap between them stays near zero. Health is green and nothing needs doing.',
  },
  {
    title: 'The twin shows its work', route: '/physics', dwellS: 9,
    text: () => 'The twin is physics, not a black box: load sets the losses, the losses set the oil temperature, the oil sets the hot spot, and the hot spot sets how fast the insulation ages. Every step is on screen with this transformer\'s numbers.',
  },
  {
    title: 'Now a cooling fault', route: '/', dataset: 'S2', start: { ratio: 0.58 },
    play: { until: { alert: ['residual_drift'], offsetH: 4 }, speed: 14400, maxS: 32 }, dwellS: 2,
    text: () => 'From April 20 the radiators slowly lose efficiency. Watch the hatched band open between what the physics expects and what the sensor reads.',
  },
  {
    title: 'Caught early', route: '/', dataset: 'S2', start: { alert: ['residual_drift'], offsetH: 4 }, dwellS: 10,
    text: ({ alerts }) => {
      const twin = first(alerts, ['residual_drift'])
      const plain = first(alerts, ['top_oil_high', 'hot_spot_high'])
      if (!twin) return 'The twin raises the alert from the gap alone.'
      if (!plain) return `The twin flagged the problem on ${day(alertMs(twin))}. A plain temperature threshold never fired in this window.`
      const h = (alertMs(plain) - alertMs(twin)) / 3600_000
      return `The twin flagged it on ${day(alertMs(twin))}, ${h >= 48 ? `${(h / 24).toFixed(1)} days` : `${h.toFixed(0)} hours`} before the ordinary temperature alarm (${day(alertMs(plain))}).`
    },
  },
  {
    title: 'What to do about it', route: '/alerts', dataset: 'S2', dwellS: 8,
    text: () => 'Each alert comes with the test to run, how urgent it is, and why. Sensor faults are kept apart: they say "check the device, not the transformer".',
  },
  {
    title: 'An overload costs life', route: '/', dataset: 'S1', start: { alert: ['loading_high'], offsetH: 2 }, dwellS: 8,
    text: () => 'Three days of heavy load push the hot spot past 98 °C, the point where the insulation ages faster than designed. The ageing rate and the headroom move with it.',
  },
  {
    title: 'Oil: leak or theft?', route: '/', dataset: 'S4b', start: { alert: ['oil_theft'], offsetH: 3 }, dwellS: 8,
    text: () => 'A slow slope is a leak. A step in an hour with no thermal cause, at night, is flagged as possible theft or tampering, and gets a different response.',
  },
  {
    title: 'Short-circuit stress', route: '/', dataset: 'S5', start: { alert: ['through_fault_stress'], offsetH: 1 }, dwellS: 8,
    text: () => 'Short circuits cannot be seen in 15-minute averages, so they come from an event log. Stress builds up until the twin recommends measuring short-circuit impedance.',
  },
  {
    title: 'Any distribution transformer', route: '/profile', dwellS: 9,
    text: () => 'Enter a rating, or a whole nameplate, and the same model, scenarios and baseline run for that unit. Whatever the nameplate does not say falls back to a tagged standard value.',
  },
  {
    title: 'Honest about the limits', route: '/about', dwellS: 9,
    text: () => 'The fault scenarios are synthetic and labelled so. Health weights and thresholds are engineering judgement. Remaining life is a model outcome for the insulation, not a failure forecast.',
  },
]

interface Demo { active: boolean; index: number; total: number; auto: boolean; start: () => void; stop: () => void; next: () => void; prev: () => void; toggleAuto: () => void; progress: number }
const Ctx = createContext<Demo | null>(null)

export function DemoProvider({ children }: { children: ReactNode }) {
  const s = useSession()
  const nav = useNavigate()
  const [active, setActive] = useState(false)
  const [index, setIndex] = useState(0)
  const [auto, setAuto] = useState(true)
  const [progress, setProgress] = useState(0)
  const applied = useRef<number>(-1)
  const timer = useRef<number | undefined>(undefined)
  const step = STEPS[index]

  const resolve = useCallback((pos: Pos | undefined): number | null => {
    if (!pos || !s.bounds) return null
    if ('ratio' in pos) return s.bounds.start + pos.ratio * (s.bounds.end - s.bounds.start)
    const a = first(s.alerts, pos.alert)
    return a ? alertMs(a) + pos.offsetH * 3600_000 : null
  }, [s.alerts, s.bounds])

  const stop = useCallback(() => { setActive(false); window.clearTimeout(timer.current); s.playing && s.togglePlay() }, [s])
  const go = useCallback((i: number) => {
    window.clearTimeout(timer.current)
    applied.current = -1
    setProgress(0)
    setIndex(Math.max(0, Math.min(STEPS.length - 1, i)))
  }, [])
  const start = useCallback(() => { setActive(true); go(0) }, [go])
  const next = useCallback(() => (index >= STEPS.length - 1 ? stop() : go(index + 1)), [go, index, stop])
  const prev = useCallback(() => go(index - 1), [go, index])

  // Move the app to the step: page, dataset.
  useEffect(() => {
    if (!active) return
    nav(step.route)
    if (step.dataset && s.datasets.some((d) => d.dataset_id === step.dataset) && s.datasetId !== step.dataset) s.setDatasetId(step.dataset)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, index])

  // Once the right run is loaded: set the replay position, and play if the step asks for it.
  useEffect(() => {
    if (!active || applied.current === index) return
    const wanted = step.dataset && s.datasets.some((d) => d.dataset_id === step.dataset) ? step.dataset : s.datasetId
    if (!s.run || s.run.dataset_id !== wanted || !s.bounds) {
      if (!step.start && !step.play && wanted === s.datasetId) { applied.current = index; scheduleAdvance(step.dwellS * 1000) }
      return
    }
    applied.current = index
    // The session resets the replay position when a new run loads. Wait for that to settle before moving it,
    // otherwise "play" would start from the beginning of the run.
    const begin = () => {
      const at = resolve(step.start)
      if (at != null) s.setCursor(at)
      if (step.play) {
        const until = resolve(step.play.until)
        s.setSpeed(step.play.speed)
        window.setTimeout(() => { if (!playingRef.current) s.togglePlay() }, 120)
        const t0 = performance.now()
        const watch = window.setInterval(() => {
          const elapsed = (performance.now() - t0) / 1000
          setProgress(Math.min(1, elapsed / (step.play!.maxS + step.dwellS)))
          const reached = until != null && cursorRef.current != null && cursorRef.current >= until
          if (reached || elapsed > step.play!.maxS) {
            window.clearInterval(watch)
            if (playingRef.current) s.togglePlay()
            scheduleAdvance(step.dwellS * 1000)
          }
        }, 250)
        timer.current = watch as unknown as number
      } else {
        if (playingRef.current) s.togglePlay()
        scheduleAdvance(step.dwellS * 1000)
      }
    }
    const kickoff = window.setTimeout(begin, 380)
    timer.current = kickoff as unknown as number
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, index, s.run, s.bounds, s.datasets])

  const cursorRef = useRef<number | null>(null)
  cursorRef.current = s.cursor
  const playingRef = useRef(false)
  playingRef.current = s.playing
  const autoRef = useRef(auto)
  autoRef.current = auto

  function scheduleAdvance(ms: number) {
    const t0 = performance.now()
    const tick = window.setInterval(() => {
      const f = (performance.now() - t0) / ms
      setProgress(Math.min(1, f))
      if (f >= 1) {
        window.clearInterval(tick)
        if (autoRef.current) setIndex((i) => { applied.current = -1; return Math.min(STEPS.length - 1, i + 1) })
      }
    }, 200)
    timer.current = tick as unknown as number
  }

  useEffect(() => {
    if (!active) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') stop() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [active, stop])

  const value = useMemo<Demo>(() => ({
    active, index, total: STEPS.length, auto, start, stop, next, prev, toggleAuto: () => setAuto((a) => !a), progress,
  }), [active, index, auto, start, stop, next, prev, progress])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useDemo(): Demo {
  const d = useContext(Ctx)
  if (!d) throw new Error('useDemo outside DemoProvider')
  return d
}

export function DemoButton() {
  const d = useDemo()
  return (
    <button className="btn btn--primary" type="button" onClick={d.active ? d.stop : d.start}>
      {d.active ? 'Stop demo' : 'Guided demo'}
    </button>
  )
}

export function DemoOverlay() {
  const d = useDemo()
  const s = useSession()
  if (!d.active) return null
  const step = STEPS[d.index]
  const text = step.text({ alerts: s.alerts, fmt: (ms) => new Date(ms).toISOString() })
  return (
    <div className="demo" role="dialog" aria-label="Guided demo">
      <div className="demo__card">
        <span className="demo__step">Step {d.index + 1} of {d.total}</span>
        <h2 className="demo__title">{step.title}</h2>
        <p className="demo__text">{text}</p>
        <div className="demo__bar" aria-hidden><span style={{ width: `${((d.index + d.progress) / d.total) * 100}%` }} /></div>
        <div className="demo__actions">
          <button className="btn" type="button" onClick={d.prev} disabled={d.index === 0}>Back</button>
          <button className="btn btn--primary" type="button" onClick={d.next}>{d.index === d.total - 1 ? 'Finish' : 'Next'}</button>
          <button className="btn btn--ghost" type="button" onClick={d.toggleAuto}>{d.auto ? 'Pause auto-advance' : 'Resume auto-advance'}</button>
          <span style={{ flex: 1 }} />
          <button className="btn btn--ghost" type="button" onClick={d.stop}>Exit (Esc)</button>
        </div>
      </div>
    </div>
  )
}
