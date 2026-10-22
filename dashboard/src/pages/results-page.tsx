import { PageTitle } from "../components/page-title";
import { Histogram, Scatter } from "../charts";
import { EmptyResults } from "../components/empty-results";
import { ResultFilters } from "../components/result-filters";
import { ResultsTable } from "../components/results-table";
import { useSession } from "../hooks/use-session-data";
import { useDashboardNavigation } from "../hooks/use-dashboard-navigation";
import { useResults } from "../hooks/use-results";
import { type ResultKind } from "../navigation";
import { useEffect, useRef } from "react";
import { key } from "../data";
export function ResultsPage({ kind }: { kind: ResultKind }) {
  const { data, summary } = useSession();
  const { p, navigate } = useDashboardNavigation();
  const {
    rows,
    filtered,
    columns,
    sort,
    desc,
    limit,
    selectedRows,
    pageSize,
    page,
    notice,
    setNotice,
    exportCsv,
    chartSelect,
    step,
  } = useResults(kind);
  // j/k or arrow keys step through results, unless typing or interacting with the viewer.
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.altKey || event.ctrlKey || event.metaKey || event.defaultPrevented) return;
      const target = event.target;
      if (
        target instanceof Element &&
        target.closest("input, select, textarea, [contenteditable], .molecular-canvas")
      )
        return;
      const delta = { j: 1, ArrowDown: 1, k: -1, ArrowUp: -1 }[event.key];
      if (!delta) return;
      event.preventDefault();
      step(delta);
    }
    addEventListener("keydown", onKeyDown);
    return () => removeEventListener("keydown", onKeyDown);
  });
  const selectedId = p.get("selected");
  useEffect(() => {
    document.querySelector("tr.selected")?.scrollIntoView?.({ block: "nearest" });
  }, [selectedId, page]);
  // Show the first visible result in the viewer once, unless the URL already selects one.
  const autoSelected = useRef(Boolean(p.get("selected")));
  const first = data[kind] ? selectedRows[(page - 1) * pageSize] : undefined;
  useEffect(() => {
    if (autoSelected.current || !data[kind]) return;
    autoSelected.current = true;
    if (first)
      navigate(
        {
          selected: key(first),
          selection: kind,
          tab: first.viewer_available ? "viewer" : "details",
        },
        kind,
        true,
      );
  });
  return (
    <>
      <PageTitle>
        <button onClick={exportCsv} disabled={!selectedRows.length}>
          Export CSV ↓
        </button>
      </PageTitle>
      {notice && (
        <p className="notice" role="status">
          {notice}
          <button onClick={() => setNotice("")} aria-label="Dismiss notification">
            ×
          </button>
        </p>
      )}
      <>
        <ResultFilters kind={kind} rows={rows} limit={limit} />
        {!data[kind] ? (
          <p className="empty">Loading {kind}…</p>
        ) : !rows.length ? (
          <EmptyResults summary={summary} />
        ) : (
          <>
            <section className="chart-section">
              <div>
                <h2>{kind === "fitting" ? "Score distribution" : "Refinement comparison"}</h2>
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
                  {" · "}
                  <kbd>j</kbd>/<kbd>k</kbd> or <kbd>↓</kbd>/<kbd>↑</kbd> step through{" "}
                  {kind === "fitting" ? "solutions" : "members"}
                </span>
              </div>
              <ResultsTable
                items={selectedRows.slice((page - 1) * pageSize, page * pageSize)}
                cols={columns}
                type={kind}
                sort={sort}
                desc={desc}
              />
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
                <button disabled={page === 1} onClick={() => navigate({ page: String(page - 1) })}>
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
    </>
  );
}
