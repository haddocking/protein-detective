import { useEffect, useRef, useState } from "react";

// This runtime is deliberately external: no Mol* code enters the application bundle.
const CDN = "https://cdn.jsdelivr.net/npm/molstar@5.4.2/build/viewer/";
const INTEGRITY = {
  js: "sha384-KPjE4DR+Gi9m+RcA+CPrlPL0J/Hm8WNAZCGeweLJXS+yN5QiHsUUA/9Xcy/KAHmX",
  css: "sha384-OIZzP2/tcSEcDPl+fLOn1/a8+WsnX1G56OLq90JfKyBEzfFHKojppLf/8rprUx6I",
};
// The pinned CDN runtime has its own dynamic plugin API. Keep that boundary here.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Runtime = any;
declare global {
  interface Window {
    molstar?: Runtime;
  }
}
let runtimePromise: Promise<Runtime> | undefined;
let stylesheetReady = false;

function loadRuntime(): Promise<Runtime> {
  if (window.molstar && stylesheetReady) return Promise.resolve(window.molstar);
  if (runtimePromise) return runtimePromise;
  runtimePromise = Promise.all([
    new Promise<void>((resolve, reject) => {
      if (stylesheetReady) {
        resolve();
        return;
      }
      const style = document.createElement("link");
      style.rel = "stylesheet";
      style.href = `${CDN}molstar.css`;
      style.integrity = INTEGRITY.css;
      style.crossOrigin = "anonymous";
      style.onload = () => {
        stylesheetReady = true;
        resolve();
      };
      style.onerror = () => {
        style.remove();
        reject(new Error("Mol* stylesheet download failed."));
      };
      document.head.append(style);
    }),
    new Promise<void>((resolve, reject) => {
      if (window.molstar) {
        resolve();
        return;
      }
      const script = document.createElement("script");
      script.src = `${CDN}molstar.js`;
      script.integrity = INTEGRITY.js;
      script.crossOrigin = "anonymous";
      script.async = true;
      script.onload = () => resolve();
      script.onerror = () => {
        script.remove();
        reject(new Error("Mol* script download failed."));
      };
      document.head.append(script);
    }),
  ])
    .then(() => {
      if (!window.molstar) throw new Error("Mol* did not initialize.");
      return window.molstar;
    })
    .catch((error: unknown) => {
      runtimePromise = undefined;
      throw error;
    });
  return runtimePromise;
}

async function modelText(url: string, signal: AbortSignal): Promise<string> {
  const local = new URL(url, location.href);
  if (local.origin !== location.origin)
    throw new Error("Structure files must use the dashboard origin.");
  const response = await fetch(local, { credentials: "same-origin", signal });
  if (!response.ok)
    throw new Error(
      response.status === 401
        ? "Session expired. Open the current dashboard launch URL."
        : `Structure file could not be loaded (HTTP ${response.status}).`,
    );
  const bytes = await response.arrayBuffer();
  const header = new Uint8Array(bytes);
  // Detect gzip bytes, since a server may already have decompressed Content-Encoding.
  if (header[0] === 0x1f && header[1] === 0x8b) {
    const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
    return new Response(stream).text();
  }
  return new TextDecoder().decode(bytes);
}

export interface StructureViewerProps {
  structureUrl: string;
  densityUrl: string;
  refined?: boolean;
  label?: string;
}

export function StructureViewer({
  structureUrl,
  densityUrl,
  refined = false,
  label = "Selected structure",
}: StructureViewerProps) {
  const target = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<Runtime>(null);
  const sessionRef = useRef<{
    disposed: boolean;
    viewer: Promise<Runtime>;
    queue: Promise<void>;
    modelRoots: string[];
    densityRoots: string[];
    densityUrl: string | null;
  } | null>(null);
  const reps = useRef<Runtime[]>([]);
  const volume = useRef<Runtime>(null);
  const [attempt, setAttempt] = useState(0);
  const [status, setStatus] = useState("Loading Mol* viewer…");
  const [error, setError] = useState("");
  const [ready, setReady] = useState(false);
  const [candidate, setCandidate] = useState(true);
  const [partner, setPartner] = useState(true);
  const [density, setDensity] = useState(true);
  const [opacity, setOpacity] = useState(0.25);
  const [contour, setContour] = useState(1.5);

  // The plugin belongs to this panel, rather than to an individual selection.
  useEffect(() => {
    let viewer: Runtime;
    const observer = new ResizeObserver((entries) => {
      if (entries.some((entry) => entry.contentRect.width && entry.contentRect.height))
        viewer?.plugin.handleResize();
    });
    if (target.current) observer.observe(target.current);
    const session = {
      disposed: false,
      viewer: Promise.resolve(null) as Promise<Runtime>,
      queue: Promise.resolve(),
      modelRoots: [] as string[],
      densityRoots: [] as string[],
      densityUrl: null as string | null,
    };
    session.viewer = (async () => {
      const runtime = await loadRuntime();
      if (session.disposed || !target.current) return null;
      viewer = await runtime.Viewer.create(target.current, {
        layoutIsExpanded: false,
        layoutShowControls: false,
        layoutShowSequence: false,
        layoutShowLog: false,
        layoutShowLeftPanel: false,
        layoutShowRemoteState: false,
        viewportShowExpand: true,
        volumeStreamingDisabled: true,
        extensions: [],
      });
      if (session.disposed) {
        viewer.plugin.dispose();
        return null;
      }
      viewerRef.current = viewer;
      return viewer;
    })();
    sessionRef.current = session;
    return () => {
      session.disposed = true;
      observer.disconnect();
      viewerRef.current = null;
      viewer?.plugin.dispose();
    };
  }, [attempt]);

  useEffect(() => {
    const session = sessionRef.current;
    if (!session) return;
    const controller = new AbortController();
    const obsolete = () => session.disposed || controller.signal.aborted;
    setReady(false);
    setError("");
    setStatus("Loading structure…");
    setCandidate(true);
    setPartner(true);
    // Queue plugin mutations so quick selections cannot mix old and new scenes.
    session.queue = session.queue.then(async () => {
      try {
        const viewer = await session.viewer;
        if (obsolete() || !viewer) return;
        if (!structureUrl || !densityUrl)
          throw new Error("The structure or its source density map is unavailable.");
        if (new URL(densityUrl, location.href).origin !== location.origin)
          throw new Error("Density files must use the dashboard origin.");
        const plugin = viewer.plugin;
        const removeRoots = async (roots: string[]) => {
          if (!roots.length) return;
          const update = plugin.build();
          for (const ref of roots) update.delete(ref);
          await update.commit();
          roots.length = 0;
        };
        setStatus("Loading authenticated structure…");
        const text = await modelText(structureUrl, controller.signal);
        if (obsolete()) return;
        await removeRoots(session.modelRoots);
        reps.current = [];
        if (obsolete()) return;
        const parts = refined
          ? [
              { chain: "A", name: "Candidate (chain A)", color: 0x2c7fb8 },
              { chain: "B", name: "Fixed partner (chain B)", color: 0xe89c36 },
            ]
          : [{ chain: "", name: label, color: 0x2c7fb8 }];
        for (const part of parts) {
          const pdb = part.chain
            ? text
                .split("\n")
                .filter((line) => /^(ATOM  |HETATM)/.test(line) && line[21] === part.chain)
                .join("\n") + "\nEND\n"
            : text;
          if (part.chain && !pdb.includes("ATOM"))
            throw new Error(`Refined structure is missing ${part.name}.`);
          const data = await plugin.builders.data.rawData({ data: pdb, label: part.name });
          session.modelRoots.push(data.ref);
          if (obsolete()) return;
          const trajectory = await plugin.builders.structure.parseTrajectory(data, "pdb");
          if (obsolete()) return;
          const model = await plugin.builders.structure.createModel(trajectory);
          if (obsolete()) return;
          const structure = await plugin.builders.structure.createStructure(model);
          if (obsolete()) return;
          const component = await plugin.builders.structure.tryCreateComponentStatic(
            structure,
            "all",
          );
          if (obsolete()) return;
          const rep = await plugin.builders.structure.representation.addRepresentation(component, {
            type: "cartoon",
            color: "uniform",
            colorParams: { value: part.color },
          });
          reps.current.push(rep);
          if (obsolete()) return;
        }
        if (session.densityUrl !== densityUrl) {
          await removeRoots(session.densityRoots);
          session.densityUrl = null;
          volume.current = null;
          if (obsolete()) return;
          setStatus("Loading source density map…");
          setDensity(true);
          setOpacity(0.25);
          setContour(1.5);
          const before = new Set<string>(plugin.state.data.cells.keys());
          try {
            await viewer.loadVolumeFromUrl({ url: densityUrl, format: "ccp4", isBinary: true }, [
              { type: "relative", value: 1.5, color: 0x8294a7, alpha: 0.25 },
            ]);
            session.densityUrl = densityUrl;
          } finally {
            // Track the new top-level subtree, including a partially failed load.
            for (const cell of plugin.state.data.cells.values()) {
              if (!before.has(cell.transform.ref) && before.has(cell.transform.parent))
                session.densityRoots.push(cell.transform.ref);
              if (
                !before.has(cell.transform.ref) &&
                cell.params?.values?.type?.name === "isosurface"
              )
                volume.current = cell;
            }
          }
        }
        if (obsolete()) return;
        plugin.managers.camera.reset();
        setReady(true);
        setStatus("");
      } catch (cause) {
        if (!obsolete()) {
          setError(cause instanceof Error ? cause.message : String(cause));
          setStatus("");
        }
      }
    });
    return () => controller.abort();
  }, [structureUrl, densityUrl, refined, label, attempt]);

  function visibility(index: number, visible: boolean) {
    const rep = reps.current[index];
    if (rep) viewerRef.current?.plugin.state.data.updateCellState(rep.ref, { isHidden: !visible });
  }
  function updateDensity(visible: boolean, alpha: number, level: number) {
    const cell = volume.current;
    const plugin = viewerRef.current?.plugin;
    if (!cell || !plugin) return;
    plugin.state.data.updateCellState(cell.transform.ref, { isHidden: !visible });
    void plugin
      .build()
      .to(cell.transform.ref)
      .update((old: Runtime) => ({
        ...old,
        type: {
          ...old.type,
          params: {
            ...old.type.params,
            alpha,
            isoValue: { kind: "relative", relativeValue: level },
          },
        },
      }))
      .commit()
      .catch((cause: unknown) => setError(String(cause)));
  }
  return (
    <section className="molecular-viewer" aria-label="3D structure viewer">
      <p className="muted">
        Candidate in blue{refined ? "; fixed partner in orange (both from the refined file)" : ""}.
        Density contour is in standard deviations (σ).
      </p>
      {status && <p role="status">{status}</p>}
      {error && (
        <div role="alert">
          <p>{error}</p>
          <p>
            3D viewing needs internet access to download Mol*. Other dashboard views remain
            available.
          </p>
          <button onClick={() => setAttempt((value) => value + 1)}>Retry viewer</button>
        </div>
      )}
      <div ref={target} className="molecular-canvas" />
      <fieldset disabled={!ready} className="viewer-controls">
        <legend>Display controls</legend>
        <label>
          <input
            type="checkbox"
            checked={candidate}
            onChange={(event) => {
              setCandidate(event.target.checked);
              visibility(0, event.target.checked);
            }}
          />
          Candidate
        </label>
        {refined && (
          <label>
            <input
              type="checkbox"
              checked={partner}
              onChange={(event) => {
                setPartner(event.target.checked);
                visibility(1, event.target.checked);
              }}
            />
            Fixed partner
          </label>
        )}
        <label>
          <input
            type="checkbox"
            checked={density}
            onChange={(event) => {
              setDensity(event.target.checked);
              updateDensity(event.target.checked, opacity, contour);
            }}
          />
          Density
        </label>
        <label>
          Opacity {opacity.toFixed(2)}
          <input
            type="range"
            min="0"
            max="1"
            step="0.05"
            value={opacity}
            onChange={(event) => {
              const value = Number(event.target.value);
              setOpacity(value);
              updateDensity(density, value, contour);
            }}
          />
        </label>
        <label>
          Contour {contour.toFixed(1)} σ
          <input
            type="range"
            min="0.1"
            max="6"
            step="0.1"
            value={contour}
            onChange={(event) => {
              const value = Number(event.target.value);
              setContour(value);
              updateDensity(density, opacity, value);
            }}
          />
        </label>
        <button onClick={() => viewerRef.current?.plugin.managers.camera.reset()}>
          Reset camera
        </button>
      </fieldset>
    </section>
  );
}
