import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
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

export const reportUrl = (id: string) => `${API_BASE}/datasets/${encodeURIComponent(id)}/report.pdf`

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
