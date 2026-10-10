import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useDatasets, useRun, type Alert, type DatasetInfo, type Run } from '../api/client'
import { alertMs, nowAt, sortedAlerts, type Now } from '../lib/derive'

/** Data seconds per wall-clock second. */
export const SPEEDS = [
  { label: 'Slow', hint: '1 day per minute', value: 1440 },
  { label: 'Medium', hint: '1 day per 15 s', value: 5760 },
  { label: 'Fast', hint: '1 day per second', value: 86400 },
] as const

interface Session {
  datasetId: string | null
  setDatasetId: (id: string) => void
  datasets: DatasetInfo[]
  info: DatasetInfo | undefined
  run: Run | undefined
  loading: boolean
  /** The backend answered but has no datasets at all. */
  empty: boolean
  error: Error | null
  alerts: Alert[]
  bounds: { start: number; end: number } | null
  cursor: number | null
  setCursor: (ms: number) => void
  playing: boolean
  togglePlay: () => void
  speed: number
  setSpeed: (v: number) => void
  nextAlert: () => void
  prevAlert: () => void
  stepBy: (deltaMs: number) => void
  now: Now | null
  simulated: boolean
  label: string
}

const Ctx = createContext<Session | null>(null)
const STORE_KEY = 'dt.dataset'
const TICK_MS = 50

function storedId(): string | null {
  try {
    return localStorage.getItem(STORE_KEY)
  } catch {
    return null
  }
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const dsQuery = useDatasets()
  const datasets = useMemo(() => dsQuery.data ?? [], [dsQuery.data])
  const [chosen, setChosen] = useState<string | null>(storedId)
  const datasetId = useMemo(() => {
    if (!datasets.length) return null
    if (chosen && datasets.some((d) => d.dataset_id === chosen)) return chosen
    return datasets.find((d) => d.dataset_id === 'S2')?.dataset_id ?? datasets[0].dataset_id
  }, [datasets, chosen])

  const runQuery = useRun(datasetId)
  const run = runQuery.data
  const info = datasets.find((d) => d.dataset_id === datasetId)
  const alerts = useMemo(() => (run ? sortedAlerts(run) : []), [run])

  const bounds = useMemo(() => {
    if (!run?.start || !run.end) return null
    return { start: Date.parse(run.start), end: Date.parse(run.end) }
  }, [run])

  const [cursor, setCursorState] = useState<number | null>(null)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState<number>(SPEEDS[1].value)

  // A new run starts paused at its end, so every page shows the full picture until Play is pressed.
  useEffect(() => {
    setPlaying(false)
    setCursorState(bounds ? bounds.end : null)
  }, [bounds])

  // The cursor lives in a ref as well, so playback, play/pause and "next alert" read the latest value and the
  // state updaters stay pure (no setState inside an updater).
  const boundsRef = useRef(bounds)
  boundsRef.current = bounds
  const cursorRef = useRef<number | null>(null)
  cursorRef.current = cursor

  useEffect(() => {
    if (!playing) return
    let last = performance.now()
    const id = window.setInterval(() => {
      const t = performance.now()
      const dt = t - last
      last = t
      const b = boundsRef.current
      if (!b) return
      const next = (cursorRef.current ?? b.start) + dt * speed
      if (next >= b.end) {
        setCursorState(b.end)
        setPlaying(false)
      } else {
        setCursorState(next)
      }
    }, TICK_MS)
    return () => window.clearInterval(id)
  }, [playing, speed])

  const setCursor = useCallback((ms: number) => setCursorState(ms), [])
  const togglePlay = useCallback(() => {
    const b = boundsRef.current
    if (!b) return
    if (!playing) {
      const c = cursorRef.current
      if (c == null || c >= b.end) setCursorState(b.start)   // Play at the end restarts from the beginning
    }
    setPlaying(!playing)
  }, [playing])

  const nextAlert = useCallback(() => {
    const b = boundsRef.current
    if (!b) return
    const from = cursorRef.current ?? b.start
    const next = alerts.find((a) => alertMs(a) > from + 1000)
    if (next) setCursorState(alertMs(next))
  }, [alerts])

  const prevAlert = useCallback(() => {
    const b = boundsRef.current
    if (!b) return
    const from = cursorRef.current ?? b.end
    const earlier = alerts.filter((a) => alertMs(a) < from - 1000)
    if (earlier.length) setCursorState(alertMs(earlier[earlier.length - 1]))
  }, [alerts])

  const stepBy = useCallback((deltaMs: number) => {
    const b = boundsRef.current
    if (!b) return
    setCursorState(Math.min(b.end, Math.max(b.start, (cursorRef.current ?? b.end) + deltaMs)))
  }, [])

  const now = useMemo(() => (run && cursor != null ? nowAt(run, alerts, cursor) : null), [run, alerts, cursor])

  const setDatasetId = useCallback((id: string) => {
    setChosen(id)
    try {
      localStorage.setItem(STORE_KEY, id)
    } catch {
      /* private window: selection just isn't remembered */
    }
  }, [])

  const value: Session = {
    datasetId, setDatasetId, datasets, info, run,
    loading: dsQuery.isLoading || runQuery.isLoading,
    empty: dsQuery.isSuccess && datasets.length === 0,
    error: (dsQuery.error ?? runQuery.error) as Error | null,
    alerts, bounds, cursor, setCursor, playing, togglePlay, speed, setSpeed, nextAlert, prevAlert, stepBy, now,
    simulated: info?.simulated ?? false,
    label: run?.name ?? '',
  }
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useSession(): Session {
  const s = useContext(Ctx)
  if (!s) throw new Error('useSession outside SessionProvider')
  return s
}
