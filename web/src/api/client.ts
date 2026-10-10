// Typed access to the FastAPI backend (types generated from docs/openapi.json: `npm run gen:api`).
// The frontend never computes engineering values: every number shown comes from these responses.
import { useQuery } from "@tanstack/react-query";
import type { components } from "./schema";

export type StateAt = components["schemas"]["StateAtModel"];
export type Run = components["schemas"]["RunModel"];
export type DatasetInfo = components["schemas"]["DatasetInfoModel"];
export type Alert = components["schemas"]["AlertModel"];

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function get<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
  const qs = params
    ? "?" + new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined) as [string, string][])
    : "";
  let res: Response;
  try {
    res = await fetch(`/api${path}${qs}`);
  } catch {
    throw new ApiError(0, "The twin server isn't reachable. Start it with: uvicorn server.app:app --port 8000");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, body.detail ?? res.statusText);
  }
  return res.json() as Promise<T>;
}

export const api = {
  datasets: () => get<DatasetInfo[]>("/datasets"),
  // max_points small: here we only need the run's summary, asset and capabilities, not its charts.
  runSummary: (id: string) => get<Run>(`/datasets/${id}/run`, { max_points: 10 }),
  stateAt: (id: string, t: string) => get<StateAt>(`/datasets/${id}/state`, { t }),
};

export const useDatasets = () => useQuery({ queryKey: ["datasets"], queryFn: api.datasets, staleTime: Infinity });
export const useRunSummary = (id: string) =>
  useQuery({ queryKey: ["run-summary", id], queryFn: () => api.runSummary(id), staleTime: Infinity });
export const useStateAt = (id: string, t: string) =>
  useQuery({ queryKey: ["state", id, t], queryFn: () => api.stateAt(id, t), staleTime: Infinity });

export type FramesResponse = components["schemas"]["FramesModel"];
export const getFrames = (id: string) => get<FramesResponse>(`/datasets/${id}/frames`);
export const useFramesQuery = (id: string, enabled = true) =>
  useQuery({ queryKey: ["frames", id], queryFn: () => getFrames(id), staleTime: Infinity, enabled });

export type ThermalProfile = components["schemas"]["ThermalProfileModel"];
export type Components = components["schemas"]["ComponentsModel"];
export type PartView = components["schemas"]["PartModel"];
export type Equation = components["schemas"]["EquationModel"];

// Model constants (P0, Pk, τ, …) do not change within a run: fetched once, at the first sample.
export const useThermalParams = (id: string, t0: string | null) =>
  useQuery({
    queryKey: ["thermal-params", id], enabled: !!t0, staleTime: Infinity,
    queryFn: () => get<ThermalProfile>(`/datasets/${id}/thermal-profile`, { t: t0! }).then((r) => r.params),
  });
// Per-part equations at the replay cursor; only while a part is pinned. Keeps the last answer while the next loads.
export const useComponents = (id: string, t: string | null, enabled: boolean) =>
  useQuery({
    queryKey: ["components", id, t], enabled: enabled && !!t, staleTime: Infinity,
    queryFn: () => get<Components>(`/datasets/${id}/components`, { t: t! }),
    placeholderData: (prev) => prev,
  });

export type DatasetLoaded = components["schemas"]["DatasetModel"];
/** Upload CSV/Excel file(s); the backend maps, runs the twin + analytics and registers the dataset. */
export async function uploadDataset(files: File[], estimateRating: boolean): Promise<DatasetLoaded> {
  const body = new FormData();
  files.forEach((f) => body.append("files", f));
  body.append("name", files.map((f) => f.name).join(", "));
  if (estimateRating) body.append("asset", "estimate");
  let res: Response;
  try {
    res = await fetch("/api/datasets", { method: "POST", body });
  } catch {
    throw new ApiError(0, "The twin server isn't reachable. Start it with: python -m server");
  }
  if (!res.ok) {
    const b = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, typeof b.detail === "string" ? b.detail : JSON.stringify(b.detail));
  }
  return res.json() as Promise<DatasetLoaded>;
}

export type WhatIf = components["schemas"]["WhatIfModel"];
export type Findings = components["schemas"]["FindingsModel"];
export type Finding = components["schemas"]["FindingModel"];
export interface WhatIfInput { load: number; ambient: number; cooling: number }
// Simulate: one steady-state answer per slider position (the approach starts from the twin state at `t`).
export const useWhatIf = (inp: WhatIfInput | null, dataset: string, t: string | null) =>
  useQuery({
    queryKey: ["whatif", dataset, t, inp?.load, inp?.ambient, inp?.cooling], enabled: !!inp, staleTime: Infinity,
    queryFn: () => get<WhatIf>("/whatif", { load_pu: inp!.load, ambient_C: inp!.ambient, cooling: inp!.cooling,
      dataset_id: dataset, t: t ?? undefined }),
    placeholderData: (prev) => prev,
  });
// Diagnose: findings up to the replay cursor.
export const useFindings = (dataset: string, t: string | null, enabled: boolean) =>
  useQuery({
    queryKey: ["findings", dataset, t], enabled, staleTime: Infinity,
    queryFn: () => get<Findings>(`/datasets/${dataset}/findings`, { t: t ?? undefined }),
    placeholderData: (prev) => prev,
  });
