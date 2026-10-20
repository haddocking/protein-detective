import { useState } from "react";
import { key, type Dataset, type Row } from "../data";
import { useSession } from "./use-session-data";
import { useDashboardNavigation } from "./use-dashboard-navigation";
export function useDetailsPanel() {
  const { data } = useSession();
  const { view, p, selectedId } = useDashboardNavigation();
  const tab = p.get("tab");
  const kind = view === "refinements" ? "refinements" : "fitting";
  const [viewerSelection, setViewerSelection] = useState<{ row: Row; kind: string } | null>(null);
  const [width, setWidth] = useState(() =>
    tab === "viewer" ? Math.max(440, Math.round(window.innerWidth * 0.6)) : 440,
  );
  const [previousTab, setPreviousTab] = useState(tab);
  const selectedKind = p.get("selection") || kind;
  const selected = (data[selectedKind as Dataset] ?? []).find((r) => key(r) === selectedId);
  const candidate =
    selected &&
    (data.candidates ?? []).find(
      (c) =>
        String(c.candidate_id ?? c.structure) ===
        String(selected.candidate_id ?? selected.structure),
    );
  const viewerVisible = p.get("tab") === "viewer" && Boolean(selected?.viewer_available);
  // Retain the loaded viewer while showing details, and update before children render.
  if (!selectedId && viewerSelection) setViewerSelection(null);
  else if (
    viewerVisible &&
    selected &&
    (viewerSelection?.row !== selected || viewerSelection?.kind !== selectedKind)
  ) {
    setViewerSelection({ row: selected, kind: selectedKind });
  }
  const accessionValue = selected?.uniprot_accessions ?? candidate?.uniprot_accessions;
  const accessions =
    typeof accessionValue === "string" ? accessionValue.split(/[,:;\s]+/).filter(Boolean) : [];
  if (previousTab !== tab) {
    setPreviousTab(tab);
    if (tab === "viewer")
      setWidth((current) => Math.max(current, Math.round(window.innerWidth * 0.6)));
  }
  return {
    selected,
    selectedKind,
    candidate,
    viewerVisible,
    viewerSelection,
    accessions,
    width,
    setWidth,
  };
}
