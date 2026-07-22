import logging
import shutil
from pathlib import Path

from dask.distributed import Client, progress
from distributed.deploy.cluster import Cluster

from protein_detective.powerfit.options import PowerfitOptions
from protein_detective.powerfit.parallel import build_gpu_cycler, configure_dask_scheduler, detect_available_gpus
from protein_detective.powerfit.run import clear_worker_cache, powerfit_worker

logger = logging.getLogger(__name__)


def _initialize_powerfit_run(
    session_dir: Path, input_target: Path, powerfit_run_id: str | None = None
) -> tuple[str, Path, Path, list[Path]]:
    powerfit_root_dir = session_dir / "powerfit"
    powerfit_root_dir.mkdir(parents=True, exist_ok=True)

    existing_runs = [d for d in powerfit_root_dir.iterdir() if d.is_dir()]
    if powerfit_run_id is None:
        powerfit_run_id = f"run_{len(existing_runs) + 1:03d}"
    powerfit_run_dir = powerfit_root_dir / powerfit_run_id
    if powerfit_run_dir.exists():
        msg = f"PowerFit run directory '{powerfit_run_dir}' already exists."
        raise FileExistsError(msg)
    powerfit_run_dir.mkdir(parents=True, exist_ok=False)

    # Copy the density map to the powerfit directory
    density_map = input_target
    density_map_target = powerfit_run_dir / density_map.name
    shutil.copy(density_map, density_map_target)
    logger.info(f"Copied density map from {density_map} to {density_map_target}")

    combined_filter_output = session_dir / "combined_output"
    ss_output_dir = session_dir / "secondary_structure"
    structure_files_dir = ss_output_dir if ss_output_dir.exists() else combined_filter_output
    if not structure_files_dir.exists():
        msg = (
            f"Structure files directory '{structure_files_dir}' does not exist. "
            "Please run `protein-detective filter` command."
        )
        raise FileNotFoundError(msg)
    structure_files = sorted(structure_files_dir.glob("*"))

    return powerfit_run_id, powerfit_root_dir, density_map_target, structure_files


def powerfit_commands(
    target: Path,
    resolution: float,
    session_dir: Path,
    /,
    *,
    options: PowerfitOptions,
    powerfit_run_id: str | None = None,
) -> tuple[list[str], str]:
    """Generate PowerFit commands for structure files in the session directory.

    Args:
        target: Target density map to fit the model in. Data should either be in CCP4 or MRC format
        resolution: Resolution of map in Angstrom
        session_dir: Session directory for input and output
        options: Powerfit options.
        powerfit_run_id: ID of the PowerFit run to use. If not provided, will autoincrement based on existing runs.

    Returns:
        A tuple containing a list of PowerFit commands and the PowerFit run ID.
    """
    powerfit_run_id, powerfit_run_root_dir, density_map_target, structure_files = _initialize_powerfit_run(
        session_dir, target, powerfit_run_id=powerfit_run_id
    )

    commands = []
    gpu_ids = detect_available_gpus(options.gpu_backend)
    if options.gpu and not gpu_ids:
        msg = "GPU execution requested, but no GPUs were detected."
        raise ValueError(msg)
    gpu_cycler = build_gpu_cycler(workers_per_gpu=1, gpu_ids=gpu_ids)
    for structure_file in structure_files:
        result_dir = powerfit_run_root_dir / powerfit_run_id / structure_file.stem
        command = options.to_command(
            density_map=density_map_target,
            resolution=resolution,
            template=structure_file,
            out_dir=result_dir,
            gpu_cycler=gpu_cycler,
        )
        commands.append(command)

    return commands, powerfit_run_id

def powerfit_runs(
    target: Path,
    resolution: float,
    session_dir: Path,
    /,
    *,
    options: PowerfitOptions,
    powerfit_run_id: str | None = None,
    scheduler_address: str | Cluster | None = None,
):
    """Run PowerFit on PDB files in the session directory and store results.

    Args:
        target: Target density map to fit the model in. Data should either be in CCP4 or MRC format
        resolution: Resolution of map in Angstrom
        session_dir: Session directory for input and output
        options: Powerfit options.
        powerfit_run_id: ID of the PowerFit run to use. If not provided, will autoincrement based on existing runs.
        scheduler_address: Address of the Dask scheduler to use. If not provided, will create a local Dask cluster.
    """
    session_dir.mkdir(parents=True, exist_ok=True)
    powerfit_run_id, powerfit_run_root_dir, density_map_target, structure_files = _initialize_powerfit_run(
            session_dir, target, powerfit_run_id=powerfit_run_id
    )
    with (
        configure_dask_scheduler(
            scheduler_address,
            name=f"powerfit-run-{powerfit_run_id}",
            workers_per_gpu=options.gpu,
            nproc=options.nproc,
            gpu_backend=options.gpu_backend,
        ) as scheduler_address,
        Client(scheduler_address) as client,
    ):
        logger.info(f"Follow progress on dask dashboard at: {client.dashboard_link}")
        client.run(clear_worker_cache)
        futures = client.map(
            powerfit_worker,
            structure_files,
            density_map_target=density_map_target,
            resolution=resolution,
            powerfit_run_root_dir=powerfit_run_root_dir,
            options=options,
        )

        progress(futures)

        client.gather(futures)

    return powerfit_run_id
