import csv
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from textwrap import dedent
from typing import Annotated

import pandas as pd
from cyclopts import Parameter, validators
from cyclopts.types import PositiveInt
from haddock.core.defaults import RUNDIR
from haddock.gear.prepare_run import setup_run
from haddock.libs.libio import working_directory
from haddock.libs.libworkflow import WorkflowManager
from protein_quest.cli.common import Common
from protein_quest.parallel import configure_dask_scheduler, map_with_progress
from protein_quest.structure.chains import chains_in_structure
from protein_quest.structure.formats import read_structure, write_structure
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
    # TODO do not overload system as dask cluster and haddock3 ncores are independent
    # we expect there are more models to refined then there are CPU cores available
    ncores: PositiveInt = 1


def _write_ro_crate(
    session_dir: Path,
    start_time: datetime,
    session_fixed_structure: Path,
    refined: list[tuple[Path, Path]],
    io_csv: Path,
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
                help="Fitted model file.",
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
        output_files=[
            IOArgumentPath(
                name="io_csv",
                path=io_csv,
                help="CSV file containing fitted model path and refine run dir.",
            )
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
        run_dir = "{run_dir}"
        mode = "local"
        ncores = {options.ncores}
        clean = true

        molecules = [
            "{fitted_model}",
            "{fixed_structure}"
        ]

        [topoaa]

        [rigidbody]
        separate = false
        mol_fix_origin_2 = true
        sampling = {options.rigidbody_sampling}
        cmrest = true

        [caprieval]

        [clustfcc]
        min_population = 1

        [caprieval]

        [seletopclusts]
        top_clusters = {options.top_clusters}
        top_models = {options.top_models}

        [mdref]
        # sampling = {options.water_refinement_sampling}

        [caprieval]
        """)


def _prepare_fixed_structure(fixed_structure: Path, refine_dir: Path, out_chain: str = "B") -> Path:
    # Haddock3 does not work with mmcif so convert to pdb
    # luckily fitted models are already pdb formatted.
    fixed_structure_dest = refine_dir / "fixed_structure.pdb"
    structure = read_structure(fixed_structure)

    chains = chains_in_structure(structure)
    # Chain rename logic from include/gemmi/modify.hpp:rename_chain
    if chains != {out_chain}:
        for residue in structure.mod_residues:
            residue.chain_name = out_chain
        for refinement in structure.meta.refinement:
            for group in refinement.tls_groups:
                for selection in group.selections:
                    selection.chain = out_chain
        for model in structure:
            for chain in model:
                if chain != out_chain:
                    chain.name = out_chain

    write_structure(structure, fixed_structure_dest)
    return fixed_structure_dest


def _run_haddock3(config_file: Path) -> None:
    modules_params, general_params = setup_run(config_file)
    run_dir = general_params[RUNDIR]

    with working_directory(run_dir):
        workflow = WorkflowManager(
            workflow_params=modules_params,
            start=None,
            **general_params,
        )
        workflow.run()

        if general_params.get("postprocess", True):
            workflow.postprocess(self_contained=general_params.get("gen_archive", False))

        workflow.clean()


def refine_structure_task(
    fitted_model: Path, /, *, root_refine_dir: Path, fixed_structure: Path, options: RefineOptions
) -> tuple[Path, Path]:
    # fitted_model=mysession/powerfit/run_001/4pld_updated_A2A.cif.gz/fit_1.pdb
    # refine_run_dir=mysession/refine/run_001/4pld_updated_A2A.cif.gz/fit_1.pdb/
    powerfit_root_run_dir = fitted_model.parent.parent.parent
    refine_run_dir = root_refine_dir / fitted_model.relative_to(powerfit_root_run_dir)
    abs_fitted_model = (root_refine_dir / ".." / fitted_model).resolve().absolute()

    if refine_run_dir.exists():
        msg = f"Refine directory already exists: {refine_run_dir}"
        raise FileExistsError(msg)

    # Keep the workflow config outside the run_dir because HADDOCK3's
    # setup_run refuses to start in a non-empty directory.
    refine_run_dir.parent.mkdir(parents=True, exist_ok=True)
    config_file = refine_run_dir.parent / f"{refine_run_dir.name}.cfg"
    config_body = _generate_config_body(refine_run_dir, abs_fitted_model, fixed_structure, options)
    config_file.write_text(config_body)

    _run_haddock3(config_file)

    return fitted_model, refine_run_dir


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

    structures_to_refine = [Path(f) for f in fitted_models_df["fitted_model_file"]]
    with context as cluster:
        real_scheduler_address = cluster if isinstance(cluster, str) else cluster.scheduler_address
        refined = refine_structures(
            refine_dir,
            structures_to_refine,
            session_fixed_structure,
            options=options,
            scheduler_address=real_scheduler_address,
        )

    io_csv = refine_dir / "io.csv"
    with io_csv.open("w") as f:
        writer = csv.writer(f)
        writer.writerow(["fitted_model", "refine_run_dir"])
        for fitted_model, refine_run_dir in refined:
            writer.writerow([fitted_model, refine_run_dir])

    _write_ro_crate(session_dir, start_time, session_fixed_structure, refined, io_csv)
