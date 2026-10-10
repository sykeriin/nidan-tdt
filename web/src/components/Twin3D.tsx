// React host for the vendored three.js scene (src/twin3d). The scene and overlay are imperative and created once;
// every new TwinView only changes looks, labels and detail boxes, never the model.
import { useEffect, useRef } from 'react'
import { createOverlay } from '../twin3d/overlay.js'
import { PART_MAP } from '../twin3d/partMap.js'
import { createScene } from '../twin3d/scene.js'
import type { TwinView } from '../lib/twinView'
import '../styles/twin3d.css'

const SEVERITY_RANK: Record<string, number> = { critical: 0, warning: 1, info: 2 }

interface Handles {
  scene: Awaited<ReturnType<typeof createScene>> | null
  overlay: ReturnType<typeof createOverlay>
  view: TwinView | null
  seen: Set<string>
  source: string | null
  windingsAlerting: boolean
  dead: boolean
}

export function Twin3D({ view, height = 620, onSelect }: { view: TwinView | null; height?: number; onSelect?: (part: string | null) => void }) {
  const stageRef = useRef<HTMLDivElement>(null)
  const h = useRef<Handles | null>(null)
  const onSelectRef = useRef(onSelect)
  onSelectRef.current = onSelect

  // Alert ids already shown for the current dataset: an id opens its box once. Closing the box does not bring it
  // back, only a new alert id does.
  const apply = () => {
    const s = h.current
    if (!s?.scene || !s.view) return
    const view = s.view
    s.scene.setStatuses(view.parts)
    s.overlay.setSensorBadges(view.parts)

    const current = `${view.source_label}|${view.mode}`
    if (current !== s.source) {
      s.source = current
      s.seen.clear()
      s.overlay.closeAllBoxes()
    }
    const fresh = view.alerts
      .filter((a) => !s.seen.has(a.id) && (PART_MAP as Record<string, unknown>)[a.part])
      .sort((a, b) => (SEVERITY_RANK[a.severity] ?? 3) - (SEVERITY_RANK[b.severity] ?? 3))
    for (const a of view.alerts) s.seen.add(a.id)
    s.overlay.updateBoxes(view)
    if (fresh.length) {
      const parts = [...new Set(fresh.map((a) => a.part))].slice(0, 2)
      for (const id of parts.reverse()) s.overlay.openBox(id)   // worst one opened last
      s.scene.focusPart(fresh[0].part)
    }
    // A new windings alert switches X-ray on once, so the coloured coils are visible.
    const alerting = ['yellow', 'red'].includes(view.parts.windings.status)
    if (alerting && !s.windingsAlerting) {
      s.scene.setXray(true)
      s.overlay.setXray(true)
    }
    s.windingsAlerting = alerting
  }

  useEffect(() => {
    const stage = stageRef.current!
    const state: Handles = {
      scene: null, view: null, seen: new Set(), source: null, windingsAlerting: false, dead: false,
      overlay: createOverlay(stage, {
        onXray(on: boolean) {
          state.scene?.setXray(on)
          state.overlay.setXray(on)
        },
        onResetView() {
          state.scene?.resetView()
        },
        onBoxes(open: string[]) {
          onSelectRef.current?.(open.length ? open[open.length - 1] : null)
        },
      }),
    }
    h.current = state

    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && state.overlay.closeAllBoxes()
    document.addEventListener('keydown', onKey)

    createScene(stage, {
      onHover(id: string | null, x: number, y: number) {
        if (id) state.overlay.showTooltip(id, state.view?.parts[id as keyof TwinView['parts']], x, y)
        else state.overlay.hideTooltip()
      },
      onSelect(id: string | null) {
        if (!id) {
          state.overlay.closeAllBoxes()
          return
        }
        state.overlay.openBox(id)
        state.scene?.focusPart(id)
      },
      onFrame() {
        if (!state.scene) return
        state.overlay.positionBadges(state.scene.project)
        state.overlay.positionLeaders(state.scene.project)
      },
    })
      .then((scene: NonNullable<Handles['scene']>) => {
        if (state.dead) {
          scene.dispose()
          return
        }
        state.scene = scene
        state.overlay.setMessage(scene.source === 'fallback' ? 'Simplified model shown: the detailed 3D model could not be loaded.' : '')
        apply()
      })
      .catch((err: unknown) => {
        console.error('[twin3d] could not start the 3D scene', err)
        state.overlay.setMessage('The 3D view could not start in this browser.')
      })

    return () => {
      state.dead = true
      document.removeEventListener('keydown', onKey)
      state.scene?.dispose()
      state.overlay.closeAllBoxes()
      h.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (h.current) {
      h.current.view = view
      apply()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view])

  return (
    <div className="stage" ref={stageRef} style={{ height }}>
      <p className="stage__message" id="message" role="status">Loading 3D model…</p>
      <div className="toolbar">
        <button className="toggle" id="reset-view" type="button">Reset view</button>
        <button className="toggle" id="xray" type="button" aria-pressed="false">X-ray</button>
      </div>
      <svg className="leaders" id="leaders" aria-hidden="true" />
      <div className="badges" id="badges" />
      <div className="boxes" id="boxes" />
      <div className="tooltip glass status" id="tooltip" data-status="grey" hidden>
        <strong className="tooltip__label" />
        <span className="tooltip__status">
          <span className="status__icon" aria-hidden="true" />
          <span className="status__word" />
        </span>
        <span className="tooltip__reading num" />
        <span className="tooltip__note" />
      </div>
    </div>
  )
}
