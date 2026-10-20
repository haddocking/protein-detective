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
  return (
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
                    k === "cluster" ? clusterKey(r) : typeof r[k] === "string" ? r[k] : "",
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
        {kind === "fitting" ? "Solutions per structure / run" : "Members per cluster / input / run"}
        <select value={limit} onChange={(e) => navigate({ top: e.target.value, page: "1" })}>
          <option value="1">Best only</option>
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
  );
}
