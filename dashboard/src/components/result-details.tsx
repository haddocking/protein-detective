import React from "react";
import { Link } from "@tanstack/react-router";
import { display, key, labels, type Dataset, type Row } from "../data";
import { useSession } from "../hooks/use-session-data";
import { useDashboardNavigation } from "../hooks/use-dashboard-navigation";
import { useFittingNavigation, useRefinementsNavigation } from "../hooks/use-result-navigation";
const secondaryScoreFields = [
  "before_cc",
  "cc_change",
  "before_fishz",
  "after_fishz",
  "before_relative_z",
  "after_relative_z",
  "baseline_score",
  "score_change",
  "cluster_score",
  "cluster_score_std",
];

const detailsFields = new Set([
  ...secondaryScoreFields,
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
  "fitted_cc",
  "cluster_id",
  "cluster_rank",
  "member_rank",
  "refined_score",
  "after_cc",
  "population",
]);

export function ResultDetails({
  selected,
  resultLabel,
  viewerMessage,
  candidate,
  accessions,
}: {
  selected: Row;
  resultLabel: string;
  viewerMessage: string | null;
  candidate: Row | undefined;
  accessions: string[];
}) {
  const { data } = useSession();
  const { navigate } = useDashboardNavigation();
  const fittingNavigation = useFittingNavigation();
  const refinementsNavigation = useRefinementsNavigation();
  const metadata = { ...candidate, ...selected };
  const fields = Object.entries(metadata).filter(([name]) => !secondaryScoreFields.includes(name));
  const ccIndex = fields.findIndex(([name]) => name === "after_cc");
  if (ccIndex >= 0) {
    const [cc] = fields.splice(ccIndex, 1);
    const scoreIndex = fields.findIndex(([name]) => name === "refined_score");
    fields.splice(scoreIndex >= 0 ? scoreIndex : fields.length, 0, cc);
  }
  for (const field of secondaryScoreFields) {
    if (metadata[field] != null) fields.push([field, metadata[field]]);
  }
  return (
    <div className="details-content">
      <p className="eyebrow">{resultLabel}</p>
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
        viewerMessage && <p className="notice">{viewerMessage}</p>
      )}
      <dl>
        {fields
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
      {[fittingNavigation, refinementsNavigation].map(({ kind: type, select }) => {
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
                <button className="related" key={key(r)} onClick={() => select(r)}>
                  {display(r.powerfit_run_id)} ·{" "}
                  {type === "fitting"
                    ? `rank ${display(r.rank)} · PowerFit CC ${display(r.cc)}`
                    : `${display(r.refine_run_id)} · HADDOCK score ${display(r.refined_score)}`}
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
