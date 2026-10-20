export const views = [
  ["overview", "Overview"],
  ["fitting", "Fitting results"],
  ["refinements", "Refinement results"],
  ["provenance", "Provenance"],
] as const;
export type View = (typeof views)[number][0];
export type ResultKind = "fitting" | "refinements";
export type DashboardSearch = Record<string, string>;

// Keep existing snapshot links (including JSON cluster identifiers) as strings.
export function parseSearch(search: string): DashboardSearch {
  return Object.fromEntries(new URLSearchParams(search));
}
export function stringifySearch(search: DashboardSearch): string {
  const value = new URLSearchParams(search).toString();
  return value ? `?${value}` : "";
}
