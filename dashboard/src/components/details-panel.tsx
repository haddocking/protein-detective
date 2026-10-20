import { lazy, Suspense } from "react";
import { display, fileUrl } from "../data";
import { useDashboardNavigation } from "../hooks/use-dashboard-navigation";
import { useDetailsPanel } from "../hooks/use-details-panel";
import { ResultDetails } from "./result-details";
const StructureViewer = lazy(() =>
  import("../viewer").then((m) => ({ default: m.StructureViewer })),
);

export function DetailsPanel() {
  const { p, navigate, selectedId } = useDashboardNavigation();
  const {
    selected,
    selectedKind,
    candidate,
    viewerVisible,
    viewerSelection,
    accessions,
    width,
    setWidth,
  } = useDetailsPanel();
  if (!selectedId) return null;
  return (
    <aside className={p.get("tab") === "viewer" ? "viewer-panel" : undefined} style={{ width }}>
      <div
        className="resizer"
        role="separator"
        aria-label="Resize details panel"
        aria-orientation="vertical"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "ArrowLeft") setWidth((w) => Math.min(window.innerWidth - 360, w + 25));
          if (e.key === "ArrowRight") setWidth((w) => Math.max(320, w - 25));
        }}
        onPointerDown={(e) => {
          e.currentTarget.setPointerCapture(e.pointerId);
          const start = e.clientX,
            original = width;
          const move = (event: PointerEvent) =>
            setWidth(
              Math.max(320, Math.min(window.innerWidth - 360, original + start - event.clientX)),
            );
          const up = () => {
            removeEventListener("pointermove", move);
            removeEventListener("pointerup", up);
          };
          addEventListener("pointermove", move);
          addEventListener("pointerup", up);
        }}
      />
      <div className="panel-header">
        <strong>{display(selected?.structure ?? selectedId)}</strong>
        <button
          aria-label="Close details panel"
          onClick={() => navigate({ selected: null, selection: null, tab: null })}
        >
          ×
        </button>
      </div>
      <div className="tabs">
        <button
          aria-pressed={p.get("tab") !== "viewer"}
          onClick={() => navigate({ tab: "details" })}
        >
          Details
        </button>
        <button
          disabled={!selected?.viewer_available}
          aria-pressed={p.get("tab") === "viewer"}
          onClick={() => navigate({ tab: "viewer" })}
        >
          3D viewer
        </button>
      </div>
      {viewerSelection && (
        <div className="retained-viewer" hidden={!viewerVisible}>
          <Suspense fallback={<p>Loading 3D viewer…</p>}>
            <StructureViewer
              structureUrl={fileUrl(viewerSelection.row.model_path)}
              densityUrl={fileUrl(viewerSelection.row.density_path)}
              refined={viewerSelection.kind === "refinements"}
              label={display(viewerSelection.row.structure)}
            />
          </Suspense>
        </div>
      )}
      {!selected ? (
        <p className="empty">Loading selected result…</p>
      ) : viewerVisible ? null : (
        <ResultDetails
          selected={selected}
          selectedKind={selectedKind}
          candidate={candidate}
          accessions={accessions}
        />
      )}
    </aside>
  );
}
