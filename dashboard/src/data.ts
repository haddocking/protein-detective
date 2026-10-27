/** Read-only snapshot API. GETs return arrays except /summary (counts + available_tables + fitting_status).
 * Authentication: POST /api/auth {token}; all subsequent requests use the HttpOnly cookie.
 * Candidate identity is candidate_id/structure, never UniProt. Viewer paths are session-relative.
 */
export type Row = Record<string, unknown>;

export type Dataset = "candidates" | "fitting" | "refinements" | "provenance";

export const fittingColumns = [
  "structure",
  "uniprot_accessions",
  "source",
  "powerfit_run_id",
  "rank",
  "cc",
  "fishz",
  "relative_z",
  "model_available",
];

export const refinementColumns = [
  "structure",
  "uniprot_accessions",
  "refine_run_id",
  "powerfit_run_id",
  "fitted_rank",
  "fitted_cc",
  "cluster_rank",
  "member_rank",
  "refined_score",
  "baseline_score",
  "score_change",
  "before_cc",
  "after_cc",
  "cc_change",
];

export const labels: Record<string, string> = {
  filtering_status: "Filtering status",
  rejection_reason: "Rejection reason",
  cluster_score_std: "CAPRI cluster score standard deviation",
  population: "Cluster population",
  cluster_score: "CAPRI cluster score",
  structure: "Structure",
  uniprot_accessions: "UniProt",
  source: "Source",
  powerfit_run_id: "PowerFit run",
  refine_run_id: "Refinement run",
  rank: "Solution rank",
  cc: "PowerFit CC",
  before_cc: "PowerFit CC before refinement",
  after_cc: "PowerFit CC after refinement",
  cc_change: "PowerFit CC change (after − before)",
  before_fishz: "PowerFit Fisher z before refinement",
  after_fishz: "PowerFit Fisher z after refinement",
  before_relative_z: "PowerFit relative z before refinement",
  after_relative_z: "PowerFit relative z after refinement",
  fishz: "PowerFit Fisher z",
  relative_z: "PowerFit relative z",
  model_available: "Fitted structure saved",
  fitted_rank: "Fitted rank",
  fitted_cc: "PowerFit search CC (fitted solution)",
  cluster_rank: "CAPRI cluster rank",
  member_rank: "CAPRI member rank",
  refined_score: "CAPRI score after refinement",
  baseline_score: "CAPRI score before refinement",
  score_change: "CAPRI score change (after − before)",
};

export function display(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(4);
  if (Array.isArray(v)) return v.join(", ");
  if (typeof v === "object") return JSON.stringify(v);
  return typeof v === "string" ? v : typeof v === "boolean" ? (v ? "true" : "false") : "";
}

export function key(row: Row): string {
  return String(row.id ?? row.candidate_id ?? row.structure);
}

export function filterRows(rows: Row[], p: URLSearchParams): Row[] {
  const q = (p.get("q") || "").toLowerCase();
  return rows.filter(
    (r) =>
      (!q ||
        ["structure", "structure_id", "uniprot_accessions"].some((k) =>
          display(r[k]).toLowerCase().includes(q),
        )) &&
      ["source", "powerfit_run_id", "refine_run_id", "cluster"].every(
        (k) => !p.get(k) || String(k === "cluster" ? clusterKey(r) : r[k]) === p.get(k),
      ),
  );
}

export function clusterKey(r: Row): string {
  return JSON.stringify([
    r.refine_run_id,
    r.refine_run_dir,
    r.fitted_model ??
      r.model_input ??
      r.fitted_model_path ??
      r.fitted_input ??
      r.candidate_id ??
      r.structure,
    r.fitted_rank,
    r.cluster_id,
  ]);
}

export function grouped(rows: Row[], kind: string, n: string): Row[] {
  if (n === "all") return [...rows];
  const limit = Math.max(1, Number(n) || 1);
  const groups = new Map<string, Row[]>();
  for (const r of rows) {
    const k =
      kind === "fitting"
        ? JSON.stringify([r.powerfit_run_id, r.candidate_id ?? r.structure])
        : clusterKey(r);
    const group = groups.get(k) || [];
    group.push(r);
    groups.set(k, group);
  }
  return [...groups.values()].flatMap((group) =>
    group
      .sort(
        (a, b) =>
          Number(kind === "fitting" ? a.rank : a.member_rank) -
          Number(kind === "fitting" ? b.rank : b.member_rank),
      )
      .slice(0, limit),
  );
}

export function sorted(rows: Row[], column: string, desc: boolean): Row[] {
  return [...rows].sort((a, b) => {
    const x = a[column],
      y = b[column];
    if (x == null) return y == null ? 0 : 1;
    if (y == null) return -1;
    return (
      (typeof x === "number" && typeof y === "number"
        ? x - y
        : display(x).localeCompare(display(y), undefined, { numeric: true })) * (desc ? -1 : 1)
    );
  });
}

export function csv(rows: Row[], columns: string[]): string {
  const escape = (v: unknown) => '"' + display(v).replaceAll('"', '""') + '"';
  return [
    columns.map((k) => escape(labels[k] ?? k)).join(","),
    ...rows.map((r) => columns.map((k) => escape(r[k])).join(",")),
  ].join("\r\n");
}

export function fileUrl(path: unknown): string {
  return "/files/" + String(path).split("/").map(encodeURIComponent).join("/");
}

export function histogram(rows: Row[], metric: string) {
  const values = rows
    .map((r) => r[metric])
    .filter((x): x is number => typeof x === "number" && Number.isFinite(x));
  if (!values.length) return [];
  const lo = Math.min(...values),
    hi = Math.max(...values),
    width = (hi - lo || 1) / 20;
  return Array.from({ length: 20 }, (_, i) => ({
    start: lo + i * width,
    end: lo + (i + 1) * width,
    count: values.filter((x) => Math.min(19, Math.floor((x - lo) / width)) === i).length,
  }));
}

/** Stable API fields; further recorded metadata may be returned on any row. */
export interface Candidate extends Row {
  candidate_id: string;
  structure: string;
  structure_id: string;
  uniprot_accessions: string;
  source: "AlphaFold" | "PDB";
  filtering_status: "passed" | "rejected" | "not recorded";
  rejection_reason: string | null;
}

export interface StructureResult extends Row {
  id: string;
  candidate_id: string;
  structure: string;
  powerfit_run_id: string;
  model_path: string | null;
  density_path: string | null;
  model_absolute_path: string | null;
  density_absolute_path: string | null;
  model_available: boolean;
  density_available: boolean;
  viewer_available: boolean;
  viewer_error: string | null;
}

export interface FittingResult extends StructureResult {
  rank: number;
  cc: number;
  fishz: number | null;
  relative_z: number | null;
}

export interface RefinementResult extends StructureResult {
  refined_complex: string | null;
  refined_fitted_structure: string | null;
  refined_known_structure: string | null;
  refined_fitted_structure_absolute_path: string | null;
  refined_known_structure_absolute_path: string | null;
  original_known_structure_absolute_path: string | null;
  refine_run_id: string;
  refine_run_dir: string;
  fitted_model: string;
  fitted_model_absolute_path: string | null;
  fitted_rank: number;
  cluster_id: number;
  cluster_rank: number;
  member_rank: number;
  before_cc: number;
  after_cc: number;
  cc_change: number;
  before_fishz: number;
  after_fishz: number;
  before_relative_z: number;
  after_relative_z: number;
  refined_score: number;
  baseline_score: number | null;
  score_change: number | null;
  population: number | null;
  cluster_score: number | null;
  cluster_score_std: number | null;
}

export interface ProvenanceAction extends Row {
  command: string;
  start_time: string | null;
  end_time: string | null;
  inputs: string[];
  outputs: string[];
}

/** URL restoration determines all datasets needed by the page and its details panel. */
export function datasetsForView(view: string, selection: string | null): Dataset[] {
  const names: Dataset[] =
    view === "provenance" ? ["provenance"] : ["candidates", "fitting", "refinements"];
  if (selection)
    for (const name of ["candidates", "fitting", "refinements"] as const)
      if (!names.includes(name)) names.push(name);
  return names;
}

export function positivePage(value: string | null): number {
  const n = Number(value);
  return Number.isSafeInteger(n) && n > 0 ? n : 1;
}

export function tablePageSize(value: string | null): number {
  const n = Number(value);
  return [25, 50, 100].includes(n) ? n : 50;
}

export function topSelection(value: string | null): string {
  return value && ["1", "3", "5", "10", "all"].includes(value) ? value : "1";
}
