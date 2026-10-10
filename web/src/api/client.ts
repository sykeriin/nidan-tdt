import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { API_BASE } from '../config'
import type { components } from './schema'

type S = components['schemas']
export type Run = S['RunModel']
export type DatasetInfo = S['DatasetInfoModel']
export type Alert = S['AlertModel']
export type Recommendation = S['RecommendationModel']
export type Health = S['HealthModel']
export type Table = S['TableModel']
export type Series = S['SeriesModel']
export type InspectResult = S['InspectResultModel']
export type LoadedDataset = S['DatasetModel']
export type Preset = S['PresetModel']
export type ResolvedProfile = S['ProfileModel']
export type Chain = S['ChainModel']
export type StepResponse = S['StepResponseModel']
export type WhatIf = S['WhatIfModel']

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

/** Every failure becomes an ApiError whose message is the backend's readable `detail`. */
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, init)
  } catch {
    throw new ApiError(0, 'Backend offline: start the server (uvicorn server.app:app --port 8000).')
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (typeof body?.detail === 'string') detail = body.detail
    } catch {
      /* not JSON: keep the status line */
    }
    throw new ApiError(res.status, detail)
  }
  return res.json() as Promise<T>
}

export const useBackend = () =>
  useQuery({
    queryKey: ['health'],
    queryFn: () => request<{ status: string; web_build: boolean }>('/health'),
    refetchInterval: 15000,
    retry: false,
  })

export const useDatasets = () =>
  useQuery({ queryKey: ['datasets'], queryFn: () => request<DatasetInfo[]>('/datasets') })

export const useRun = (id: string | null) =>
  useQuery({
    queryKey: ['run', id],
    queryFn: () => request<Run>(`/datasets/${encodeURIComponent(id!)}/run?max_points=2000`),
    enabled: !!id,
    staleTime: Infinity,
  })

export const useSelfTest = () =>
  useQuery({ queryKey: ['self-test'], queryFn: () => request<Table>('/self-test') })

export const reportHref = (id: string, fmt: 'html' | 'csv' | 'json', download = false) =>
  `${API_BASE}/datasets/${encodeURIComponent(id)}/report?fmt=${fmt}${download ? '&download=true' : ''}`

export async function inspectFiles(files: File[]): Promise<InspectResult> {
  const form = new FormData()
  files.forEach((f) => form.append('files', f))
  return request<InspectResult>('/inspect', { method: 'POST', body: form })
}

export interface LoadArgs {
  files: File[]
  name?: string
  mapping?: Record<string, { to: string; unit?: string }>
  asset?: 'estimate' | Record<string, number>
  interval?: string
}

export function useLoadDataset() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (a: LoadArgs) => {
      const form = new FormData()
      a.files.forEach((f) => form.append('files', f))
      if (a.name) form.append('name', a.name)
      if (a.mapping) form.append('mapping', JSON.stringify(a.mapping))
      if (a.asset) form.append('asset', a.asset === 'estimate' ? 'estimate' : JSON.stringify(a.asset))
      if (a.interval) form.append('interval', a.interval)
      return request<LoadedDataset>('/datasets', { method: 'POST', body: form })
    },
    onSuccess: () => Promise.all([qc.invalidateQueries({ queryKey: ['datasets'] }), qc.invalidateQueries({ queryKey: ['run'] })]),
  })
}

// ---------------------------------------------------------------- generic transformer profile and physics
export interface ProfileBody {
  values: Record<string, unknown>
  tags?: Record<string, string>
}

const post = <T,>(path: string, body: unknown) =>
  request<T>(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

export const usePresets = () =>
  useQuery({ queryKey: ['presets'], queryFn: () => request<Preset[]>('/presets'), staleTime: Infinity })

/** The complete, tagged profile the twin will use for what was typed (rated current, loss split, IEC defaults). */
export const useResolvedProfile = (body: ProfileBody | null) =>
  useQuery({
    queryKey: ['profile', body],
    queryFn: () => post<ResolvedProfile>('/profile', body),
    enabled: !!body,
    retry: false,
    placeholderData: keepPreviousData,
  })

export const useChain = (profile: ProfileBody | null, loadPu: number, ambientC: number) =>
  useQuery({
    queryKey: ['chain', profile, loadPu, ambientC],
    queryFn: () => post<Chain>('/physics/chain', { ...profile, load_pu: loadPu, ambient_C: ambientC }),
    enabled: !!profile,
    retry: false,
    placeholderData: keepPreviousData,
  })

export const useStepResponse = (profile: ProfileBody | null, fromPu: number, toPu: number, ambientC: number, minutes: number) =>
  useQuery({
    queryKey: ['step', profile, fromPu, toPu, ambientC, minutes],
    queryFn: () => post<StepResponse>('/physics/step', { ...profile, from_pu: fromPu, to_pu: toPu, ambient_C: ambientC, minutes }),
    enabled: !!profile,
    retry: false,
    placeholderData: keepPreviousData,
  })

export const useWhatIf = (datasetId: string | null, loadMult: number, ambientOffsetC: number, riseMult: number, enabled: boolean, model: 'iec' | 'detailed' = 'iec', kFactor = 1) =>
  useQuery({
    queryKey: ['whatif', datasetId, loadMult, ambientOffsetC, riseMult, model, kFactor],
    queryFn: () =>
      post<WhatIf>(`/datasets/${encodeURIComponent(datasetId!)}/whatif`, { load_mult: loadMult, ambient_offset_C: ambientOffsetC, rise_mult: riseMult, model, k_factor: kFactor }),
    enabled: !!datasetId && enabled,
    retry: false,
    placeholderData: keepPreviousData,
  })

export interface IngestResult { dataset_id: string; session: string; rows_total: number; mode: string; last_timestamp: string | null }

/** Send readings the way a device or gateway would; the session appears as the dataset u-live-<session>. */
export const ingestReadings = (session: string, rows: Record<string, unknown>[], asset?: Record<string, unknown>) =>
  post<IngestResult>('/ingest', { session, rows, asset })

export const fetchReplayRows = async (datasetId: string, start: string, limit: number): Promise<Record<string, unknown>[]> => {
  const res = await fetch(`${API_BASE}/datasets/${encodeURIComponent(datasetId)}/replay?start=${encodeURIComponent(start)}&limit=${limit}`)
  if (!res.ok) throw new ApiError(res.status, 'Could not read the sample feed.')
  const lines = (await res.text()).split('\n').filter(Boolean)
  return lines.map((l) => JSON.parse(l).row as Record<string, unknown>)
}

export function useSimulate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (a: ProfileBody & { scenario: string; name?: string; plant?: 'iec' | 'detailed' }) => post<LoadedDataset>('/simulate', a),
    onSuccess: () => Promise.all([qc.invalidateQueries({ queryKey: ['datasets'] }), qc.invalidateQueries({ queryKey: ['run'] })]),
  })
}

// ---------------------------------------------------------------- the moment, and the outlook
import type { AgeingModels, Brief, DetailedCompare, Outlook } from './types'

const BUCKET_15_MIN = 15 * 60_000
const BUCKET_HOUR = 60 * 60_000

/** Status sentence, ranked diagnosis, work order and headroom at replay time `ms` (cached per 15-minute bucket). */
export const useBrief = (datasetId: string | null, ms: number | null, enabled = true) => {
  const bucket = ms == null ? null : Math.floor(ms / BUCKET_15_MIN) * BUCKET_15_MIN
  return useQuery({
    queryKey: ['brief', datasetId, bucket],
    queryFn: () => request<Brief>(`/datasets/${encodeURIComponent(datasetId!)}/brief?t=${encodeURIComponent(new Date(bucket!).toISOString())}`),
    enabled: !!datasetId && bucket != null && enabled,
    placeholderData: keepPreviousData,
    staleTime: Infinity,
    retry: false,
  })
}

/** Monte Carlo remaining life, 30-day risk and 24 h forecast from time `ms` (cached per hour). */
export const useOutlook = (datasetId: string | null, ms: number | null, enabled = true) => {
  const bucket = ms == null ? null : Math.floor(ms / BUCKET_HOUR) * BUCKET_HOUR
  return useQuery({
    queryKey: ['outlook', datasetId, bucket],
    queryFn: () => request<Outlook>(`/datasets/${encodeURIComponent(datasetId!)}/outlook?t=${encodeURIComponent(new Date(bucket!).toISOString())}`),
    enabled: !!datasetId && bucket != null && enabled,
    placeholderData: keepPreviousData,
    staleTime: Infinity,
    retry: false,
  })
}

export const useDetailed = (
  profile: ProfileBody | null,
  p: { fromPu: number; toPu: number; ambientC: number; minutes: number; kFactor: number; useMass: boolean },
) =>
  useQuery({
    queryKey: ['detailed', profile, p],
    queryFn: () =>
      post<DetailedCompare>('/physics/detailed', {
        ...profile, from_pu: p.fromPu, to_pu: p.toPu, ambient_C: p.ambientC, minutes: p.minutes, k_factor: p.kFactor, use_mass_capacity: p.useMass,
      }),
    enabled: !!profile,
    retry: false,
    placeholderData: keepPreviousData,
  })

export const useAgeingModels = () =>
  useQuery({ queryKey: ['ageing-models'], queryFn: () => request<AgeingModels>('/physics/ageing-models'), staleTime: Infinity })
