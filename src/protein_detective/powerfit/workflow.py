# PowerFit-related workflow methods moved from workflow.py

import logging
import shutil
from pathlib import Path

import pandas as pd
from tqdm.auto import tqdm

from protein_detective.db import (
    connect,
    load_density_filtered_alphafolds_files,
    load_single_chain_pdb_files,
    powerfit_solutions,
    save_fitted_models,
    save_powerfit_options,
)
from protein_detective.powerfit.options import PowerfitOptions
from protein_detective.powerfit.run import run as powerfit_run
from protein_detective.powerfit.solution import fit_models


def _initialize_powerfit_run(session_dir, options):
    session_dir.mkdir(parents=True, exist_ok=True)
    with connect(session_dir) as con:
        powerfit_run_id = save_powerfit_options(options, con)
    powerfit_run_dir = session_dir / "powerfit" / str(powerfit_run_id)
    powerfit_run_dir.mkdir(parents=True, exist_ok=True)

    # Copy the density map to the powerfit directory
    density_map = options.target
    density_map_target = powerfit_run_dir / density_map.name
    shutil.copy(density_map, density_map_target)
    logging.getLogger(__name__).info(f"Copied density map from {density_map} to {density_map_target}")

    # Load the PDB files from the session directory
    pdb_files = []
    with connect(session_dir, read_only=True) as con:
        pdbe_files = load_single_chain_pdb_files(con)
        af_files = load_density_filtered_alphafolds_files(con)
        pdb_files = pdbe_files + af_files
    return powerfit_run_id, powerfit_run_dir, density_map_target, pdb_files


def powerfit_commands(session_dir: Path, options: PowerfitOptions) -> tuple[list[str], int]:
    """
    Generate PowerFit commands for fitting structures to a density map.

    Args:
        session_dir: Directory containing the session data, including PDB files.
        options: Options for generating PowerFit commands.

    Returns:
        A tuple containing:
            - A list of PowerFit command strings.
            - The ID of the PowerFit run saved in the session database.
    """
    powerfit_run_id, powerfit_run_root_dir, density_map_target, pdb_files = _initialize_powerfit_run(
        session_dir, options
    )

    # Generate PowerFit commands for each PDB file
    commands = []
    for pdb_file in pdb_files:
        result_dir = powerfit_run_root_dir / pdb_file.stem
        command = options.to_command(
            density_map=density_map_target,
            template=pdb_file,
            out_dir=result_dir,
        )
        commands.append(command)

    return commands, powerfit_run_id


def powerfit_runs(session_dir: Path, options: PowerfitOptions) -> int:
    """Run PowerFit on the PDB files in the session directory.

    Args:
        session_dir: Directory containing the session data, including PDB files.
        options: Options for running PowerFit.

    Returns:
        The ID of the PowerFit run saved in the session.
    """
    session_dir.mkdir(parents=True, exist_ok=True)
    powerfit_run_id, powerfit_run_root_dir, density_map_target, pdb_files = _initialize_powerfit_run(
        session_dir, options
    )

    with density_map_target.open("rb") as density_map:
        # TODO make run in parallel/distributed instead of sequentially
        # with some distributed computing framework such as
        # multiprocessing, joblib, dask, snakemake, airflow, cwl, prefect, ray, asyncio-subprocess
        # TODO if options.gpu is truthy then make sure parallel runs do not use the same gpu
        for pdb_file in tqdm(pdb_files, desc="Running PowerFit", unit="structure"):
            result_dir = powerfit_run_root_dir / pdb_file.stem
            powerfit_run(density_map, pdb_file, result_dir, options)

    return powerfit_run_id


def powerfit_report(session_dir: Path, powerfit_run_id: int | None = None) -> pd.DataFrame:
    """Report PowerFit results.

    Args:
        session_dir: Directory containing the session data.
        powerfit_run_id: Optional ID of the PowerFit run to report. If None, reports over all runs.

    Returns:
        A DataFrame containing the PowerFit solutions. See [protein_detective.db.powerfit_solutions][] for details.
    """
    with connect(session_dir, read_only=True) as con:
        return powerfit_solutions(con, powerfit_run_id=powerfit_run_id)


def powerfit_fit_models(session_dir: Path, powerfit_run_id: int | None = None, top: int = 10) -> pd.DataFrame:
    """Fit models using PowerFit solutions.

    Args:
        session_dir: Directory containing the session data.
        powerfit_run_id: Optional ID of the PowerFit run to report. If None, reports over all runs.
        top: Number of top solutions to fit.

    Returns:
        A DataFrame containing the fitted models. See protein_detective.db.save_fitted_models function
            for details.
    """
    all_solutions = powerfit_report(session_dir, powerfit_run_id)
    solutions = all_solutions.head(top)
    powerfit_root_run_dir = session_dir / "powerfit"
    fitted_df = fit_models(solutions, powerfit_root_run_dir)
    with connect(session_dir) as con:
        df4db = fitted_df.copy()

        # make *_file columns relative to session_dir
        def fn(x):
            return x.relative_to(session_dir)

        df4db["fitted_model_file"] = df4db["fitted_model_file"].apply(fn)
        df4db["unfitted_model_file"] = df4db["unfitted_model_file"].apply(fn)

        save_fitted_models(df4db, con)
    return fitted_df
