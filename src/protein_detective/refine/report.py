"""Report final members of every refinement cluster using session metadata."""

import warnings
from pathlib import Path

import duckdb
import pandas as pd

from protein_detective.meta import capri_as_duckdb_ddl
from protein_detective.refine import LAST_CAPRIEVAL_MODULE

REPORT_QUERY = """
WITH members AS (
    SELECT *,
        split_part(refine_run_dir, '/', 2) AS refine_run_id,
        split_part(refine_run_dir, '/', 3) AS powerfit_run_id,
        split_part(refine_run_dir, '/', 4) AS structure,
        concat_ws('/', 'powerfit', split_part(refine_run_dir, '/', 3),
            split_part(refine_run_dir, '/', 4), split_part(refine_run_dir, '/', 5)) AS fitted_model,
        modelcluster_ranking AS model_rank
    FROM refinements_capri_ss
    WHERE score IS NOT NULL
)
SELECT m.refine_run_id, m.powerfit_run_id, m.structure,
    fm.rank AS fitted_rank,
    coalesce(fs.uniprot_accessions, '') AS uniprot_accessions,
    m.cluster_id,
    cl.cluster_rank AS cluster_rank,
    cl.n AS population,
    cl.under_eval,
    cl.score AS cluster_score,
    cl.score_std AS cluster_score_std,
    m.model_rank,
    m.score AS model_score,
    m.model AS model_path,
    m.fitted_model, m.refine_run_dir
FROM members m
-- Repeated fitting appends duplicate rows to fitted_models.csv.
LEFT JOIN (SELECT DISTINCT * FROM fitted_models) fm ON m.fitted_model = fm.fitted_model_file
LEFT JOIN fittable_structures fs ON m.structure = fs.structure
LEFT JOIN refinements_capri_clt cl
    ON m.refine_run_dir = cl.refine_run_dir AND m.cluster_id = cl.cluster_id
WHERE NOT $group_by_structure OR m.model_rank <= $top
ORDER BY m.refine_run_id, m.powerfit_run_id, m.structure, fitted_rank,
    cluster_rank, m.cluster_id, model_rank, model_path
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


def _find_model_runs(session_dir: Path, refine_run_id: str | None = None) -> tuple[set[str], list[Path]]:
    """Find model run directories and those with both final CAPRI files.

    Args:
        session_dir: Absolute session directory containing refinement runs.
        refine_run_id: Independent refinement run to select; defaults to all runs.

    Returns:
        Session-relative model run paths and sorted absolute paths to model runs
        containing both capri_ss.tsv and capri_clt.tsv in LAST_CAPRIEVAL_MODULE.

    Raises:
        ValueError: The requested refinement run directory is unknown or no
            model runs contain both final CAPRI files.
    """
    run_dirs = sorted(path for path in (session_dir / "refine").glob("*") if path.is_dir())

    if refine_run_id is not None:
        run_dirs = [path for path in run_dirs if path.name == refine_run_id]
        if not run_dirs:
            msg = f"Unknown refinement run ID: {refine_run_id}"
            raise ValueError(msg)

    model_runs = {
        str(path.relative_to(session_dir)) for run_dir in run_dirs for path in run_dir.glob("*/*/*") if path.is_dir()
    }

    complete_runs = [
        session_dir / run
        for run in sorted(model_runs)
        if all(
            (session_dir / run / LAST_CAPRIEVAL_MODULE / name).is_file() for name in ("capri_ss.tsv", "capri_clt.tsv")
        )
    ]

    if not complete_runs:
        msg = f"No complete refinement results found in {session_dir}"
        raise ValueError(msg)

    return model_runs, complete_runs


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
    Rank by model_score ascending and keep the usual report order for score ties.
    Reporting does not change the workflow's top_clusters or top_models options.

    Include UniProt accessions, fitted rank, source and refinement run IDs,
    cluster summaries, and individual model scores in separate columns.
    CSV columns model_path, fitted_model and refine_run_dir are relative to the
    current working directory. Model paths reference compressed PDBs produced
    by HADDOCK cleanup with clean = True.

    Require powerfit/fitted_models.csv and powerfit/fittable_structures.csv to
    contain data rows. Missing metadata rows leave accessions empty without
    dropping members. Discover final results directly in 8_caprieval and join
    PowerFit CSVs in memory; no IO index or persistent database is needed.

    Exclude incomplete model runs and emit a UserWarning listing them, shown
    on stderr by default. Raise an error if no complete results are available.
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
    - cluster_id: capri_ss.tsv column cluster_id; missing IDs become '-' in CSV.
    - cluster_rank: capri_clt.tsv column cluster_rank.
    - population: capri_clt.tsv column n, before report member selection.
    - under_eval: capri_clt.tsv column under_eval.
    - cluster_score: capri_clt.tsv column score.
    - cluster_score_std: capri_clt.tsv column score_std.
    - model_rank: capri_ss.tsv column model-cluster_ranking; starts at 1.
    - model_score: capri_ss.tsv column score.
    - model_path: capri_ss.tsv column model, resolved relative to 8_caprieval
      and printed relative to the current working directory with a .pdb.gz
      extension, as produced by HADDOCK cleanup.
    - fitted_model: source input path derived as
      powerfit/{powerfit_run_id}/{structure}/{fitted_model_name} from the refinement
      directory layout, matched to fitted_models.csv column fitted_model_file.
    - refine_run_dir: model run directory containing
      8_caprieval, discovered as
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
        Member report DataFrame with session-relative paths. Model paths
        reference compressed PDBs produced by HADDOCK cleanup. The CLI converts
        the three path columns to paths relative to the current working directory.
        Model and cluster summary scores are kept in separate columns.

    Raises:
        FileNotFoundError: A required PowerFit CSV is missing.
        ValueError: top is not positive, the requested refinement run is unknown,
            a required PowerFit CSV is empty, or no complete results are available.
    """
    if top < 1:
        msg = "top must be a positive integer"
        raise ValueError(msg)

    session_dir = session_dir.resolve()
    model_runs, complete_runs = _find_model_runs(session_dir, refine_run_id)

    with duckdb.connect() as con:
        _ensure_metadata(con, session_dir)

        for statement, params in capri_as_duckdb_ddl(session_dir, model_runs=complete_runs):
            con.execute(statement, params)

        results = con.execute(REPORT_QUERY, {"top": top, "group_by_structure": group_by_structure}).df()

        if results.empty:
            msg = f"No complete refinement results found in {session_dir}"
            raise ValueError(msg)

    incomplete = sorted(model_runs - set(results["refine_run_dir"]))
    if incomplete:
        warnings.warn(
            f"Excluded {len(incomplete)} incomplete refinement model run(s):\n" + "\n".join(incomplete),
            stacklevel=2,
        )

    if not group_by_structure:
        results = results.sort_values("model_score", kind="stable").head(top)

    results["model_path"] = [
        _resolve_model_path(session_dir, run, model)
        for run, model in zip(results["refine_run_dir"], results["model_path"], strict=True)
    ]

    return results


def _resolve_model_path(session_dir: Path, run: str, model: str) -> str:
    """Resolve a CAPRI member path to the compressed PDB produced by HADDOCK cleanup.

    Args:
        session_dir: Absolute session directory.
        run: Session-relative model-level HADDOCK run directory.
        model: Uncompressed PDB path recorded relative to the final CAPRI directory.

    Returns:
        Session-relative .pdb.gz path, assuming the workflow uses clean = True.
    """
    path = (session_dir / run / LAST_CAPRIEVAL_MODULE / model).with_suffix(".pdb.gz").resolve()
    return str(path.relative_to(session_dir))
