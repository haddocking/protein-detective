import { PageTitle } from "../components/page-title";
import { Link } from "@tanstack/react-router";
import { filterRows, grouped, sorted, positivePage, tablePageSize } from "../data";
import { ResultsTable } from "../components/results-table";
import { useSession } from "../hooks/use-session-data";
import { useDashboardNavigation } from "../hooks/use-dashboard-navigation";
export function OverviewPage() {
  const { data, summary } = useSession();
  const { p, navigate } = useDashboardNavigation();
  const candidates = filterRows(data.candidates ?? [], p);
  const pageSize = tablePageSize(p.get("size"));
  const page = Math.min(
    positivePage(p.get("page")),
    Math.max(1, Math.ceil(candidates.length / pageSize)),
  );
  return (
    <>
      <PageTitle />
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
            <ResultsTable
              items={sorted(grouped(data.fitting, "fitting", "1"), "cc", true).slice(0, 5)}
              cols={["structure", "powerfit_run_id", "cc"]}
              type="fitting"
            />
          ) : (
            <p>Loading fitting results…</p>
          )}
          <Link to="/fitting" search={{}}>
            Explore fitting results →
          </Link>
        </section>
        <section>
          <h2>Lowest refinement scores</h2>
          {data.refinements ? (
            <ResultsTable
              items={sorted(
                grouped(data.refinements, "refinements", "1"),
                "refined_score",
                false,
              ).slice(0, 5)}
              cols={["structure", "refine_run_id", "refined_score"]}
              type="refinements"
            />
          ) : (
            <p>Loading refinement results…</p>
          )}
          <Link to="/refinements" search={{}}>
            Explore refinements →
          </Link>
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
          <ResultsTable
            items={candidates.slice((page - 1) * pageSize, page * pageSize)}
            cols={[
              "structure",
              "uniprot_accessions",
              "source",
              "filtering_status",
              "rejection_reason",
            ]}
            type="candidates"
          />
        ) : (
          <p>Loading candidates…</p>
        )}
        <div className="pagination">
          <button disabled={page <= 1} onClick={() => navigate({ page: String(page - 1) })}>
            Previous
          </button>
          <span>
            Page {page} · {candidates.length} candidates
          </span>
          <button
            disabled={page * pageSize >= candidates.length}
            onClick={() => navigate({ page: String(page + 1) })}
          >
            Next
          </button>
        </div>
      </section>
    </>
  );
}
