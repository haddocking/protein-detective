import { useState } from "react";
import { display, fileUrl, key, type Row } from "../data";
import type { StructureViewerProps } from "../viewer";
import { useSession } from "./use-session-data";
import { useDashboardNavigation } from "./use-dashboard-navigation";
import {
  useCandidateNavigation,
  useFittingNavigation,
  useRefinementsNavigation,
  type ResultNavigation,
} from "./use-result-navigation";
type FileGroup = { title: string; showHeading: boolean; files: [kind: string, label: string][] };

function useSelectedResult({ kind, active, selectedId }: ResultNavigation) {
  const { data } = useSession();
  const selected = active ? (data[kind] ?? []).find((row) => key(row) === selectedId) : undefined;
  const viewer: StructureViewerProps | undefined = selected
    ? {
        structureUrl: fileUrl(selected.model_path),
        densityUrl: fileUrl(selected.density_path),
        label: display(selected.structure),
      }
    : undefined;
  let viewerMessage = "Structure or associated density is unavailable.";
  if (display(selected?.viewer_error) !== "—") viewerMessage = display(selected?.viewer_error);
  else if (selected?.model_available === false) viewerMessage = "Fitted structure not saved";
  return { kind, active, selected, viewer, viewerMessage };
}

function useCandidateDetails() {
  return {
    ...useSelectedResult(useCandidateNavigation()),
    resultLabel: "CANDIDATE STRUCTURE",
    viewerMessage: null,
    fileGroups: [] as FileGroup[],
  };
}

function useFittingDetails() {
  return {
    ...useSelectedResult(useFittingNavigation()),
    resultLabel: "FITTING SOLUTION",
    fileGroups: [
      {
        title: "Local files",
        showHeading: false,
        files: [
          ["model", "Structure"],
          ["density", "Density"],
        ],
      },
    ] satisfies FileGroup[],
  };
}

function useRefinementDetails() {
  const details = useSelectedResult(useRefinementsNavigation());
  return {
    ...details,
    resultLabel: "REFINEMENT MEMBER",
    viewer: details.viewer && {
      ...details.viewer,
      refined: true,
      refinedKnownStructureUrl: fileUrl(details.selected?.refined_known_structure),
    },
    fileGroups: [
      {
        title: "Inputs",
        showHeading: true,
        files: [
          ["density", "Density"],
          ["fitted_model", "Unrefined fitted model"],
          ["original_known_structure", "Original known structure"],
        ],
      },
      {
        title: "Outputs",
        showHeading: true,
        files: [
          ["refined_fitted_structure", "Refined fitted structure"],
          ["refined_known_structure", "Refined known structure"],
        ],
      },
    ] satisfies FileGroup[],
  };
}

export function useDetailsPanel() {
  const { data } = useSession();
  const { p, selectedId } = useDashboardNavigation();
  const candidates = useCandidateDetails();
  const fitting = useFittingDetails();
  const refinements = useRefinementDetails();
  const { kind, selected, viewer, resultLabel, viewerMessage, fileGroups } =
    [candidates, fitting, refinements].find((details) => details.active) ?? fitting;
  const tab = p.get("tab") ?? "viewer";
  const [viewerSelection, setViewerSelection] = useState<{
    row: Row;
    kind: string;
    props: StructureViewerProps;
  } | null>(null);
  const candidate =
    selected &&
    (data.candidates ?? []).find(
      (c) =>
        String(c.candidate_id ?? c.structure) ===
        String(selected.candidate_id ?? selected.structure),
    );
  const viewerVisible = tab === "viewer" && Boolean(selected?.viewer_available);
  const [width, setWidth] = useState(() =>
    viewerVisible ? Math.max(440, Math.round(window.innerWidth * 0.6)) : 440,
  );
  const [previousViewerVisible, setPreviousViewerVisible] = useState(viewerVisible);
  // Retain the loaded viewer while showing details, and update before children render.
  if (!selectedId && viewerSelection) setViewerSelection(null);
  else if (
    viewerVisible &&
    selected &&
    viewer &&
    (viewerSelection?.row !== selected || viewerSelection?.kind !== kind)
  ) {
    setViewerSelection({ row: selected, kind, props: viewer });
  }
  const accessionValue = selected?.uniprot_accessions ?? candidate?.uniprot_accessions;
  const accessions =
    typeof accessionValue === "string" ? accessionValue.split(/[,:;\s]+/).filter(Boolean) : [];
  if (previousViewerVisible !== viewerVisible) {
    setPreviousViewerVisible(viewerVisible);
    if (viewerVisible)
      setWidth((current) => Math.max(current, Math.round(window.innerWidth * 0.6)));
  }
  return {
    selected,
    resultLabel,
    viewerMessage,
    fileGroups,
    candidate,
    viewerVisible,
    viewerSelection,
    accessions,
    width,
    setWidth,
  };
}
