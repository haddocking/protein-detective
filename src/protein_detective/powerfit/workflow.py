import csv
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path
from textwrap import dedent

from dask.distributed import Client, progress
from distributed.deploy.cluster import Cluster
from duckdb import connect
from pandas import DataFrame
from protein_quest.structure.formats import read_structure
from protein_quest.structure.uniprot import structure2uniprot_accessions
from rocrate_action_recorder import IOArgumentPath, IOArgumentPaths

from protein_detective.common_cli import write_ro_crate
from protein_detective.powerfit.options import PowerfitOptions
from protein_detective.powerfit.parallel import build_gpu_cycler, configure_dask_scheduler, detect_available_gpus
from protein_detective.powerfit.run import clear_worker_cache, powerfit_worker
from protein_detective.powerfit.solution import fit_models

logger = logging.getLogger(__name__)


def _find_structure_files(session_dir: Path) -> list[Path]:
    combined_filter_output = session_dir / "combined_output"
    ss_output_dir = session_dir / "secondary_structure"
    structure_files_dir = ss_output_dir if ss_output_dir.exists() else combined_filter_output
    if not structure_files_dir.exists():
        msg = (
            f"Structure files directory '{structure_files_dir}' does not exist. "
            "Please run `protein-detective filter` command."
        )
        raise FileNotFoundError(msg)
    return sorted(structure_files_dir.glob("*"))


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

    structure_files = _find_structure_files(session_dir)

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
        result_dir = powerfit_run_root_dir / powerfit_run_id / structure_file.name
        command = options.to_command(
            density_map=density_map_target,
            resolution=resolution,
            template=structure_file,
            out_dir=result_dir,
            gpu_cycler=gpu_cycler,
        )
        commands.append(command)

    return commands, powerfit_run_id


def _write_ro_crate4runs(
    session_dir: Path,
    start_time: datetime,
    /,
    *,
    density_map_target: Path,
    structure_files_root: Path,
    powerfit_run_dir: Path,
) -> None:
    ioargs = IOArgumentPaths(
        input_files=[
            IOArgumentPath(
                name="density_map_target",
                path=density_map_target,
                help="Density map used for fitting.",
            ),
        ],
        input_dirs=[
            IOArgumentPath(
                name="structure_files_root",
                path=structure_files_root,
                help="Directory containing the structure files used for fitting.",
            ),
        ],
        output_dirs=[
            IOArgumentPath(
                name="powerfit_run_dir",
                path=powerfit_run_dir,
                help="Directory where the PowerFit results were stored.",
            ),
        ],
    )
    write_ro_crate(
        session_dir,
        start_time,
        command_name="powerfit run",
        command_description="Run PowerFit on structure files",
        ioargs=ioargs,
    )


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
    start_time = datetime.now(tz=UTC)
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

    structure_files_root = structure_files[0].parent
    powerfit_run_dir = powerfit_run_root_dir / powerfit_run_id
    _write_ro_crate4runs(
        session_dir,
        start_time,
        density_map_target=density_map_target,
        structure_files_root=structure_files_root,
        powerfit_run_dir=powerfit_run_dir,
    )

    return powerfit_run_id


def make_structures_df(session_dir: Path) -> list[dict]:
    structure_files = _find_structure_files(session_dir)
    data: list[dict[str, str]] = []
    for structure_file in structure_files:
        name = structure_file.name
        structure = read_structure(structure_file)
        pdb_id = structure.name
        uniprot_accession = next(iter(structure2uniprot_accessions(structure)))
        data.append(
            {
                "structure_file": str(structure_file),
                "structure": name,
                "pdb_id": pdb_id,
                "uniprot_accession": uniprot_accession,
            }
        )
    return data


def create_structures_csv(session_dir, structures_lookup_csv):
    structures_data = make_structures_df(session_dir)
    with structures_lookup_csv.open("wt", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=structures_data[0].keys())
        writer.writeheader()
        writer.writerows(structures_data)


def powerfit_report(
    session_dir: Path,
    powerfit_run_id: str | None = None,
):
    structures_lookup_csv = session_dir / "powerfit" / "structures_lookup.csv"
    if not structures_lookup_csv.exists():
        # TODO create earlier or record in rocrate
        create_structures_csv(session_dir, structures_lookup_csv)

    solutions = session_dir / "powerfit" / "*" / "*" / "solutions.out"
    if powerfit_run_id:
        solutions = session_dir / "powerfit" / powerfit_run_id / "*" / "solutions.out"
    with connect() as con:
        query = dedent("""\
        SELECT
            powerfit_run_id,
            structure,
            rank,
            cc,
            fishz,
            relz,
            translation,
            rotation,
            structure_file AS template_file,
            uniprot_accession,
            pdb_id
        FROM (
            SELECT
                parse_path(filename)[-3] AS powerfit_run_id,
                parse_path(filename)[-2] AS structure,
                rank, cc, fishz, relz,
                [x,y,z]::FLOAT[3] AS translation,
                [a11, a12, a13, a21, a22, a23, a31, a32, a33]::FLOAT[9] AS rotation,
            FROM
                read_csv(
                    ?,
                    filename=True, normalize_names=True,
                    columns={
                        'rank': 'INTEGER',
                        'cc': 'FLOAT',
                        'fishz': 'FLOAT',
                        'relz': 'FLOAT',
                        'x': 'FLOAT',
                        'y': 'FLOAT',
                        'z': 'FLOAT',
                        'a11': 'FLOAT',
                        'a12': 'FLOAT',
                        'a13': 'FLOAT',
                        'a21': 'FLOAT',
                        'a22': 'FLOAT',
                        'a23': 'FLOAT',
                        'a31': 'FLOAT',
                        'a32': 'FLOAT',
                        'a33': 'FLOAT',
                    }
                )
            ) AS solutions
            JOIN read_csv(?) AS structures USING (structure)
        ORDER BY cc DESC, rank ASC
        """)
        con.execute(query, (str(solutions), str(structures_lookup_csv)))
        return con.df()


def powerfit_fit_models(
    session_dir: Path,
    powerfit_run_id: str | None = None,
    top: int = 1,
    group_by_structure: bool = True,
) -> DataFrame:
    """Fit models using PowerFit solutions.

    Args:
        session_dir: Directory containing the session data.
        powerfit_run_id: Optional ID of the PowerFit run to report. If None, reports over all runs.
        top: Number of top solutions to fit.
        group_by_structure: Whether to group solutions by structure before selecting top solutions.

    Returns:
        A DataFrame containing the fitted models. See protein_detective.db.save_fitted_models function
            for details.
    """
    all_solutions = powerfit_report(session_dir, powerfit_run_id)
    powerfit_root_run_dir = session_dir / "powerfit"
    if group_by_structure:  # noqa: SIM108 ternary is unclear
        solutions = all_solutions.groupby("structure").head(top)
    else:
        solutions = all_solutions.head(top)
    return fit_models(solutions, powerfit_root_run_dir)


def density_map_of_run_dir(run_dir: Path) -> Path:
    for potential_file in run_dir.iterdir():
        if potential_file.is_file():
            # TODO check for extensions
            return potential_file
    msg = f"No density map found in {run_dir}"
    raise FileNotFoundError(msg)


def powerfit_list_runs(session_dir: Path) -> list[tuple[str, str, Path]]:
    """List all PowerFit runs in the session directory.

    Args:
        session_dir: Directory containing the session data.

    Returns:
        A list of tuples containing the run ID, density map path, and directory path for each PowerFit run.
    """
    powerfit_root_dir = session_dir / "powerfit"
    runs = []
    for run_dir in sorted(powerfit_root_dir.iterdir()):
        if run_dir.is_dir():
            density_map = density_map_of_run_dir(run_dir)
            # TODO from ro-crate-metadata.json parse command used to create run_dir
            runs.append((run_dir.name, str(density_map), run_dir.relative_to(session_dir)))
    return runs
