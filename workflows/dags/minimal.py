import logging
from collections.abc import Mapping
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from airflow.sdk import Asset, AssetAlias, dag, task

from protein_detective.alphafold import AlphaFoldEntry, Path
from protein_detective.alphafold.density import DensityFilterQuery, filter_on_density
from protein_detective.db import PowerfitOptions
from protein_detective.pdbe.fetch import fetch as pdbe_fetch
from protein_detective.pdbe.io import ProteinPdbRow, SingleChainQuery, write_single_chain_pdb_files
from protein_detective.powerfit.run import run
from protein_detective.powerfit.solution import fit_model
from protein_detective.uniprot import PdbResult, Query, search4af, search4pdb, search4uniprot
from protein_detective.workflow import af_fetch

logger = logging.getLogger(__name__)


@task(retries=3)
def search_uniprot(query: dict, limit: int) -> set[str]:
    uniprot_query = Query(**query)
    return search4uniprot(uniprot_query, limit)


@task(retries=3)
def pdb_of_uniprot(uniprot_accessions: set[str], limit: int) -> dict[str, set[PdbResult]]:
    return search4pdb(uniprot_accessions, limit=limit)


@task(retries=3)
def af_of_uniprot(uniprot_accessions: set[str], limit: int):
    return search4af(uniprot_accessions, limit=limit)


@task
def af_fetch_task(af_results: dict[str, set[str]], session_dir: str) -> list[AlphaFoldEntry]:
    af_ids = set()
    for results in af_results.values():
        af_ids.update(results)

    save_dir = Path(session_dir) / "alphafold_files"
    save_dir.mkdir(parents=True, exist_ok=True)

    fetched = af_fetch(af_ids, save_dir)
    for f in fetched:
        f.pdb_file = str(f.pdb_file) if f.pdb_file else None
    return fetched


@task
def filter_af_task(
    af_entries: list[AlphaFoldEntry],
    density_query: Mapping[str, float | int],
    session_dir: str,
):
    density_filtered_dir = Path(session_dir) / "filtered_afs"
    density_filtered_dir.mkdir(parents=True, exist_ok=True)

    af_files = [Path(entry.pdb_file) for entry in af_entries if entry.pdb_file is not None]
    query_obj = DensityFilterQuery(**density_query)
    filtered = list(filter_on_density(af_files, query_obj, density_filtered_dir))
    for f in filtered:
        f.pdb_file = str(f.pdb_file)
        f.density_filtered_file = str(f.density_filtered_file) if f.density_filtered_file else None
    return filtered


@task
def pdbe_fetch_task(pdb_results: dict[str, set[PdbResult]], session_dir: str) -> Mapping[str, Path]:
    pdb_ids = set()
    for results in pdb_results.values():
        pdb_ids.update(result.id for result in results)

    save_dir = Path(session_dir) / "pdbe_files"
    save_dir.mkdir(parents=True, exist_ok=True)

    fetched = pdbe_fetch(pdb_ids, save_dir)
    return {k: str(v) for k, v in fetched.items()}


@task
def filter_pdbs_task(
    pdb_results: dict[str, set[PdbResult]],
    pdb_files: Mapping[str, Path],
    pdb_query: Mapping[str, int],
    session_dir: str,
) -> list[Path]:
    session_path = Path(session_dir)
    single_chain_dir = Path(session_dir) / "filtered_pdbs"
    single_chain_dir.mkdir(parents=True, exist_ok=True)

    proteinpdbs = []
    for uniprot_acc, pdb_result_set in pdb_results.items():
        for pdb_result in pdb_result_set:
            row = ProteinPdbRow(
                id=pdb_result.id,
                uniprot_chains=pdb_result.uniprot_chains,
                uniprot_acc=uniprot_acc,
                mmcif_file=Path(pdb_files.get(pdb_result.id, None)),
            )
            proteinpdbs.append(row)

    query_obj = SingleChainQuery(**pdb_query)
    results = write_single_chain_pdb_files(
        proteinpdbs,
        session_path,
        single_chain_dir,
        query_obj,
    )

    return [str(result.output_file) for result in results if result.passed]


@task
def prep_powerfit(filtered_af_files, filtered_pdb_files) -> list[str]:
    return filtered_pdb_files + [f.density_filtered_file for f in filtered_af_files if f.density_filtered_file]


@task
def powerfit(options: dict, template: str, session_dir: str) -> tuple[str, str]:
    options_obj = PowerfitOptions(
        target=Path(options["target"]),
        resolution=options["resolution"],
        angle=options["angle"],
        laplace=options["laplace"],
    )
    logger.info(f"Running powerfit with options: {options_obj} and template: {template}")

    template = Path(template)
    root_result_dir = Path(session_dir) / "powerfit_results"
    root_result_dir.mkdir(parents=True, exist_ok=True)
    result_dir = root_result_dir / template.stem
    solutions = str(result_dir / "solutions.out")

    if not result_dir.exists():
        with options_obj.target.open("rb") as target_file:
            run(target_file, template, result_dir, options_obj)

    return str(template), solutions


@task
def score_report(solutions: list[tuple[str, str]], top: int) -> pd.DataFrame:
    solutions = list(solutions)
    solutions_files = [s[1] for s in solutions]

    data = [
        {
            "template_file": s[0],
            "result_dir": Path(s[1]).parent,
        }
        for s in solutions
    ]
    model2result = pd.DataFrame(data)  # noqa: F841 -- is used by DuckDB query

    query = """
        SELECT
            template_file,
            parse_dirpath(filename) AS result_dir,
            filename AS solutions_file,
            rank, cc, fishz, relz,
            [x,y,z]::FLOAT[3] AS translation,
            [a11, a12, a13, a21, a22, a23, a31, a32, a33]::FLOAT[9] AS rotation,
        FROM
        read_csv(
            ?,
            filename=True, normalize_names=True
        )
        JOIN model2result
        ON model2result.result_dir = parse_dirpath(filename)
        ORDER BY cc DESC
    """
    rows = duckdb.query(query, params=[solutions_files]).df().head(top).to_dict(orient="records")
    for r in rows:
        r["rotation"] = r["rotation"].reshape(3, 3).tolist()
        r["translation"] = r["translation"].tolist()
    return rows


@task(outlets=[AssetAlias("fitted-model-outputs")])
def fit_model_task(row: dict[str, Any], *, outlet_events):
    template_file = row["template_file"]
    translation = np.array(row["translation"])
    rotation = np.array(row["rotation"]).reshape(3, 3)
    rank = row["rank"]
    solutions_file = row["solutions_file"]
    fitted_model_file = Path(solutions_file).parent / f"fit_{rank}.pdb"

    if fitted_model_file.exists():
        logger.info(f"Skipping creation of {fitted_model_file}. Already exists.")
    else:
        fit_model(template_file, translation, rotation, fitted_model_file)

    outlet_events[AssetAlias("fitted-model-outputs")].add(
        Asset(f"file://{fitted_model_file}"), extra={"unfitted_model_file": template_file, "rank": rank}
    )

    return {
        "unfitted_model_file": template_file,
        "fitted_model_file": str(fitted_model_file),
        "rank": rank,
    }


@task(outlets=[AssetAlias("save-results-outputs")])
def save_results(scores, fitted_models, session_dir: str, *, outlet_events):
    session_path = Path(session_dir)
    scores_df = pd.DataFrame(scores)
    scores_df.to_csv(session_path / "scores.csv", index=False)
    fitted_models_df = pd.DataFrame(fitted_models)
    fitted_models_df.to_csv(session_path / "fitted_models.csv", index=False)

    outlet_events[AssetAlias("save-results-outputs")].add(Asset(f"file://{session_path / 'scores.csv'}"))
    outlet_events[AssetAlias("save-results-outputs")].add(Asset(f"file://{session_path / 'fitted_models.csv'}"))


default_uniprot_query = {
    "taxon_id": "9606",
    "reviewed": True,
    "subcellular_location_uniprot": "nucleus",
    "subcellular_location_go": "GO:0005634",  # Cellular component - Nucleus
    "molecular_function_go": "GO:0003677",  # Molecular function - DNA binding
}

default_pdb_query = {
    "min_residues": 100,
    "max_residues": 500,
}

default_density_query = {
    "confidence": 70.0,
    "min_threshold": 100,
    "max_threshold": 500,
}

default_powerfit_options = {
    "target": "../../powerfit-tutorial/ribosome-KsgA.map",
    "resolution": 13,
    "angle": 20,
    "laplace": True,
}


@dag(
    "protein_detective_minimal_workflow",
    params={
        "uniprot_query": default_uniprot_query,
        "pdb_query": default_pdb_query,
        "density_query": default_density_query,
        "powerfit_options": default_powerfit_options,
    },
)
def minimal_workflow(
    session_dir: str = "session1",
    uniprot_query: Mapping[str, str] = default_uniprot_query,
    pdb_query: Mapping[str, int] = default_pdb_query,
    density_query: Mapping[str, float] = default_density_query,
    powerfit_options: dict = default_powerfit_options,
    limit: int = 100,
    top: int = 10,
):
    uniprot_accessions = search_uniprot(uniprot_query, limit)

    pdb_results = pdb_of_uniprot(uniprot_accessions, limit)
    pdb_files = pdbe_fetch_task(pdb_results, session_dir)
    filtered_pdb_files = filter_pdbs_task(pdb_results, pdb_files, pdb_query, session_dir)

    af_results = af_of_uniprot(uniprot_accessions, limit)
    af_entries = af_fetch_task(af_results, session_dir)
    filtered_af_files = filter_af_task(af_entries, density_query, session_dir)

    templates = prep_powerfit(filtered_af_files, filtered_pdb_files)
    solutions = powerfit.partial(options=powerfit_options, session_dir=session_dir).expand(template=templates)
    scores = score_report(solutions, top)
    fitted_models = fit_model_task.expand(row=scores)
    save_results(scores, fitted_models, session_dir)


minimal_workflow()
