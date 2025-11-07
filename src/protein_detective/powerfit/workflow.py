# PowerFit-related workflow methods moved from workflow.py

from dataclasses import replace
import json
import logging
import shutil
from pathlib import Path

import pandas as pd
from dask.distributed import Client, progress
from distributed.deploy.cluster import Cluster

from protein_detective.db import (
    connect,
    load_filtered_structure_files,
    powerfit_solutions,
    save_fitted_models,
    save_powerfit_options,
)
from protein_detective.powerfit.options import PowerfitOptions
from protein_detective.powerfit.parallel import build_gpu_cycler, configure_dask_scheduler, powerfit_worker
from protein_detective.powerfit.run import FitActor
from protein_detective.powerfit.solution import fit_models

logger = logging.getLogger(__name__)


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
    logger.info(f"Copied density map from {density_map} to {density_map_target}")

    # Load the PDB files from the session directory
    template_structures = []
    with connect(session_dir, read_only=True) as con:
        template_structures = load_filtered_structure_files(con)
    return powerfit_run_id, powerfit_run_dir, density_map_target, template_structures


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
    powerfit_run_id, powerfit_run_root_dir, density_map_target, template_structures = _initialize_powerfit_run(
        session_dir, options
    )

    # Generate PowerFit commands for each PDB file
    commands = []
    gpu_cycler = build_gpu_cycler(options.gpu)
    for template_structure in template_structures:
        result_dir = powerfit_run_root_dir / template_structure.stem
        command = options.to_command(
            density_map=density_map_target, template=template_structure, out_dir=result_dir, gpu_cycler=gpu_cycler
        )
        commands.append(command)

    return commands, powerfit_run_id


def powerfit_runs(session_dir: Path, options: PowerfitOptions, scheduler_address: str | Cluster | None = None):
    """Run distributed PowerFits on each of the PDB files in the session directory.

    Args:
        session_dir: Directory containing the session data, including PDB files.
        options: Options for running PowerFit.
        scheduler_address: Address of the Dask scheduler or a Cluster instance or None for local execution.

    Returns:
        The ID of the PowerFit run saved in the session.
    """
    session_dir.mkdir(parents=True, exist_ok=True)
    with connect(session_dir) as con:
        powerfit_run_id = save_powerfit_options(options, con)
    template_structures = []
    with connect(session_dir, read_only=True) as con:
        template_structures = load_filtered_structure_files(con)
    scheduler_address = configure_dask_scheduler(
        scheduler_address,
        name=f"powerfit-run-{powerfit_run_id}",
        workers_per_gpu=options.gpu,
        nproc=options.nproc,
    )

    with Client(scheduler_address) as client:
        logger.info(f"Follow progress on dask dashboard at: {client.dashboard_link}")
        workers = list(client.scheduler_info()["workers"].keys())
        logger.info(f"Using workers: {workers}")
        actor_futures = [client.submit(FitActor, options, actor=True, workers=[worker]) for worker in workers]
        actors = [future.result() for future in actor_futures]
        logger.info(f"Actors initialized: {actors}")
        futures = []
        for i, template_structure in enumerate(template_structures):
            actor = actors[i % len(actors)]
            future = actor.fit_structure(template_structure)
            futures.append(future)
        progress(futures)

        results = client.gather(futures)

        logger.info("Cleaning up actors")
        for actor in actors:
            actor.close()

    logger.info(f"PowerFit run {powerfit_run_id} completed.")
    # Write results to session db instead of file
    results_fn = session_dir / f"powerfit_results.{powerfit_run_id}.json"
    with results_fn.open("w") as f:
        json.dump(results, f)

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
