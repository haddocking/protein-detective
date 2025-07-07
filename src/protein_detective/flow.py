"""Prefect flow for minimal protein detective workflow.


To run

```shell
uv sync --group prefect
uv run prefect server start
# In another terminal
uv run prefect config set PREFECT_RESULTS_PERSIST_BY_DEFAULT=true
uv run prefect config set PREFECT_TASK_RUNNER_THREAD_POOL_MAX_WORKERS=6
uv run python3 src/protein_detective/flow.py
```

"""

from collections.abc import Mapping
from dataclasses import dataclass

import duckdb
import pandas as pd
from prefect import flow, get_run_logger, task
from prefect.assets import materialize
from prefect_dask.task_runners import DaskTaskRunner

from protein_detective.alphafold import AlphaFoldEntry, Path
from protein_detective.alphafold.density import DensityFilterQuery, filter_on_density
from protein_detective.db import PowerfitOptions
from protein_detective.pdbe.fetch import fetch as pdbe_fetch
from protein_detective.pdbe.io import ProteinPdbRow, SingleChainQuery, write_single_chain_pdb_files
from protein_detective.powerfit.run import run
from protein_detective.powerfit.solution import fit_model
from protein_detective.uniprot import PdbResult, Query, search4af, search4pdb, search4uniprot
from protein_detective.workflow import af_fetch


@task
def search_uniprot(query: Query, limit: int) -> set[str]:
    return search4uniprot(query, limit)


@task
def pdb_of_uniprot(uniprot_accessions: set[str], limit: int) -> dict[str, set[PdbResult]]:
    return search4pdb(uniprot_accessions, limit=limit)


@task
def af_of_uniprot(uniprot_accessions: set[str], limit: int):
    return search4af(uniprot_accessions, limit=limit)


@materialize("file://./pdbe_files")
def pdbe_fetch_task(pdb_results: dict[str, set[PdbResult]]) -> Mapping[str, Path]:
    pdb_ids = set()
    for results in pdb_results.values():
        pdb_ids.update(result.id for result in results)

    save_dir = Path("pdbe_files")
    save_dir.mkdir(parents=True, exist_ok=True)

    return pdbe_fetch(pdb_ids, save_dir)


@materialize("file://./alphafold_files")
def af_fetch_task(af_results: dict[str, set[str]]) -> list[AlphaFoldEntry]:
    af_ids = set()
    for results in af_results.values():
        af_ids.update(results)

    save_dir = Path("alphafold_files")
    save_dir.mkdir(parents=True, exist_ok=True)

    return af_fetch(af_ids, save_dir)


@materialize("file://./filtered_pdbs")
def filter_pdbs_task(
    pdb_results: dict[str, set[PdbResult]],
    pdb_files: Mapping[str, Path],
    query: SingleChainQuery,
) -> list[Path]:
    session_dir = Path(".")
    single_chain_dir = Path("filtered_pdbs")
    single_chain_dir.mkdir(parents=True, exist_ok=True)

    proteinpdbs = []
    for uniprot_acc, pdb_result_set in pdb_results.items():
        for pdb_result in pdb_result_set:
            row = ProteinPdbRow(
                id=pdb_result.id,
                uniprot_chains=pdb_result.uniprot_chains,
                uniprot_acc=uniprot_acc,
                mmcif_file=pdb_files.get(pdb_result.id, None),
            )
            proteinpdbs.append(row)

    results = write_single_chain_pdb_files(
        proteinpdbs,
        session_dir,
        single_chain_dir,
        query,
    )

    return [result.output_file for result in results if result.passed and result.output_file]


@materialize("file://./filtered_afs")
def filter_af_task(
    af_entries: list[AlphaFoldEntry],
    query: DensityFilterQuery,
):
    density_filtered_dir = Path("filtered_afs")
    density_filtered_dir.mkdir(parents=True, exist_ok=True)

    af_files = [entry.pdb_file for entry in af_entries if entry.pdb_file is not None]
    return filter_on_density(af_files, query, density_filtered_dir)


@task
def fetch_and_filter_af(dquery, uniprot_accessions, limit: int):
    af_results = af_of_uniprot(uniprot_accessions, limit)
    af_entries = af_fetch_task(af_results)
    return filter_af_task(af_entries, dquery)


@task
def fetch_and_filter_pdb_files(pdb_query, uniprot_accessions, limit: int):
    pdb_results = pdb_of_uniprot(uniprot_accessions, limit)
    pdb_files = pdbe_fetch_task(pdb_results)
    return filter_pdbs_task(pdb_results, pdb_files, pdb_query)


@dataclass
class PowerfitRun:
    model_file: Path
    options: PowerfitOptions
    result_dir: Path


@task
def powerfit_run_task(
    arg: PowerfitRun,
):
    model_file = arg.model_file
    options = arg.options
    result_dir = arg.result_dir
    logger = get_run_logger()
    if (result_dir).exists():
        logger.info(f"Skipping PowerFit run for {model_file}, result directory already exists: {result_dir}")
        return (model_file, result_dir)
    logger.info(f"Running PowerFit on {model_file} in {result_dir}")
    with options.target.open("rb") as density_map:
        run(density_map, model_file, result_dir, options)
    logger.info(f"PowerFit run completed for {model_file}, results saved in {result_dir}")
    return (model_file, result_dir)


@materialize("file://./powerfit_results")
def run_powerfit_on_models(
    powerfit_options: PowerfitOptions, filtered_pdb_files, filtered_af_files
) -> dict[Path, Path]:
    logger = get_run_logger()

    model_files = list(filtered_pdb_files) + list(filtered_af_files)

    logger.info(f"Running PowerFit on {len(model_files)} models with options: {powerfit_options}")
    root_result_dir = Path("powerfit_results")
    root_result_dir.mkdir(parents=True, exist_ok=True)

    runs = []
    for model_file in model_files:
        result_dir = root_result_dir / model_file.stem
        runs.append(
            PowerfitRun(
                model_file=model_file,
                result_dir=result_dir,
                options=powerfit_options,
            )
        )
    result_dirs = powerfit_run_task.map(runs).result()

    return dict(result_dirs)


@task
def powerfit_report_task(result_dirs: dict[Path, Path]) -> pd.DataFrame:
    logger = get_run_logger()
    logger.info(f"Generating PowerFit report from {len(result_dirs)} models")
    root_result_dir = Path("powerfit_results")

    data = []
    for model_file, result_dir in result_dirs.items():
        data.append({"model_file": model_file, "result_dir": result_dir})

    model2result = pd.DataFrame(data)  # noqa: F841 -- is used by DuckDB query
    query = """
        SELECT
            model_file,
            parse_dirpath(filename) AS result_dir,
            filename AS solutions_file,
            rank, cc, fishz, relz,
            [x,y,z]::FLOAT[3] AS translation,
            [a11, a12, a13, a21, a22, a23, a31, a32, a33]::FLOAT[9] AS rotation,
        FROM
          read_csv(
            ? || '/*/solutions.out',
            filename=True, normalize_names=True
          )
          JOIN model2result
          ON model2result.result_dir = parse_dirpath(filename)
        ORDER BY cc DESC
    """
    return duckdb.sql(query, params=(str(root_result_dir),)).df()


@task
def fit_model_task(item):
    _index, row = item
    unfitted_model_file = row["model_file"]
    translation = row["translation"]
    rotation = row["rotation"].reshape(3, 3)
    rank = row["rank"]
    solutions_file = row["solutions_file"]
    fitted_model_file = Path(solutions_file).parent / f"fit_{rank}.pdb"

    logger = get_run_logger()
    if fitted_model_file.exists():
        logger.info(f"Skipping creation of {fitted_model_file}. Already exists.")
    else:
        fit_model(unfitted_model_file, translation, rotation, fitted_model_file)

    return {
        "unfitted_model_file": unfitted_model_file,
        "fitted_model_file": fitted_model_file,
        "rank": rank,
    }


@task
def fit_models_task(solutions: pd.DataFrame, top: int) -> pd.DataFrame:
    logger = get_run_logger()
    logger.info(f"Fitting top {top} models")

    fitted_files = fit_model_task.map(solutions.head(top).iterrows())

    return pd.DataFrame(
        fitted_files.result(),
    )


@materialize("file://./powerfit_results/solutions.duckdb")
def save_powerfit_results(solutions: pd.DataFrame, fitted_solutions: pd.DataFrame):  # noqa: ARG001 - used by DuckDB query
    fn = Path("powerfit_results/solutions.duckdb")
    with duckdb.connect(fn) as con:
        con.execute("CREATE TABLE IF NOT EXISTS solutions AS SELECT * FROM solutions")
        con.execute("CREATE TABLE IF NOT EXISTS fitted_solutions AS SELECT * FROM fitted_solutions")


runner = DaskTaskRunner(cluster_kwargs={"n_workers": 6, "threads_per_worker": 1})

@flow(task_runner=runner)  # type: ignore[arg-type]
def my_workflow(
    query: Query,
    limit: int,
    pdb_query: SingleChainQuery,
    dquery: DensityFilterQuery,
    powerfit_options: PowerfitOptions,
    top: int,
):
    uniprot_accessions = search_uniprot(query, limit)

    filtered_pdb_files = fetch_and_filter_pdb_files.submit(pdb_query, uniprot_accessions, limit)
    filtered_af_files = fetch_and_filter_af.submit(dquery, uniprot_accessions, limit)

    powerfit_result_dirs: dict[Path, Path] | None = run_powerfit_on_models(powerfit_options, filtered_pdb_files, filtered_af_files)
    if powerfit_result_dirs is None:
        msg = "No PowerFit results found. Check your queries and input data."
        raise ValueError(msg)

    solutions = powerfit_report_task(powerfit_result_dirs)
    fitted_solutions = fit_models_task(solutions, top=top)

    save_powerfit_results(solutions, fitted_solutions)


if __name__ == "__main__":
    query = Query(
        taxon_id="9606",
        reviewed=True,
        subcellular_location_uniprot="nucleus",
        subcellular_location_go="GO:0005634",  # Cellular component - Nucleus
        molecular_function_go="GO:0003677",  # Molecular function - DNA binding
    )
    pdb_query = SingleChainQuery(
        min_residues=100,
        max_residues=500,
    )
    dquery = DensityFilterQuery(
        confidence=70.0,
        min_threshold=100,
        max_threshold=500,
    )
    powerfit_options = PowerfitOptions(
        target=Path("../powerfit-tutorial/ribosome-KsgA.map"),
        resolution=13,
        angle=20,
        laplace=True,
        nproc=1,
        show_progress=False,
    )
    top = 10
    my_workflow(query, 100, pdb_query, dquery, powerfit_options, top=top)
