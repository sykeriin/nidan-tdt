// The active transformer profile: what the user typed (or took from a preset) plus where each value came from.
// The server completes it (rated current, loss split, IEC defaults); this only keeps the typed part.
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { usePresets, type ProfileBody } from '../api/client'
import { fromPreset, toBody, type Typed } from '../lib/profile'

interface State {
  typed: Typed
  tags: Record<string, string>
  presetId: string | null
}

interface Profile extends State {
  setField: (key: string, value: string) => void
  applyPreset: (id: string) => void
  /** Request body for the API, or null while there is nothing usable yet. */
  body: ProfileBody | null
  ready: boolean
}

const Ctx = createContext<Profile | null>(null)
const KEY = 'dt.profile'

function stored(): State | null {
  try {
    const raw = localStorage.getItem(KEY)
    return raw ? (JSON.parse(raw) as State) : null
  } catch {
    return null
  }
}

export function ProfileProvider({ children }: { children: ReactNode }) {
  const presets = usePresets()
  const [state, setState] = useState<State | null>(stored)

  // First visit: start from Transformer-1, the profile the demo scenarios were generated for.
  useEffect(() => {
    if (state || !presets.data) return
    const p = presets.data.find((x) => x.id === 'transformer-1') ?? presets.data[0]
    if (p) setState({ typed: fromPreset(p.values), tags: p.tags, presetId: p.id })
  }, [presets.data, state])

  useEffect(() => {
    if (!state) return
    try {
      localStorage.setItem(KEY, JSON.stringify(state))
    } catch {
      /* private window: the profile is just not remembered */
    }
  }, [state])

  const setField = useCallback((key: string, value: string) => {
    setState((s) => {
      if (!s) return s
      const tags = { ...s.tags }
      delete tags[key]                        // an edited value is user input now, not the preset's tag
      return { typed: { ...s.typed, [key]: value }, tags, presetId: s.presetId }
    })
  }, [])

  const applyPreset = useCallback(
    (id: string) => {
      const p = presets.data?.find((x) => x.id === id)
      if (p) setState({ typed: fromPreset(p.values), tags: p.tags, presetId: p.id })
    },
    [presets.data],
  )

  const body = useMemo(() => (state ? toBody(state.typed, state.tags) : null), [state])
  const ready = !!body && ('rating_kVA' in body.values || 'i_rated_A' in body.values)

  const value: Profile = {
    typed: state?.typed ?? {}, tags: state?.tags ?? {}, presetId: state?.presetId ?? null,
    setField, applyPreset, body: ready ? body : null, ready,
  }
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useProfile(): Profile {
  const p = useContext(Ctx)
  if (!p) throw new Error('useProfile outside ProfileProvider')
  return p
}
