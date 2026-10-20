import React, { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  csv,
  datasetsForView,
  positivePage,
  tablePageSize,
  topSelection,
  display,
  fileUrl,
  filterRows,
  fittingColumns,
  grouped,
  key,
  labels,
  refinementColumns,
  sorted,
  clusterKey,
  type Dataset,
  type Row,
} from "./data";
import { Histogram, Scatter } from "./charts";
import "./style.css";
const StructureViewer = lazy(() =>
  import("./viewer").then((m) => ({ default: m.StructureViewer })),
);
const detailsFields = new Set([
  "structure",
  "structure_id",
  "uniprot_accessions",
  "source",
  "filtering_status",
  "rejection_reason",
  "powerfit_run_id",
  "refine_run_id",
  "rank",
  "cc",
  "fishz",
  "relative_z",
  "fitted_rank",
  "cluster_id",
  "cluster_rank",
  "member_rank",
  "refined_score",
  "baseline_score",
  "score_change",
  "population",
  "cluster_score",
  "cluster_score_std",
]);
const views = [
  ["overview", "Overview"],
  ["fitting", "Fitting results"],
  ["refinements", "Refinement results"],
  ["provenance", "Provenance"],
];
function clusterLabel(r: Row | undefined) {
  return r
    ? `${display(r.refine_run_id)} / ${display(r.structure)} · fitted ${display(r.fitted_rank)} · cluster ${display(r.cluster_id)}`
    : "Unknown cluster";
}
function App() {
  const [url, setUrl] = useState(() => new URL(location.href));
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const [data, setData] = useState<Partial<Record<Dataset, Row[]>>>({});
  const [summary, setSummary] = useState<Row>({});
  const requested = useRef(new Set<Dataset>());
  const [notice, setNotice] = useState("");
  const [viewerSelection, setViewerSelection] = useState<{ row: Row; kind: string } | null>(null);
  const [width, setWidth] = useState(() =>
    new URLSearchParams(location.search).get("tab") === "viewer"
      ? Math.max(440, Math.round(window.innerWidth * 0.6))
      : 440,
  );
  const [copied, setCopied] = useState("");
  const view = views.some((v) => v[0] === url.pathname.slice(1))
    ? url.pathname.slice(1)
    : "overview";
  const p = url.searchParams;
  const kind = view === "refinements" ? "refinements" : "fitting";
  function navigate(changes: Record<string, string | null>, nextView = view) {
    if (changes.tab === "viewer") {
      setWidth((current) => Math.max(current, Math.round(window.innerWidth * 0.6)));
    }
    const next = new URL(location.href);
    next.pathname = "/" + nextView;
    if (nextView !== view) next.search = "";
    for (const [k, v] of Object.entries(changes)) {
      if (v === null) next.searchParams.delete(k);
      else next.searchParams.set(k, v);
    }
    history.pushState({}, "", next);
    setUrl(next);
  }
  useEffect(() => {
    const handler = () => setUrl(new URL(location.href));
    addEventListener("popstate", handler);
    return () => removeEventListener("popstate", handler);
  }, []);
  async function get<T>(name: string): Promise<T> {
    const response = await fetch("/api/" + name);
    if (!response.ok)
      throw new Error(
        response.status === 401
          ? "Open the current launch URL printed by protein-detective dashboard to authenticate."
          : `Could not load ${name} (${response.status}).`,
      );
    return response.json();
  }
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const token = new URLSearchParams(location.hash.slice(1)).get("token");
        if (token) {
          const response = await fetch("/api/auth", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ token }),
          });
          if (!response.ok)
            throw new Error(
              "Authentication failed. Open the current launch URL printed by protein-detective dashboard.",
            );
          history.replaceState({}, "", location.pathname + location.search);
        }
        const s = await get<Row>("summary");
        if (!cancelled) {
          setSummary(s);
          setReady(true);
        }
      } catch (e) {
        if (!cancelled) setError(String(e instanceof Error ? e.message : e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);
  useEffect(() => {
    if (!ready) return;
    const names = datasetsForView(view, p.get("selected"));
    for (const name of names)
      if (!requested.current.has(name)) {
        requested.current.add(name);
        get<Row[]>(name)
          .then((rows) => setData((current) => ({ ...current, [name]: rows })))
          .catch((e) => setError(e.message));
      }
  }, [ready, view, p.get("selected"), p.get("selection")]);
  const rows = data[kind] ?? [];
  const filtered = useMemo(() => filterRows(rows, p), [rows, url]);
  const columns = kind === "fitting" ? fittingColumns : refinementColumns;
  const sort = columns.includes(p.get("sort") ?? "")
    ? p.get("sort")!
    : kind === "fitting"
      ? "cc"
      : "refined_score";
  const desc = p.get("dir") ? p.get("dir") === "desc" : kind === "fitting";
  const limit = topSelection(p.get("top"));
  const selectedRows = useMemo(
    () => sorted(grouped(filtered, kind, limit), sort, desc),
    [filtered, kind, limit, sort, desc],
  );
  const pageSize = tablePageSize(p.get("size"));
  const page = Math.min(
    positivePage(p.get("page")),
    Math.max(
      1,
      Math.ceil(
        (view === "overview" ? filterRows(data.candidates ?? [], p).length : selectedRows.length) /
          pageSize,
      ),
    ),
  );
  const selectedId = p.get("selected");
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
  useEffect(() => {
    if (!selectedId) setViewerSelection(null);
    else if (viewerVisible && selected) setViewerSelection({ row: selected, kind: selectedKind });
  }, [selectedId, selected, selectedKind, viewerVisible]);
  const accessionValue = selected?.uniprot_accessions ?? candidate?.uniprot_accessions;
  const accessions =
    typeof accessionValue === "string" ? accessionValue.split(/[,:;\s]+/).filter(Boolean) : [];
  function select(r: Row, type: string, tab = "details") {
    navigate({ selected: key(r), selection: type, tab });
  }
  function exportCsv() {
    const blob = new Blob([csv(selectedRows, columns)], { type: "text/csv;charset=utf-8" });
    const href = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = href;
    a.download = `protein-detective-${kind}.csv`;
    a.click();
    URL.revokeObjectURL(href);
  }
  function chartSelect(row: Row) {
    const included = selectedRows.some((r) => key(r) === key(row));
    const all = sorted(grouped(filtered, kind, included ? limit : "all"), sort, desc);
    if (!included) setNotice("Switched to All members to reveal the selected chart point.");
    navigate({
      selected: key(row),
      selection: "refinements",
      tab: "details",
      top: included ? limit : "all",
      page: String(Math.floor(all.findIndex((r) => key(r) === key(row)) / pageSize) + 1),
    });
  }
  function table(items: Row[], cols: string[], type: string, sortable = false) {
    return (
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              {cols.map((c) => (
                <th key={c}>
                  {sortable ? (
                    <button
                      onClick={() =>
                        navigate({ sort: c, dir: sort === c && desc ? "asc" : "desc", page: "1" })
                      }
                    >
                      {labels[c] ?? c}
                      {sort === c ? (desc ? " ↓" : " ↑") : ""}
                    </button>
                  ) : (
                    (labels[c] ?? c)
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {items.map((r, i) => (
              <tr
                key={key(r) + "-" + i}
                className={selectedId === key(r) ? "selected" : ""}
                onClick={() => select(r, type)}
              >
                {cols.map((c, j) => (
                  <td
                    key={c}
                    className={c === "score_change" && Number(r[c]) < 0 ? "improved" : ""}
                  >
                    {j === 0 ? (
                      <button
                        className="text-link"
                        onClick={(e) => {
                          e.stopPropagation();
                          select(r, type);
                        }}
                      >
                        {display(r[c])}
                      </button>
                    ) : c === "model_available" ? (
                      r[c] ? (
                        "Saved"
                      ) : (
                        "Not saved"
                      )
                    ) : (
                      display(r[c])
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {!items.length && <p className="empty">No results match these filters.</p>}
      </div>
    );
  }
  function emptyResults() {
    if (summary.fitting_status === "no_runs" || !summary.fitting_solutions)
      return (
        <div className="empty">
          <h3>
            {summary.fitting_status === "incomplete"
              ? "Fitting is incomplete or results are missing."
              : "No fitting solutions yet"}
          </h3>
          <p>Run PowerFit to compare candidate structures with your density map.</p>
          <code>protein-detective powerfit run TARGET_MAP RESOLUTION SESSION_DIR</code>
        </div>
      );
    return (
      <div className="empty">
        <h3>No refinement results</h3>
        <p>Available candidates and fitting results remain accessible.</p>
      </div>
    );
  }
  return (
    <>
      <header>
        <div className="brand">
          <span className="logo">⌕</span>
          <div>
            <strong>Protein Detective</strong>
            <small>Session explorer</small>
          </div>
        </div>
        <span className="snapshot">Read-only snapshot</span>
      </header>
      <nav aria-label="Main navigation">
        {views.map(([id, title]) => (
          <a
            key={id}
            href={"/" + id}
            aria-current={view === id ? "page" : undefined}
            onClick={(e) => {
              e.preventDefault();
              navigate({}, id);
            }}
          >
            {title}
          </a>
        ))}
      </nav>
      {error ? (
        <div className="error" role="alert">
          {error}
        </div>
      ) : !ready ? (
        <p className="empty">Authenticating and loading session…</p>
      ) : (
        <div className="workspace">
          <main>
            <div className="page-title">
              <div>
                <p className="eyebrow">PROTEIN DETECTIVE / {view.toUpperCase()}</p>
                <h1>{views.find((v) => v[0] === view)?.[1]}</h1>
              </div>
              {(view === "fitting" || view === "refinements") && (
                <button onClick={exportCsv} disabled={!selectedRows.length}>
                  Export CSV ↓
                </button>
              )}
            </div>
            {notice && (
              <p className="notice" role="status">
                {notice}
                <button onClick={() => setNotice("")} aria-label="Dismiss notification">
                  ×
                </button>
              </p>
            )}
            {view === "overview" && (
              <>
                <p className="muted">
                  Explore candidate structures, fitting solutions, and refinement outcomes.
                </p>
                <div className="stats">
                  {[
                    "candidate_structures",
                    "uniprot_accessions",
                    "filtering_passed",
                    "filtering_rejected",
                    "fitting_solutions",
                    "fitted_structures",
                    "refinement_runs",
                    "refined_structures",
                  ]
                    .filter((k) => summary[k] != null)
                    .map((k) => (
                      <div className="stat" key={k}>
                        <strong>{Number(summary[k]).toLocaleString()}</strong>
                        <span>{k.replaceAll("_", " ")}</span>
                      </div>
                    ))}
                </div>
                <div className="overview-results">
                  <section>
                    <h2>Highest fitting CC</h2>
                    {data.fitting ? (
                      table(
                        sorted(grouped(data.fitting, "fitting", "1"), "cc", true).slice(0, 5),
                        ["structure", "powerfit_run_id", "cc"],
                        "fitting",
                      )
                    ) : (
                      <p>Loading fitting results…</p>
                    )}
                    <a
                      href="/fitting"
                      onClick={(e) => {
                        e.preventDefault();
                        navigate({}, "fitting");
                      }}
                    >
                      Explore fitting results →
                    </a>
                  </section>
                  <section>
                    <h2>Lowest refinement scores</h2>
                    {data.refinements ? (
                      table(
                        sorted(
                          grouped(data.refinements, "refinements", "1"),
                          "refined_score",
                          false,
                        ).slice(0, 5),
                        ["structure", "refine_run_id", "refined_score"],
                        "refinements",
                      )
                    ) : (
                      <p>Loading refinement results…</p>
                    )}
                    <a
                      href="/refinements"
                      onClick={(e) => {
                        e.preventDefault();
                        navigate({}, "refinements");
                      }}
                    >
                      Explore refinements →
                    </a>
                  </section>
                </div>
                <section>
                  <div className="section-heading">
                    <h2>Candidate structures</h2>
                    <input
                      aria-label="Search candidates"
                      placeholder="Search structure or UniProt…"
                      value={p.get("q") || ""}
                      onChange={(e) => navigate({ q: e.target.value, page: "1" })}
                    />
                  </div>
                  {data.candidates ? (
                    table(
                      filterRows(data.candidates, p).slice((page - 1) * pageSize, page * pageSize),
                      [
                        "structure",
                        "uniprot_accessions",
                        "source",
                        "filtering_status",
                        "rejection_reason",
                      ],
                      "candidates",
                    )
                  ) : (
                    <p>Loading candidates…</p>
                  )}
                  <div className="pagination">
                    <button
                      disabled={page <= 1}
                      onClick={() => navigate({ page: String(page - 1) })}
                    >
                      Previous
                    </button>
                    <span>
                      Page {page} · {filterRows(data.candidates ?? [], p).length} candidates
                    </span>
                    <button
                      disabled={page * pageSize >= filterRows(data.candidates ?? [], p).length}
                      onClick={() => navigate({ page: String(page + 1) })}
                    >
                      Next
                    </button>
                  </div>
                </section>
              </>
            )}
            {(view === "fitting" || view === "refinements") && (
              <>
                <div className="filters">
                  <label>
                    Search
                    <input
                      placeholder="Structure or UniProt"
                      value={p.get("q") || ""}
                      onChange={(e) => navigate({ q: e.target.value, page: "1" })}
                    />
                  </label>
                  {[
                    "source",
                    "powerfit_run_id",
                    ...(kind === "refinements" ? ["refine_run_id", "cluster"] : []),
                  ].map((k) => (
                    <label key={k}>
                      {k === "cluster" ? "Cluster / fitted input" : labels[k]}
                      <select
                        value={p.get(k) || ""}
                        onChange={(e) => navigate({ [k]: e.target.value, page: "1" })}
                      >
                        <option value="">
                          All {k === "cluster" ? "clusters" : labels[k]?.toLowerCase() + "s"}
                        </option>
                        {[
                          ...new Set(
                            rows
                              .map((r) =>
                                k === "cluster"
                                  ? clusterKey(r)
                                  : typeof r[k] === "string"
                                    ? r[k]
                                    : "",
                              )
                              .filter(Boolean),
                          ),
                        ]
                          .sort()
                          .map((v) => (
                            <option key={v} value={v}>
                              {k === "cluster"
                                ? clusterLabel(rows.find((r) => clusterKey(r) === v))
                                : display(v)}
                            </option>
                          ))}
                      </select>
                    </label>
                  ))}
                  <label>
                    {kind === "fitting"
                      ? "Solutions per structure / run"
                      : "Members per cluster / input / run"}
                    <select
                      value={limit}
                      onChange={(e) => navigate({ top: e.target.value, page: "1" })}
                    >
                      <option value="1">Best only</option>
                      <option value="3">Top 3</option>
                      <option value="5">Top 5</option>
                      <option value="10">Top 10</option>
                      <option value="all">
                        {kind === "fitting" ? "All solutions" : "All members"}
                      </option>
                    </select>
                  </label>
                  <button
                    className="subtle"
                    onClick={() =>
                      navigate({
                        q: null,
                        source: null,
                        powerfit_run_id: null,
                        refine_run_id: null,
                        cluster: null,
                        top: null,
                        page: "1",
                      })
                    }
                  >
                    Clear filters
                  </button>
                </div>
                {!data[kind] ? (
                  <p className="empty">Loading {kind}…</p>
                ) : !rows.length ? (
                  emptyResults()
                ) : (
                  <>
                    <section className="chart-section">
                      <div>
                        <h2>
                          {kind === "fitting" ? "Score distribution" : "Refinement comparison"}
                        </h2>
                        <p className="muted">
                          All {filtered.length.toLocaleString()} matching{" "}
                          {kind === "fitting" ? "solutions" : "members"}, before top-N selection and
                          pagination.
                        </p>
                        {kind === "fitting" ? (
                          <label>
                            Metric{" "}
                            <select
                              value={p.get("metric") || "cc"}
                              onChange={(e) => navigate({ metric: e.target.value })}
                            >
                              <option value="cc">CC</option>
                              <option value="fishz">FishZ</option>
                              <option value="relative_z">Relative Z</option>
                            </select>
                          </label>
                        ) : (
                          <p>
                            Points below the diagonal improved.
                            <br />
                            Select a point to inspect its result.
                          </p>
                        )}
                      </div>
                      {kind === "fitting" ? (
                        <Histogram rows={filtered} metric={p.get("metric") || "cc"} />
                      ) : (
                        <Scatter rows={filtered} onSelect={chartSelect} />
                      )}
                    </section>
                    {kind === "fitting" && !Number(summary.fitted_structures) && (
                      <p className="notice">
                        Solutions exist but fitted structures have not been saved. Run{" "}
                        <code>protein-detective powerfit fit-models</code> to enable 3D viewing.
                      </p>
                    )}
                    <section>
                      <div className="section-heading">
                        <h2>
                          {selectedRows.length.toLocaleString()}{" "}
                          {kind === "fitting" ? "solutions" : "members"}
                        </h2>
                        <span className="muted">
                          {kind === "fitting"
                            ? "Higher CC is better"
                            : "Score change = refined − baseline; negative is better"}
                        </span>
                      </div>
                      {table(
                        selectedRows.slice((page - 1) * pageSize, page * pageSize),
                        columns,
                        kind,
                        true,
                      )}
                      <div className="pagination">
                        <label>
                          Rows{" "}
                          <select
                            value={pageSize}
                            onChange={(e) => navigate({ size: e.target.value, page: "1" })}
                          >
                            {[25, 50, 100].map((n) => (
                              <option key={n}>{n}</option>
                            ))}
                          </select>
                        </label>
                        <span>
                          {(page - 1) * pageSize + Number(selectedRows.length > 0)}–
                          {Math.min(page * pageSize, selectedRows.length)} of{" "}
                          {selectedRows.length.toLocaleString()}
                        </span>
                        <button
                          disabled={page === 1}
                          onClick={() => navigate({ page: String(page - 1) })}
                        >
                          Previous
                        </button>
                        <span>
                          Page {page} / {Math.max(1, Math.ceil(selectedRows.length / pageSize))}
                        </span>
                        <button
                          disabled={page * pageSize >= selectedRows.length}
                          onClick={() => navigate({ page: String(page + 1) })}
                        >
                          Next
                        </button>
                      </div>
                    </section>
                  </>
                )}
              </>
            )}
            {view === "provenance" && (
              <>
                <p className="muted">Recorded workflow commands and their inputs and outputs.</p>
                {!data.provenance ? (
                  <p>Loading provenance…</p>
                ) : !data.provenance.length ? (
                  <p className="empty">No recorded workflow commands.</p>
                ) : (
                  sorted(data.provenance, "start_time", false).map((r, i) => (
                    <section className="provenance" key={i}>
                      <div className="section-heading">
                        <span className="step">{i + 1}</span>
                        <code>{display(r.command)}</code>
                        <button
                          onClick={() =>
                            navigator.clipboard
                              .writeText(display(r.command))
                              .then(() => setCopied(String(i)))
                          }
                        >
                          {copied === String(i) ? "Copied" : "Copy command"}
                        </button>
                      </div>
                      <details>
                        <summary>
                          {display(r.start_time)} · Inspect timestamps and recorded paths
                        </summary>
                        <dl>
                          {Object.entries(r)
                            .filter(([k]) => k !== "command")
                            .map(([k, v]) => (
                              <React.Fragment key={k}>
                                <dt>{k.replaceAll("_", " ")}</dt>
                                <dd>
                                  <pre>
                                    {typeof v === "object"
                                      ? JSON.stringify(v, null, 2)
                                      : display(v)}
                                  </pre>
                                </dd>
                              </React.Fragment>
                            ))}
                        </dl>
                      </details>
                    </section>
                  ))
                )}
              </>
            )}
          </main>
          {selectedId && (
            <aside
              className={p.get("tab") === "viewer" ? "viewer-panel" : undefined}
              style={{ width }}
            >
              <div
                className="resizer"
                role="separator"
                aria-label="Resize details panel"
                aria-orientation="vertical"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === "ArrowLeft")
                    setWidth((w) => Math.min(window.innerWidth - 360, w + 25));
                  if (e.key === "ArrowRight") setWidth((w) => Math.max(320, w - 25));
                }}
                onPointerDown={(e) => {
                  e.currentTarget.setPointerCapture(e.pointerId);
                  const start = e.clientX,
                    original = width;
                  const move = (event: PointerEvent) =>
                    setWidth(
                      Math.max(
                        320,
                        Math.min(window.innerWidth - 360, original + start - event.clientX),
                      ),
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
                <div className="details-content">
                  <p className="eyebrow">
                    {selectedKind === "candidates"
                      ? "CANDIDATE STRUCTURE"
                      : selectedKind === "fitting"
                        ? "FITTING SOLUTION"
                        : "REFINEMENT MEMBER"}
                  </p>
                  <h2>{display(selected.structure)}</h2>
                  <div className="links">
                    {accessions.map((id) => (
                      <a
                        key={id}
                        href={"https://www.uniprot.org/uniprotkb/" + encodeURIComponent(id)}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {id} ↗
                      </a>
                    ))}
                    {(selected.source ?? candidate?.source) === "PDB" && (
                      <a
                        href={
                          "https://www.ebi.ac.uk/pdbe/entry/pdb/" +
                          String(
                            selected.structure_id ?? candidate?.structure_id ?? selected.structure,
                          ).slice(0, 4)
                        }
                        target="_blank"
                        rel="noreferrer"
                      >
                        PDB source ↗
                      </a>
                    )}
                    {(selected.source ?? candidate?.source) === "AlphaFold" && (
                      <a
                        href={
                          "https://alphafold.ebi.ac.uk/entry/" +
                          encodeURIComponent(
                            String(
                              selected.uniprot_accessions ??
                                candidate?.uniprot_accessions ??
                                selected.structure,
                            ).split(/[:,;\s]+/)[0],
                          )
                        }
                        target="_blank"
                        rel="noreferrer"
                      >
                        AlphaFold source ↗
                      </a>
                    )}
                  </div>
                  {selected.viewer_available ? (
                    <button className="primary" onClick={() => navigate({ tab: "viewer" })}>
                      View structure
                    </button>
                  ) : (
                    selectedKind !== "candidates" && (
                      <p className="notice">
                        {String(
                          display(selected.viewer_error) !== "—"
                            ? display(selected.viewer_error)
                            : selected.model_available === false
                              ? "Fitted structure not saved"
                              : "Structure or associated density is unavailable.",
                        )}
                      </p>
                    )
                  )}
                  <dl>
                    {Object.entries({ ...candidate, ...selected })
                      .filter(
                        ([k, v]) =>
                          v != null &&
                          (detailsFields.has(k) ||
                            /plddt|resolution|quality|ramachandran|clash|r_free|r_work|confidence|rmsd|sequence_identity/.test(
                              k,
                            )) &&
                          typeof v !== "object",
                      )
                      .map(([k, v]) => (
                        <React.Fragment key={k}>
                          <dt>{labels[k] ?? k.replaceAll("_", " ")}</dt>
                          <dd>{display(v)}</dd>
                        </React.Fragment>
                      ))}
                  </dl>
                  <details>
                    <summary>Additional recorded metadata</summary>
                    <pre>{JSON.stringify({ ...candidate, ...selected }, null, 2)}</pre>
                  </details>
                  {["fitting", "refinements"].map((type) => {
                    const related = (data[type as Dataset] ?? []).filter(
                      (r) =>
                        String(r.candidate_id ?? r.structure) ===
                        String(selected.candidate_id ?? selected.structure),
                    );
                    return (
                      related.length > 0 && (
                        <div key={type}>
                          <h3>
                            Related {type} ({related.length})
                          </h3>
                          {related.slice(0, 20).map((r) => (
                            <button
                              className="related"
                              key={key(r)}
                              onClick={() => select(r, type)}
                            >
                              {display(r.powerfit_run_id)} ·{" "}
                              {type === "fitting"
                                ? `rank ${display(r.rank)} · CC ${display(r.cc)}`
                                : `${display(r.refine_run_id)} · score ${display(r.refined_score)}`}
                            </button>
                          ))}
                          {related.length > 20 && (
                            <a
                              href={"/" + type}
                              onClick={(e) => {
                                e.preventDefault();
                                navigate({ q: String(selected.structure) }, type);
                              }}
                            >
                              See all related results →
                            </a>
                          )}
                        </div>
                      )
                    );
                  })}
                </div>
              )}
            </aside>
          )}
        </div>
      )}
      <footer>
        Stable session snapshot · Do not modify the session directory while this dashboard is
        running.
      </footer>
    </>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
