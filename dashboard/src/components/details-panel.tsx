import { lazy, Suspense, useEffect, useId, useState } from "react";
import { display, fileUrl } from "../data";
import { useDashboardNavigation } from "../hooks/use-dashboard-navigation";
import { useDetailsPanel } from "../hooks/use-details-panel";
import { ResultDetails } from "./result-details";
const StructureViewer = lazy(() =>
  import("../viewer").then((m) => ({ default: m.StructureViewer })),
);

function CopyPathButton({ path, label }: { path: string; label: string }) {
  const [status, setStatus] = useState("");
  useEffect(() => {
    if (!status) return;
    const timer = setTimeout(() => setStatus(""), 2000);
    return () => clearTimeout(timer);
  }, [status]);
  return (
    <button
      type="button"
      title={path}
      aria-label={`Copy ${label.toLowerCase()} path`}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(path);
          setStatus("Copied");
        } catch {
          setStatus("Copy failed");
        }
      }}
    >
      <svg
        aria-hidden="true"
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
      >
        <rect x="8" y="8" width="12" height="14" rx="2" />
        <path d="M16 8V4a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h4" />
      </svg>
      {label}
      <span role="status">{status}</span>
    </button>
  );
}

export function DetailsPanel() {
  const fileMenuId = useId();
  const { navigate, selectedId } = useDashboardNavigation();
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
        {selected && selectedKind !== "candidates" && (
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
              {(selectedKind === "refinements"
                ? [
                    {
                      title: "Inputs",
                      files: [
                        ["density", "Density"],
                        ["fitted_model", "Unrefined fitted model"],
                        ["original_known_structure", "Original known structure"],
                      ],
                    },
                    {
                      title: "Outputs",
                      files: [
                        ["refined_fitted_structure", "Refined fitted structure"],
                        ["refined_known_structure", "Refined known structure"],
                      ],
                    },
                  ]
                : [
                    {
                      title: "Local files",
                      files: [
                        ["model", "Structure"],
                        ["density", "Density"],
                      ],
                    },
                  ]
              ).map(({ title, files }) => (
                <section key={title} className="file-paths" aria-label={title}>
                  {selectedKind === "refinements" && <h3>{title}</h3>}
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
            <StructureViewer
              structureUrl={fileUrl(viewerSelection.row.model_path)}
              densityUrl={fileUrl(viewerSelection.row.density_path)}
              refinedKnownStructureUrl={
                viewerSelection.kind === "refinements"
                  ? fileUrl(viewerSelection.row.refined_known_structure)
                  : undefined
              }
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
