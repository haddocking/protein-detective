import React from "react";
import { Link } from "@tanstack/react-router";
import { display, key, labels, type Dataset, type Row } from "../data";
import { useSession } from "../hooks/use-session-data";
import { useDashboardNavigation } from "../hooks/use-dashboard-navigation";
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

export function ResultDetails({
  selected,
  selectedKind,
  candidate,
  accessions,
}: {
  selected: Row;
  selectedKind: string;
  candidate: Row | undefined;
  accessions: string[];
}) {
  const { data } = useSession();
  const { navigate, select } = useDashboardNavigation();
  return (
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
              String(selected.structure_id ?? candidate?.structure_id ?? selected.structure).slice(
                0,
                4,
              )
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
      {(["fitting", "refinements"] as const).map((type) => {
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
                <button className="related" key={key(r)} onClick={() => select(r, type)}>
                  {display(r.powerfit_run_id)} ·{" "}
                  {type === "fitting"
                    ? `rank ${display(r.rank)} · CC ${display(r.cc)}`
                    : `${display(r.refine_run_id)} · score ${display(r.refined_score)}`}
                </button>
              ))}
              {related.length > 20 && (
                <Link to={`/${type}`} search={{ q: String(selected.structure) }}>
                  See all related results →
                </Link>
              )}
            </div>
          )
        );
      })}
    </div>
  );
}
