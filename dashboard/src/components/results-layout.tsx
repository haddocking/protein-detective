import { PanelHelp } from "./panel-help";
import { PageTitle } from "./page-title";
import { EmptyResults } from "./empty-results";
import { ResultFilters } from "./result-filters";
import { ResultsTable } from "./results-table";
import { useSession } from "../hooks/use-session-data";
import { type Results } from "../hooks/use-results";
import { type ResultKind } from "../navigation";
import { useEffect, useRef, type ReactNode } from "react";
import { key } from "../data";

export function ResultsLayout({
  kind,
  results,
  noun,
  scoreHint,
  beforeTable,
  children,
}: {
  kind: ResultKind;
  results: Results;
  noun: string;
  scoreHint: string;
  beforeTable?: ReactNode;
  children: ReactNode;
}) {
  const { data, summary } = useSession();
  const { p, navigate } = results.navigation;
  const { rows, columns, sort, desc, limit, selectedRows, pageSize, page, exportCsv, step } =
    results;

  // j/k or arrow keys step through results, unless typing or interacting with the viewer.
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.altKey || event.ctrlKey || event.metaKey || event.defaultPrevented) return;
      const target = event.target;
      if (
        target instanceof Element &&
        target.closest(
          "input, select, textarea, [contenteditable], .molecular-canvas, .panel-help-content",
        )
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

  let content: ReactNode;
  if (!data[kind]) {
    content = <p className="empty">Loading {kind}…</p>;
  } else if (!rows.length) {
    content = <EmptyResults summary={summary} />;
  } else {
    content = (
      <>
        {beforeTable}
        <section className="results-section">
          <PanelHelp label="Table controls">
            <p>
              <kbd>j</kbd>/<kbd>k</kbd> or <kbd>↓</kbd>/<kbd>↑</kbd> step through {noun}.
            </p>
            <p>Select a row to inspect its result. Select a column heading to sort.</p>
          </PanelHelp>
          <div className="section-heading">
            <h2>
              {selectedRows.length.toLocaleString()} {noun}
            </h2>
            <span className="muted">{scoreHint}</span>
          </div>
          <ResultsTable
            scrollSelected
            items={selectedRows.slice((page - 1) * pageSize, page * pageSize)}
            cols={columns}
            navigation={results.navigation}
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
        {children}
      </>
    );
  }

  return (
    <>
      <PageTitle>
        <button onClick={exportCsv} disabled={!selectedRows.length}>
          Export CSV ↓
        </button>
      </PageTitle>
      <>
        <ResultFilters kind={kind} rows={rows} limit={limit} />
        {content}
      </>
    </>
  );
}
