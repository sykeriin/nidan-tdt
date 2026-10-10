import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import type { Run } from '../api/client'
import { useSession } from '../context/Session'
import type { Now } from '../lib/derive'
import { Note, Skeleton } from './ui'

/** Loading / error / mode guard shared by every data page, so no page can white-screen. */
export function Gate({ children, timeSeries = true }: { children: (run: Run, now: Now | null) => ReactNode; timeSeries?: boolean }) {
  const s = useSession()
  if (s.error) return <Note tone="error">{s.error.message}</Note>
  if (s.empty) {
    return (
      <Note tone="info">
        The backend has no datasets yet. <Link to="/import">Import a file</Link>, or run <code>python -m dt.api rebuild</code> to
        build the generated scenarios.
      </Note>
    )
  }
  if (s.loading || !s.run) {
    return (
      <div className="stack">
        <Skeleton h={60} />
        <Skeleton h={320} />
      </div>
    )
  }
  if (timeSeries && s.run.mode === 'snapshot') {
    return (
      <Note tone="info">
        This dataset has records without timestamps (snapshot mode), so there are no time charts or replay.{' '}
        <Link to="/records">See the ranked records</Link>.
      </Note>
    )
  }
  if (timeSeries && s.run.mode === 'data_only') {
    return (
      <Note tone="warn">
        The twin could not run on this dataset (it needs current and ambient temperature), so only data checks are available.{' '}
        <Link to="/data-health">Open Data Health</Link> to see what is missing.
      </Note>
    )
  }
  return <>{children(s.run, s.now)}</>
}
