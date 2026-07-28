import csv
import logging
import shutil
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from textwrap import dedent
from typing import TypedDict

from dask.distributed import Client, progress
from distributed.deploy.cluster import Cluster
from duckdb import connect
from pandas import DataFrame
from protein_quest.structure.formats import read_structure
from protein_quest.structure.uniprot import structure2uniprot_accessions
from rocrate.rocrate import ROCrate
from rocrate_action_recorder import IOArgumentPath, IOArgumentPaths
from tqdm.auto import tqdm

from protein_detective.common_cli import write_ro_crate
from protein_detective.powerfit.options import PowerfitOptions
from protein_detective.powerfit.parallel import build_gpu_cycler, configure_dask_scheduler, detect_available_gpus
from protein_detective.powerfit.run import clear_worker_cache, powerfit_worker
from protein_detective.powerfit.solution import fit_models

logger = logging.getLogger(__name__)


def _find_structure_files(session_dir: Path) -> list[Path]:
    import_dir: Path = session_dir / "imported_structures"
    combined_filter_output = session_dir / "combined_output"
    ss_output_dir = session_dir / "secondary_structure"
    structure_files_dir = combined_filter_output
    if import_dir.exists():
        structure_files_dir = import_dir
    elif ss_output_dir.exists():
        structure_files_dir = ss_output_dir
    if not structure_files_dir.exists():
        msg = (
            f"Structure files directory '{structure_files_dir}' does not exist. "
            "Please run `protein-detective filter` command."
        )
        raise FileNotFoundError(msg)
    files = sorted(structure_files_dir.glob("*"))
    if not files:
        msg = f"No structure files found in '{structure_files_dir}'. Please run `protein-detective filter` command."
        raise FileNotFoundError(msg)
    return files


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

    return powerfit_run_id, powerfit_run_dir, density_map_target, structure_files


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

    Raises:
        FileNotFoundError: If no structure files are found in the session directory.
        FileExistsError: If the PowerFit run directory already exists.

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
    gpu_cycler = build_gpu_cycler(workers_per_gpu=options.workers_per_gpu, gpu_ids=gpu_ids)
    for structure_file in structure_files:
        result_dir = powerfit_run_root_dir / structure_file.name
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
    fittable_structures_csv: Path,
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
        output_files=[
            IOArgumentPath(
                name="fittable_structures_csv",
                path=fittable_structures_csv,
                help="CSV file containing the fittable structures with PDB IDs and UniProt accessions.",
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
) -> str:
    """Run PowerFit on PDB files in the session directory and store results.

    Args:
        target: Target density map to fit the model in. Data should either be in CCP4 or MRC format
        resolution: Resolution of map in Angstrom
        session_dir: Session directory for input and output
        options: Powerfit options.
        powerfit_run_id: ID of the PowerFit run to use. If not provided, will autoincrement based on existing runs.
        scheduler_address: Address of the Dask scheduler to use. If not provided, will create a local Dask cluster.
            If set to "sequential", will run PowerFit sequentially without using Dask.

    Raises:
        FileNotFoundError: If no structure files are found in the session directory.
        FileExistsError: If the PowerFit run directory already exists.

    Returns:
        The PowerFit run ID.
    """
    session_dir.mkdir(parents=True, exist_ok=True)
    start_time = datetime.now(tz=UTC)
    powerfit_run_id, powerfit_run_root_dir, density_map_target, structure_files = _initialize_powerfit_run(
        session_dir, target, powerfit_run_id=powerfit_run_id
    )
    fittable_structures_csv: Path = session_dir / "powerfit" / "fittable_structures.csv"
    create_fittable_structures_csv(session_dir, fittable_structures_csv)

    if scheduler_address == "sequential":
        for structure_file in tqdm(structure_files, unit="structure", desc="Running PowerFit sequentially"):
            powerfit_worker(
                structure_file,
                density_map_target=density_map_target,
                resolution=resolution,
                powerfit_run_root_dir=powerfit_run_root_dir,
                options=options,
            )
    else:
        workers_per_gpu = options.workers_per_gpu if options.gpu else 0
        with (
            configure_dask_scheduler(
                scheduler_address,
                name=f"powerfit-run-{powerfit_run_id}",
                workers_per_gpu=workers_per_gpu,
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
    _write_ro_crate4runs(
        session_dir,
        start_time,
        density_map_target=density_map_target,
        fittable_structures_csv=fittable_structures_csv,
        structure_files_root=structure_files_root,
        powerfit_run_dir=powerfit_run_root_dir,
    )

    return powerfit_run_id


class FittableStructure(TypedDict):
    structure_file: str
    structure: str
    pdb_id: str
    uniprot_accessions: str


def make_fittable_structures_df(session_dir: Path) -> list[FittableStructure]:
    structure_files = _find_structure_files(session_dir)
    data: list[FittableStructure] = []
    for structure_file in structure_files:
        name = structure_file.name
        structure = read_structure(structure_file)
        pdb_id = structure.name
        uniprot_accessions = ":".join(structure2uniprot_accessions(structure))
        data.append(
            {
                "structure_file": str(structure_file.relative_to(session_dir, walk_up=True)),
                "structure": name,
                "pdb_id": pdb_id,
                "uniprot_accessions": uniprot_accessions,
            }
        )
    return data


def create_fittable_structures_csv(session_dir: Path, fittable_structures_csv: Path) -> None:
    structures_data = make_fittable_structures_df(session_dir)
    with fittable_structures_csv.open("wt", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=structures_data[0].keys())
        writer.writeheader()
        writer.writerows(structures_data)


def powerfit_report(
    session_dir: Path,
    powerfit_run_id: str | None = None,
) -> DataFrame:
    """Return a DataFrame containing the PowerFit solutions.

    Args:
        session_dir: Directory containing the session data.
        powerfit_run_id: Optional ID of the PowerFit run to report. If None,

    Raises:
        FileNotFoundError: If no structure files are found in the session directory.

    Returns:
        A DataFrame containing the PowerFit solutions.
        With following columns:

        1, powerfit_run_id: ID of the PowerFit run
        2, structure: Name of the structure file
        3, rank: Rank of the solution
        4, cc: Cross-correlation coefficient of the solution
        5, fishz: FishZ score of the solution
        6, relz: Relative Z-score of the solution
        7, translation: Translation vector of the solution
        8, rotation: Rotation matrix of the solution
        9, template_file: Path to the template structure file, relative to the session directory
        10, uniprot_accessions: Comma-separated list of UniProt accessions
        11, pdb_id: PDB ID of the template structure
    """
    fittable_structures_csv = session_dir / "powerfit" / "fittable_structures.csv"
    if not fittable_structures_csv.exists():
        create_fittable_structures_csv(session_dir, fittable_structures_csv)

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
            uniprot_accessions,
            pdb_id
        FROM (
            SELECT
                parse_path(filename)[-3] AS powerfit_run_id,
                parse_path(filename)[-2] AS structure,
                rank, cc, fishz, relz,
                [x,y,z]::FLOAT[3] AS translation,
                [a11, a12, a13, a21, a22, a23, a31, a32, a33]::FLOAT[9] AS rotation
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
            JOIN read_csv(?) AS fittable_structures USING (structure)
        ORDER BY cc DESC, rank ASC
        """)
        con.execute(query, (str(solutions), str(fittable_structures_csv)))
        return con.df()


def powerfit_filtered_report(
    session_dir: Path,
    powerfit_run_id: str | None = None,
    top: int = 1,
    group_by_structure: bool = True,
) -> DataFrame:
    """Return PowerFit solutions filtered by rank and grouping mode.

    Args:
        session_dir: Directory containing the session data.
        powerfit_run_id: Optional ID of the PowerFit run to report. If None, reports over all runs.
        top: Number of top solutions to return.
        group_by_structure: Whether to group solutions by structure before selecting top solutions.

    Raises:
        FileNotFoundError: If no structure files are found in the session directory.

    Returns:
        A DataFrame containing the filtered PowerFit solutions.
    """
    all_solutions = powerfit_report(session_dir, powerfit_run_id)
    if group_by_structure:
        return all_solutions.groupby("structure").head(top)
    return all_solutions.head(top)


def _write_ro_crate4fit_models(
    session_dir: Path,
    start_time: datetime,
    /,
    *,
    fitted_df: DataFrame,
):
    ioargs = IOArgumentPaths(
        input_files=[
            IOArgumentPath(
                name=row,
                path=row,
                help="Unfitted model file.",
            )
            for row in fitted_df["unfitted_model_file"]
        ],
        output_files=[
            IOArgumentPath(
                name=row,
                path=row,
                help="Fitted model file.",
            )
            for row in fitted_df["fitted_model_file"]
        ],
    )
    write_ro_crate(
        session_dir,
        start_time,
        command_name="powerfit fit-models",
        command_description="Fit models to the best PowerFit solutions.",
        ioargs=ioargs,
    )


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

    Raises:
        FileNotFoundError: If no structure files are found in the session directory.

    Returns:
        A DataFrame containing the fitted models. See protein_detective.db.save_fitted_models function
            for details.
    """
    start_time = datetime.now(tz=UTC)
    solutions = powerfit_filtered_report(
        session_dir,
        powerfit_run_id,
        top,
        group_by_structure=group_by_structure,
    )
    fitted_df = fit_models(solutions, session_dir)

    _write_ro_crate4fit_models(
        session_dir,
        start_time,
        fitted_df=fitted_df,
    )
    return fitted_df


def density_map_of_run_dir(run_dir: Path) -> Path:
    for potential_file in run_dir.iterdir():
        if potential_file.is_file():
            # TODO check for extensions
            return potential_file
    msg = f"No density map found in {run_dir}"
    raise FileNotFoundError(msg)


def powerfit_run_options_from_rocrate(session_dir: Path) -> dict[str, str]:
    """Extract PowerFit run options from the RO-Crate metadata.

    Args:
        session_dir: Directory containing the session data.

    Raises:
        FileNotFoundError: If the RO-Crate file is missing from the session directory.

    Returns:
        A dictionary mapping PowerFit run IDs to their corresponding options.
    """
    crate = ROCrate(session_dir)
    runs = {}
    for action in crate.get_by_type("CreateAction"):
        raw_cmd = action.id
        if "protein-detective powerfit run" not in raw_cmd:
            continue
        # /home/verhoes/git/protein-detective/protein-detective/.venv/bin/protein-detective powerfit run \
        # --workers-per-gpu 2 --angle 40 --powerfit-run-id myrun1 ../powerfit-tutorial/ribosome-KsgA.map 13 ./mysession
        # ->
        # --workers-per-gpu 2 --angle 40 --powerfit-run-id myrun1 ../powerfit-tutorial/ribosome-KsgA.map 13 ./mysession
        options = raw_cmd.split("protein-detective powerfit run", 1)[1].strip()
        for result in action["result"]:
            if result.type != "Dataset":
                continue
            # powerfit/myrun1 -> myrun1
            run_dir = Path(result["name"]).name
            runs[run_dir] = options
    return runs


class RunInfo(TypedDict):
    powerfit_run_id: str
    density_map: Path
    run_dir: Path
    options: str


def powerfit_list_runs(session_dir: Path) -> list[RunInfo]:
    """List all PowerFit runs in the session directory.

    Args:
        session_dir: Directory containing the session data.

    Raises:
        FileNotFoundError: If no density map is found in any run directory.

    Returns:
        A list of RunInfo dictionaries for each PowerFit run.
    """
    powerfit_root_dir = session_dir / "powerfit"
    runs = []
    options = powerfit_run_options_from_rocrate(session_dir)
    for run_dir in sorted(powerfit_root_dir.iterdir()):
        if run_dir.is_dir():
            density_map = density_map_of_run_dir(run_dir).relative_to(session_dir, walk_up=True)
            info = RunInfo(
                powerfit_run_id=run_dir.name,
                density_map=density_map,
                run_dir=run_dir.relative_to(session_dir, walk_up=True),
                options=options.get(run_dir.name, ""),
            )
            runs.append(info)
    return runs


def list_lcc_files(session_dir: Path) -> Generator[tuple[str, str, Path]]:
    """List all lcc.mrc files in the PowerFit runs in the session directory.

    Args:
        session_dir: Directory containing the session data.

    Yields:
        Tuples containing the run ID, structure name, and path to the lcc.mrc
    """

    # `protein-detective powerfit run` does not generate lcc.mrc files
    # however commands of `protein-detective powerfit commands` do.
    # TODO add flag run command to generate lcc.mrc in powerfit_worker function
    powerfit_root_dir = session_dir / "powerfit"
    for lcc_file in powerfit_root_dir.glob("**/lcc.mrc"):
        structure = lcc_file.parent.name
        run_dir = lcc_file.parent.parent.name
        yield (run_dir, structure, lcc_file.relative_to(session_dir, walk_up=True))
