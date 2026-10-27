import { PageTitle } from "../components/page-title";
import { Histogram, Scatter } from "../charts";
import { EmptyResults } from "../components/empty-results";
import { ResultFilters } from "../components/result-filters";
import { ResultsTable } from "../components/results-table";
import { useSession } from "../hooks/use-session-data";
import { useDashboardNavigation } from "../hooks/use-dashboard-navigation";
import { useResults } from "../hooks/use-results";
import { type ResultKind } from "../navigation";
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
  } = useResults(kind);
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
                <h2>
                  {kind === "fitting" ? "PowerFit score distribution" : "CAPRI score comparison"}
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
                      <option value="cc">PowerFit CC</option>
                      <option value="fishz">PowerFit Fisher z</option>
                      <option value="relative_z">PowerFit relative z</option>
                    </select>
                  </label>
                ) : (
                  <p>
                    Points below the diagonal have a lower (better) CAPRI score.
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
                    ? "Higher PowerFit CC is better"
                    : "Changes = after − before. PowerFit CC: positive is better. CAPRI score: negative is better."}
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
