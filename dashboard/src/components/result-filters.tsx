import { clusterKey, display, labels, type Row } from "../data";
import { type ResultKind } from "../navigation";
import { useDashboardNavigation } from "../hooks/use-dashboard-navigation";

function clusterLabel(r: Row | undefined) {
  return r
    ? `${display(r.refine_run_id)} / ${display(r.structure)} · fitted ${display(r.fitted_rank)} · cluster ${display(r.cluster_id)}`
    : "Unknown cluster";
}

export function ResultFilters({
  kind,
  rows,
  limit,
}: {
  kind: ResultKind;
  rows: Row[];
  limit: string;
}) {
  const { p, navigate } = useDashboardNavigation();

  const activeFilters: string[] = [];
  if (limit === "1") {
    let bestLabel = "Best HADDOCK score";
    if (kind === "fitting") bestLabel = "Best only";
    activeFilters.push(`"${bestLabel}"`);
  } else if (limit !== "all") {
    activeFilters.push(`"Top ${limit}"`);
  }

  const search = p.get("q");
  if (search) activeFilters.push(`Search: "${search}"`);

  const filterKeys = ["source", "powerfit_run_id"];
  if (kind === "refinements") filterKeys.push("refine_run_id", "cluster");
  for (const name of filterKeys) {
    const value = p.get(name);
    if (!value) continue;
    let label = labels[name];
    let text = value;
    if (name === "cluster") {
      label = "Cluster";
      text = clusterLabel(rows.find((row) => clusterKey(row) === value));
    }
    activeFilters.push(`${label}: "${text}"`);
  }

  let filterSummary = "(no active filters)";
  if (activeFilters.length === 1) filterSummary = `(active filter: ${activeFilters[0]})`;
  else if (activeFilters.length > 1)
    filterSummary = `(active filters: ${activeFilters.join(", ")})`;

  return (
    <details className="result-filters">
      <summary>
        <span>Search and filters</span>
        <span className="filter-summary" title={filterSummary}>
          {filterSummary}
        </span>
      </summary>
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
                    .map((r) => {
                      if (k === "cluster") return clusterKey(r);
                      if (typeof r[k] === "string") return r[k];
                      return "";
                    })
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
            : "Members by HADDOCK rank per cluster / input / run"}
          <select value={limit} onChange={(e) => navigate({ top: e.target.value, page: "1" })}>
            <option value="1">{kind === "fitting" ? "Best only" : "Best HADDOCK score"}</option>
            <option value="3">Top 3</option>
            <option value="5">Top 5</option>
            <option value="10">Top 10</option>
            <option value="all">{kind === "fitting" ? "All solutions" : "All members"}</option>
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
    </details>
  );
}
