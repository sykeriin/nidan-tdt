// Labels and units for backend fields (docs/API.md). Presentation only: no values are derived here.
export type Source = "row" | "twin" | "asset";
export type Kind = "measured" | "twin" | "residual" | "info";

export interface FieldRef {
  source: Source;
  key: string;
  label: string;
  unit: string;
  kind: Kind;
  digits?: number;
  estimated?: boolean; // shown with an "est." mark
}

export const f = (source: Source, key: string, label: string, unit: string, kind: Kind, extra: Partial<FieldRef> = {}): FieldRef =>
  ({ source, key, label, unit, kind, ...extra });

// dq_flags codes that make a measured channel untrustworthy (ingest/validate.py, twin/plausibility.py).
export const SUSPECT_CODES: Record<string, string[]> = {
  OTI_C: ["RANGE_OTI_C", "JUMP_OTI", "STUCK_OTI", "IMPLAUSIBLE_RISE"],
  WTI_C: ["RANGE_WTI_C", "JUMP_WTI", "STUCK_WTI"],
  ATI_C: ["RANGE_ATI_C", "ATI_MISMATCH"],
  OLI_pct: ["RANGE_OLI_pct", "STUCK_OLI"],
  IR: ["RANGE_IR", "STUCK_IR", "NEG_IR"],
  IY: ["RANGE_IY", "STUCK_IY", "NEG_IY"],
  IB: ["RANGE_IB", "STUCK_IB", "NEG_IB"],
  VR: ["RANGE_VR", "STUCK_VR"],
  VY: ["RANGE_VY", "STUCK_VY"],
  VB: ["RANGE_VB", "STUCK_VB"],
};
// Provenance codes: the value exists but was derived or imputed, not measured.
export const ESTIMATE_CODES: Record<string, string[]> = {
  amb_C: ["IMPUTED_AMB", "ASSUMED_AMBIENT"],
  RH_pct: ["IMPUTED_RH"],
  IR: ["DERIVED_IR"], IY: ["DERIVED_IY"], IB: ["DERIVED_IB"],
  VR: ["DERIVED_VR"], VY: ["DERIVED_VY"], VB: ["DERIVED_VB"],
};

export type Trust = "trusted" | "suspect" | "missing" | "estimated";

export function trustOf(key: string, value: unknown, dqFlags: string | null | undefined, oti_suspect: boolean): Trust {
  if (value === null || value === undefined) return "missing";
  const codes = (dqFlags ?? "").split(";");
  if ((SUSPECT_CODES[key] ?? []).some((c) => codes.includes(c))) return "suspect";
  if (key === "OTI_C" && oti_suspect) return "suspect";
  if ((ESTIMATE_CODES[key] ?? []).some((c) => codes.includes(c))) return "estimated";
  return "trusted";
}

export function fmt(v: unknown, digits = 1): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return v.toFixed(digits);
  return String(v);
}
