// Typed access to the FastAPI backend (types generated from docs/openapi.json: `npm run gen:api`).
// The frontend never computes engineering values: every number shown comes from these responses.
import { keepPreviousData, useQuery } from "@tanstack/react-query";
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
// `rev` changes when the live transformer has new readings, so its summary and frames are fetched again.
export const useRunSummary = (id: string, rev = "", enabled = true) =>
  useQuery({ queryKey: ["run-summary", id, rev], queryFn: () => api.runSummary(id), staleTime: Infinity, enabled, placeholderData: keepPreviousData });
export const useStateAt = (id: string, t: string) =>
  useQuery({ queryKey: ["state", id, t], queryFn: () => api.stateAt(id, t), staleTime: Infinity });

export type FramesResponse = components["schemas"]["FramesModel"];
export const getFrames = (id: string) => get<FramesResponse>(`/datasets/${id}/frames`);
export const useFramesQuery = (id: string, enabled = true, rev = "") =>
  useQuery({ queryKey: ["frames", id, rev], queryFn: () => getFrames(id), staleTime: Infinity, enabled, placeholderData: keepPreviousData });

// The live simulated transformer is a source, not a dataset: the server rebuilds its run from the readings so far each time this is called.
export const LIVE = "live";
export interface LiveSync { dataset_id: string; name: string; rows: number; last_timestamp: string; tick: number; simulated: boolean }
export const useLiveSync = (enabled: boolean) =>
  useQuery({
    queryKey: ["live-sync"], enabled, refetchInterval: 6000, retry: true, retryDelay: 2500, staleTime: 0, placeholderData: keepPreviousData,
    queryFn: async () => {
      const r = await fetch("/api/live/sync", { method: "POST" });
      if (!r.ok) throw new ApiError(r.status, (await r.json().catch(() => ({}))).detail ?? r.statusText);
      return (await r.json()) as LiveSync;
    },
  });

/** PDF report with a snapshot of the 3D twin as it looks now. The snapshot is optional (the report still builds without it). */
export async function downloadReport(dataset: string, snapshot: string | null): Promise<void> {
  const r = await fetch(`/api/datasets/${encodeURIComponent(dataset)}/report.pdf`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ snapshot }),
  });
  if (!r.ok) throw new ApiError(r.status, (await r.json().catch(() => ({}))).detail ?? r.statusText);
  const name = /filename="([^"]+)"/.exec(r.headers.get("content-disposition") ?? "")?.[1] ?? `${dataset}-report.pdf`;
  const url = URL.createObjectURL(await r.blob());
  const a = document.createElement("a");
  a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

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
export type LoadProfile = "steady" | "daily";
export interface WhatIfInput {
  load: number; ambient: number; cooling: number; voltage: number; pf: number; unbalance: number; profile: LoadProfile;
}
// Simulate: one steady-state answer per slider position (the approach starts from the twin state at `t`).
// Thermal only, so voltage, PF and unbalance are not part of its key.
export const useWhatIf = (inp: WhatIfInput | null, dataset: string, t: string | null) =>
  useQuery({
    queryKey: ["whatif", dataset, t, inp?.load, inp?.ambient, inp?.cooling], enabled: !!inp, staleTime: Infinity,
    queryFn: () => get<WhatIf>("/whatif", { load_pu: inp!.load, ambient_C: inp!.ambient, cooling: inp!.cooling,
      dataset_id: dataset, t: t ?? undefined }),
    placeholderData: (prev) => prev,
  });
export type WhatIfDay = components["schemas"]["WhatIfDayModel"];
// Simulate: the what-if through plant, twin, analytics and Health Index (frames for every panel). Slower: debounce the input.
export const useWhatIfDay = (inp: WhatIfInput | null, dataset: string, t: string | null) =>
  useQuery({
    queryKey: ["whatif-day", dataset, t, inp], enabled: !!inp, staleTime: Infinity, retry: false,
    queryFn: () => get<WhatIfDay>(`/datasets/${dataset}/whatif-day`, { load_pu: inp!.load, ambient_C: inp!.ambient,
      cooling: inp!.cooling, voltage_pu: inp!.voltage, pf: inp!.pf, unbalance_pct: inp!.unbalance, load_profile: inp!.profile,
      t: t ?? undefined }),
    placeholderData: (prev) => prev,
  });
// Diagnose: findings up to the replay cursor.
export const useFindings = (dataset: string, t: string | null, enabled: boolean) =>
  useQuery({
    queryKey: ["findings", dataset, t], enabled, staleTime: Infinity,
    queryFn: () => get<Findings>(`/datasets/${dataset}/findings`, { t: t ?? undefined }),
    placeholderData: (prev) => prev,
  });

// ---------------------------------------------------------------- workbench: generic profile, physics, outlook, self-test
import type { Brief, Outlook } from "../workbench/types";

export type Preset = components["schemas"]["PresetModel"];
export type ResolvedProfile = components["schemas"]["ProfileModel"];
export type Chain = components["schemas"]["ChainModel"];
export type StepResponse = components["schemas"]["StepResponseModel"];
export type Table = components["schemas"]["TableModel"];
export interface ProfileBody { values: Record<string, unknown>; tags?: Record<string, string> }

async function post<T>(path: string, body: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  } catch {
    throw new ApiError(0, "The twin server isn't reachable. Start it with: python -m server");
  }
  if (!res.ok) {
    const b = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, typeof b.detail === "string" ? b.detail : JSON.stringify(b.detail));
  }
  return res.json() as Promise<T>;
}

export const usePresets = () => useQuery({ queryKey: ["presets"], queryFn: () => get<Preset[]>("/presets"), staleTime: Infinity });
export const useResolvedProfile = (body: ProfileBody | null) =>
  useQuery({ queryKey: ["profile", body], queryFn: () => post<ResolvedProfile>("/profile", body), enabled: !!body, retry: false, placeholderData: keepPreviousData });
export const useChain = (p: ProfileBody | null, loadPu: number, ambientC: number) =>
  useQuery({ queryKey: ["chain", p, loadPu, ambientC], enabled: !!p, retry: false, placeholderData: keepPreviousData,
    queryFn: () => post<Chain>("/physics/chain", { ...p, load_pu: loadPu, ambient_C: ambientC }) });
export const useStepResponse = (p: ProfileBody | null, fromPu: number, toPu: number, ambientC: number, minutes: number) =>
  useQuery({ queryKey: ["step", p, fromPu, toPu, ambientC, minutes], enabled: !!p, retry: false, placeholderData: keepPreviousData,
    queryFn: () => post<StepResponse>("/physics/step", { ...p, from_pu: fromPu, to_pu: toPu, ambient_C: ambientC, minutes }) });
export const simulateScenario = (a: ProfileBody & { scenario: string; plant: "iec" | "detailed" }) => post<DatasetLoaded>("/simulate", a);

const HOUR = 3600_000;
const hourOf = (t: string) => { const ms = Date.parse(t); return Number.isNaN(ms) ? t : new Date(Math.floor(ms / HOUR) * HOUR).toISOString().slice(0, 19); };
/** Status sentence, ranked diagnosis, work order and headroom at time t (a replay timestamp as the frames carry it). */
export const useBrief = (id: string, t: string | null, enabled: boolean) =>
  useQuery({ queryKey: ["brief", id, t && hourOf(t)], enabled: enabled && !!t, staleTime: Infinity, retry: false, placeholderData: keepPreviousData,
    queryFn: () => get<Brief>(`/datasets/${id}/brief`, { t: t! }) });
/** Monte Carlo remaining life, 30-day risk and 24 h forecast from time t. */
export const useOutlook = (id: string, t: string | null, enabled: boolean) =>
  useQuery({ queryKey: ["outlook", id, t && hourOf(t)], enabled: enabled && !!t, staleTime: Infinity, retry: false, placeholderData: keepPreviousData,
    queryFn: () => get<Outlook>(`/datasets/${id}/outlook`, { t: t! }) });
export const useSelfTest = (enabled: boolean) => useQuery({ queryKey: ["self-test"], queryFn: () => get<Table>("/self-test"), enabled, staleTime: Infinity });
export const reportHref = (id: string, fmt: "html" | "csv" | "json", download = false) =>
  `/api/datasets/${encodeURIComponent(id)}/report?fmt=${fmt}${download ? "&download=true" : ""}`;
