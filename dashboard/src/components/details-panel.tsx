import { lazy, Suspense, useId } from "react";
import { display } from "../data";
import { useDashboardNavigation } from "../hooks/use-dashboard-navigation";
import { useDetailsPanel } from "../hooks/use-details-panel";
import { CopyPathButton } from "./copy-path-button";
import { ResultDetails } from "./result-details";
const StructureViewer = lazy(() =>
  import("../viewer").then((m) => ({ default: m.StructureViewer })),
);

export function DetailsPanel() {
  const fileMenuId = useId();
  const { navigate, selectedId } = useDashboardNavigation();
  const {
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
  } = useDetailsPanel();
  if (!selectedId) return null;
  let resultDetails = null;
  if (!selected) {
    resultDetails = <p className="empty">Loading selected result…</p>;
  } else if (!viewerVisible) {
    resultDetails = (
      <ResultDetails
        selected={selected}
        resultLabel={resultLabel}
        viewerMessage={viewerMessage}
        candidate={candidate}
        accessions={accessions}
      />
    );
  }
  return (
    <aside className={viewerVisible ? "viewer-panel" : undefined} style={{ width }}>
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
        {selected && fileGroups.length > 0 && (
          <div key={selectedId} className="file-menu">
            <button type="button" popoverTarget={fileMenuId}>
              Files ▾
            </button>
            <div
              id={fileMenuId}
              className="file-menu-content"
              popover="auto"
              onBeforeToggle={(event) => {
                if (event.newState !== "open") return;
                const menu = event.currentTarget;
                const button = menu.previousElementSibling!.getBoundingClientRect();
                menu.style.setProperty("--file-menu-top", `${button.bottom}px`);
                menu.style.setProperty(
                  "--file-menu-right",
                  `${window.innerWidth - button.right}px`,
                );
              }}
            >
              {fileGroups.map(({ title, showHeading, files }) => (
                <section key={title} className="file-paths" aria-label={title}>
                  {showHeading && <h3>{title}</h3>}
                  {files.map(([kind, label]) => {
                    const path = selected[`${kind}_absolute_path`];
                    return typeof path === "string" ? (
                      <CopyPathButton key={`${kind}:${path}`} path={path} label={label} />
                    ) : (
                      <span key={kind} className="unavailable-file" title="File unavailable">
                        {label} unavailable
                      </span>
                    );
                  })}
                </section>
              ))}
            </div>
          </div>
        )}
        <button
          aria-label="Close details panel"
          onClick={() => navigate({ selected: null, selection: null, tab: null })}
        >
          ×
        </button>
      </div>
      <div className="tabs">
        <button aria-pressed={!viewerVisible} onClick={() => navigate({ tab: "details" })}>
          Details
        </button>
        <button
          disabled={!selected?.viewer_available}
          aria-pressed={viewerVisible}
          onClick={() => navigate({ tab: "viewer" })}
        >
          3D viewer
        </button>
      </div>

      {viewerSelection && (
        <div className="retained-viewer" hidden={!viewerVisible}>
          <Suspense fallback={<p>Loading 3D viewer…</p>}>
            <StructureViewer {...viewerSelection.props} />
          </Suspense>
        </div>
      )}
      {resultDetails}
    </aside>
  );
}
