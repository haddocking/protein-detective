"""Report final members of every refinement cluster using session metadata."""

from pathlib import Path

import duckdb
import pandas as pd

from protein_detective.meta import (
    refinements_baseline,
    refinements_capri_clt_as_duckdb_ddl,
    refinements_capri_ss_as_duckdb_ddl,
    refinements_io_as_duckdb_ddl,
    refinements_runs_as_duckdb_ddl,
)

REPORT_QUERY = """
SELECT
    m.refine_run_id,
    m.powerfit_run_id,
    m.unfitted_structure AS structure,
    fm.rank AS fitted_rank,
    fs.uniprot_accessions,
    m.cluster_id,
    cl.cluster_rank,
    cl.n AS population,
    cl.under_eval,
    cl.score AS cluster_score,
    cl.score_std AS cluster_score_std,
    m.modelcluster_ranking,
    u.score AS unrefined_score,
    m.score AS refined_score,
    concat_ws('/', $session_prefix, m.refined_structure_path) AS refined_structure_path,
    concat_ws('/', $session_prefix, fm.fitted_model_file) AS fitted_model,
    concat_ws('/', $session_prefix, m.refine_run_dir) AS refine_run_dir
FROM refinements_capri_ss m
JOIN refinements_runs r USING (refine_run_id)
JOIN refinements_io io USING (refine_run_dir)
-- Repeated fitting appends duplicate rows to fitted_models.csv.
JOIN (SELECT DISTINCT * FROM fitted_models) fm ON io.fitted_model = fm.fitted_model_file
JOIN fittable_structures fs ON m.unfitted_structure = fs.structure
JOIN refinements_capri_clt cl USING (refine_run_dir, cluster_id)
JOIN refinements_baseline u USING (refine_run_dir)
WHERE m.score IS NOT NULL
    AND ($refine_run_id IS NULL OR m.refine_run_id = $refine_run_id)
    AND (NOT $group_by_structure OR modelcluster_ranking <= $top)
ORDER BY
    m.refine_run_id,
    m.powerfit_run_id,
    structure,
    fitted_rank,
    cluster_rank,
    m.cluster_id,
    modelcluster_ranking,
    refined_structure_path
"""


def _ensure_metadata(con: duckdb.DuckDBPyConnection, session_dir: Path) -> None:
    """Load the required PowerFit CSVs and reject missing or empty files.

    Args:
        con: In-memory connection in which to load the PowerFit tables.
        session_dir: Session directory containing the PowerFit CSVs.

    Raises:
        FileNotFoundError: A required PowerFit CSV is missing.
        ValueError: A required PowerFit CSV is empty or contains only a header.
    """
    fitted_models_csv = session_dir / "powerfit/fitted_models.csv"
    fittable_structures_csv = session_dir / "powerfit/fittable_structures.csv"

    if not fitted_models_csv.is_file():
        msg = f"Missing PowerFit metadata file: {fitted_models_csv}"
        raise FileNotFoundError(msg)

    if not fittable_structures_csv.is_file():
        msg = f"Missing PowerFit metadata file: {fittable_structures_csv}"
        raise FileNotFoundError(msg)

    if fitted_models_csv.stat().st_size == 0:
        msg = f"Empty PowerFit metadata file: {fitted_models_csv}"
        raise ValueError(msg)

    if fittable_structures_csv.stat().st_size == 0:
        msg = f"Empty PowerFit metadata file: {fittable_structures_csv}"
        raise ValueError(msg)

    con.read_csv(str(fitted_models_csv), header=True).create("fitted_models")
    con.read_csv(str(fittable_structures_csv), header=True).create("fittable_structures")

    if con.table("fitted_models").limit(1).fetchone() is None:
        msg = f"Empty PowerFit metadata file: {fitted_models_csv}"
        raise ValueError(msg)

    if con.table("fittable_structures").limit(1).fetchone() is None:
        msg = f"Empty PowerFit metadata file: {fittable_structures_csv}"
        raise ValueError(msg)


def refinement_report(
    session_dir: Path,
    refine_run_id: str | None = None,
    top: int = 1,
    *,
    group_by_structure: bool = True,
) -> pd.DataFrame:
    """Report the best final members of every cluster for each fitted input.

    By default, select the best N final-stage members from every cluster, independently for
    each fitted input and refinement run, using CAPRI's model-cluster_ranking.
    The generated workflow clusters every final model, including isolated
    models in single-member clusters.
    With --no-group-by-structure, select the best N models overall across all
    fitted inputs and selected refinement runs.
    Rank by refined_score ascending and keep the usual report order for score ties.
    Reporting does not change the workflow's top_clusters or top_models options.

    Include UniProt accessions, fitted rank, source and refinement run IDs,
    cluster summaries, and individual model scores in separate columns.
    CSV columns refined_structure_path, fitted_model and refine_run_dir are prefixed with session_dir.
    Relative session paths remain relative to the current working directory; absolute session paths remain absolute.
    Model paths reference compressed PDBs produced by HADDOCK cleanup with clean = True.

    Require powerfit/fitted_models.csv and powerfit/fittable_structures.csv to
    contain data rows matching each refined input. Discover final results directly in refinement/8_caprieval and join
    PowerFit CSVs in memory. Read recorded refinement runs from RO-Crate and input mappings from refine/*/io.csv.
    No persistent database is needed.

    Run the report after all refinement runs have completed, including baseline scoring.
    The CLI writes CSV to stdout or the --output path. Use --refine-run-id to select one refinement
    run, independently of the source PowerFit run.

    Report columns and their sources (CAPRI files are in each model run's
    last caprieval directory):

    - refine_run_id: refinement ID from the refine/{refine_run_id} directory name.
    - powerfit_run_id: source fitting ID from the next directory component.
    - structure: source structure directory name, joined to
      powerfit/fittable_structures.csv column structure.
    - fitted_rank: powerfit/fitted_models.csv column rank, matched through
      its fitted_model_file column.
    - uniprot_accessions: powerfit/fittable_structures.csv column
      uniprot_accessions, joined by structure; accessions are colon-separated.
    - cluster_id: capri_ss.tsv column cluster_id.
    - cluster_rank: capri_clt.tsv column cluster_rank.
    - population: capri_clt.tsv column n, before report member selection.
    - under_eval: capri_clt.tsv column under_eval.
    - cluster_score: capri_clt.tsv column score.
    - cluster_score_std: capri_clt.tsv column score_std.
    - modelcluster_ranking: capri_ss.tsv column modelcluster_ranking.
    - refined_score: capri_ss.tsv column score.
    - unrefined_score: CAPRI score of unrefined structure and the fixed structure.
    - refined_structure_path: corrected (+.gz) capri_ss.tsv column model, prefixed with session_dir.
    - fitted_model: source input path from refine/*/io.csv column fitted_model,
      matched to fitted_models.csv column fitted_model_file.
    - refine_run_dir: model run directory containing
      baseline and refinement/8_caprieval, discovered as
      refine/{refine_run_id}/{powerfit_run_id}/{structure}/{fitted_model_name}.

    Cluster summary columns are joined from capri_clt.tsv using cluster_id
    within the same model run, and are repeated for each selected member.
    Missing values are empty in CSV except cluster_id, which is '-'.

    Args:
        session_dir: Session directory containing refinement results and PowerFit metadata.
        refine_run_id: Independent refinement run to select; defaults to all runs.
        top: Positive number of best members per cluster,
            or overall when grouping is disabled.
        group_by_structure: Keep selection per fitted input and cluster when True;
            select the best models overall when False.

    Returns:
        Member report DataFrame with paths prefixed with the supplied session_dir.
        Model paths reference compressed PDBs produced by HADDOCK cleanup.
        Model and cluster summary scores are kept in separate columns.

    Raises:
        FileNotFoundError: A required PowerFit CSV is missing.
        ValueError: top is not positive, the requested refinement run is unknown.
    """
    if top < 1:
        msg = "top must be a positive integer"
        raise ValueError(msg)

    session_prefix = str(session_dir)
    session_dir = session_dir.resolve()

    with duckdb.connect() as con:
        _ensure_metadata(con, session_dir)
        for loader in (
            refinements_runs_as_duckdb_ddl,
            refinements_io_as_duckdb_ddl,
            refinements_capri_ss_as_duckdb_ddl,
            refinements_capri_clt_as_duckdb_ddl,
            refinements_baseline,
        ):
            for statement, params in loader(session_dir):
                con.execute(statement, params)

        if (
            refine_run_id is not None
            and con.execute(
                "SELECT 1 FROM refinements_runs WHERE refine_run_id = $run_id", {"run_id": refine_run_id}
            ).fetchone()
            is None
        ):
            msg = f"Unknown refinement run ID: {refine_run_id}"
            raise ValueError(msg)

        results = con.execute(
            REPORT_QUERY,
            {
                "top": top,
                "group_by_structure": group_by_structure,
                "refine_run_id": refine_run_id,
                "session_prefix": session_prefix,
            },
        ).df()

    if not group_by_structure:
        results = results.sort_values("refined_score", kind="stable").head(top)

    return results
