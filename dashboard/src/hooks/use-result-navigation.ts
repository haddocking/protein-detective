import { key, type Row } from "../data";
import type { View } from "../navigation";
import { useDashboardNavigation } from "./use-dashboard-navigation";

function useResultNavigation<Kind extends "candidates" | "fitting" | "refinements">(
  kind: Kind,
  defaultViews: View[],
) {
  const navigation = useDashboardNavigation();
  const selection = navigation.p.get("selection");
  const active = selection ? selection === kind : defaultViews.includes(navigation.view);

  function select(row: Row, tab = row.viewer_available ? "viewer" : "details") {
    navigation.navigate({ selected: key(row), selection: kind, tab });
  }

  return {
    ...navigation,
    kind,
    active,
    selectedId: active ? navigation.selectedId : null,
    select,
  };
}

export function useFittingNavigation() {
  return useResultNavigation("fitting", ["overview", "fitting", "provenance"]);
}

export function useRefinementsNavigation() {
  return useResultNavigation("refinements", ["refinements"]);
}

export function useCandidateNavigation() {
  return useResultNavigation("candidates", []);
}

export type ResultNavigation = ReturnType<typeof useResultNavigation>;
