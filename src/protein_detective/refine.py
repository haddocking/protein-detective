import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from subprocess import run
from textwrap import dedent
from typing import Annotated

import pandas as pd
from cyclopts import Parameter, validators
from cyclopts.types import PositiveInt
from protein_quest.cli.common import Common
from protein_quest.parallel import configure_dask_scheduler, map_with_progress
from protein_quest.structure.formats import read_structure, write_structure
from pytz import UTC
from rocrate_action_recorder import IOArgumentPath, IOArgumentPaths

from protein_detective.common_cli import write_ro_crate
from protein_detective.filter import _sequential_context


@dataclass
class RefineOptions:
    """Options for refining a structure with HADDOCK3.

    Attributes:
        rigidbody_sampling: Number of rigidbody samples.
        top_clusters: Number of top clusters to keep.
        top_models: Number of top models to keep.
        water_refinement_sampling: Number of water refinement samples.
        ncores: Number of CPU cores to use.
    """

    rigidbody_sampling: PositiveInt = 1000
    top_clusters: PositiveInt = 10
    top_models: PositiveInt = 2
    water_refinement_sampling: PositiveInt = 5
    ncores: PositiveInt = 1  # TODO do not overload system as dask cluster and haddock3 ncores are independent


def _haddock3_executable() -> Path:
    # TODO do this once, no need to find each loop iteration
    return Path(sys.executable).with_name("haddock3").resolve(strict=True)


def _write_ro_crate(
    session_dir: Path, start_time: datetime, session_fixed_structure: Path, refined: list[tuple[Path, Path]]
):
    ioargs = IOArgumentPaths(
        input_files=[
            IOArgumentPath(
                name="fixed_structure",
                path=session_fixed_structure,
                help="Fixed structure file.",
            ),
        ]
        + [
            IOArgumentPath(
                name=f"refined_{i}",
                path=fitted_model,
                help="Fitted structure file.",
            )
            for i, (fitted_model, _) in enumerate(refined)
        ],
        output_dirs=[
            IOArgumentPath(
                name=f"refined_{i}",
                path=refined_path,
                help="Refined structure result.",
            )
            for i, (_, refined_path) in enumerate(refined)
        ],
    )
    write_ro_crate(
        session_dir,
        start_time,
        command_name="refine",
        command_description="Refine fitted structure files based on specified parameters",
        ioargs=ioargs,
    )


def _generate_config_body(run_dir: Path, fitted_model: Path, fixed_structure: Path, options: RefineOptions) -> str:
    return dedent(f"""\
        run_dir = {run_dir}
        mode="local"
        ncores={options.ncores}

        molecules = [
            "{fitted_model}",
            "{fixed_structure}"
        ]

        [topoaa]

        [rigidbody]
        separate = false
        mol_fix_origin_2 = true
        sampling = {options.rigidbody_sampling}

        [caprieval]

        [clustfcc]
        min_population = 1

        [caprieval]

        [seletopclusts]
        top_clusters = {options.top_clusters}
        top_models = {options.top_models}

        [mdref]
        sampling = {options.water_refinement_sampling}

        [caprieval]
        """)


def _prepare_fixed_structure(fixed_structure: Path, refine_dir: Path, out_chain: str = "B") -> Path:
    fixed_structure_dest = refine_dir / "fixed_structure.cif.gz"
    structure = read_structure(fixed_structure)
    for model in structure:
        for chain in model:
            chain.name = out_chain
    write_structure(structure, fixed_structure_dest)
    return fixed_structure_dest


def refine_structure_task(
    fitted_model: Path, /, *, root_refine_dir: Path, fixed_structure: Path, options: RefineOptions
) -> tuple[Path, Path]:
    # fitted_model=mysession/powerfit/run_001/4pld_updated_A2A.cif.gz/fit_1.pdb
    # refine_dir=mysession/refine/run_001/4pld_updated_A2A.cif.gz/fit_1.pdb/
    powerfit_run_dir = fitted_model.parent.parent
    refine_dir = root_refine_dir / powerfit_run_dir.relative_to(powerfit_run_dir.parents[2])
    refine_dir.mkdir(parents=True)

    config_file = refine_dir / "workflow.cfg"
    config_body = _generate_config_body(refine_dir, fitted_model, fixed_structure, options)
    config_file.write_text(config_body)

    process_result = run([_haddock3_executable(), config_file], cwd=refine_dir, check=True)  # noqa: S603
    if process_result.returncode != 0:
        msg = f"refine structure of {fitted_model} using haddock3 failed with return code {process_result.returncode}"
        raise RuntimeError(msg)

    return fitted_model, refine_dir


def refine_structures(
    refine_dir: Path,
    fitted_models: list[Path],
    fixed_structure: Path,
    options: RefineOptions,
    scheduler_address: str,
) -> list[tuple[Path, Path]]:
    return map_with_progress(
        scheduler_address,
        refine_structure_task,
        fitted_models,
        options=options,
        fixed_structure=fixed_structure,
        root_refine_dir=refine_dir,
        map_with_progress_options={
            "tqdm_desc": "Refined structures",
            "tqdm_unit": "file",
        },
    )


def refine_with_haddock3(
    session_dir: Annotated[Path, Parameter(validator=validators.Path(file_okay=False, dir_okay=True, exists=True))],
    fixed_structure: Annotated[Path, Parameter(validator=validators.Path(file_okay=True, dir_okay=False, exists=True))],
    /,
    *,
    options: Annotated[RefineOptions, Parameter(name="*")] | None = None,
    powerfit_run_id: str | None = None,
    scheduler_address: str | None = None,
    _: Common | None = None,
):
    """Refine a structure with HADDOCK3.

    All fitted models will be refined against the fixed structure
    using HADDOCK3 rigidbody and molecular dynamics refinement.

    Args:
        session_dir: Session directory containing fitted PowerFit results
        fixed_structure: Path to the fixed structure to refine against.
            Can be a PDB or mmCIF file either gzipped or not.
            If will be copied into session directory and
            converted into a structure file with all chains renamed to **B**.
            It will not be translated or rotated.
        options: Refinement options for HADDOCK3.
        powerfit_run_id: ID of the PowerFit run to refine.
            If not provided, all fitted models of all runs will be refined.
        scheduler_address: Address of the Dask scheduler to connect to.
            If not provided, will create a local cluster.
            If set to `sequential` will run tasks sequentially.
    """
    if options is None:
        options = RefineOptions()
    start_time = datetime.now(tz=UTC)

    fitted_models_csv = session_dir / "powerfit" / "fitted_models.csv"
    fitted_models_df = pd.read_csv(fitted_models_csv)
    if powerfit_run_id is not None:
        fitted_models_df = fitted_models_df[fitted_models_df["powerfit_run_id"] == powerfit_run_id]

    refine_dir = session_dir / "refine"
    refine_dir.mkdir()
    session_fixed_structure = _prepare_fixed_structure(fixed_structure, refine_dir)

    if scheduler_address == "sequential":
        context = _sequential_context()
    else:
        scheduler_name = "protein_detective_filter"
        context = configure_dask_scheduler(scheduler_address, name=scheduler_name)

    structures_to_refine: list[Path] = fitted_models_df["fitted_model_file"].to_list()
    with context as cluster:
        real_scheduler_address = cluster if isinstance(cluster, str) else cluster.scheduler_address
        refined = refine_structures(
            refine_dir,
            structures_to_refine,
            session_fixed_structure,
            options=options,
            scheduler_address=real_scheduler_address,
        )

    _write_ro_crate(session_dir, start_time, session_fixed_structure, refined)
    # TODO write refined into csv files so you know which refined haddock3 result is for what fitted model
