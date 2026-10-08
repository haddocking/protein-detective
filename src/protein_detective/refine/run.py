"""Select fitted structures and coordinate independent refinement runs."""

import csv
import re
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from protein_quest.parallel import configure_dask_scheduler, map_with_progress, nr_cpus

from protein_detective.common_cli import rprint
from protein_detective.filter import _sequential_context
from protein_detective.refine.haddock import (
    RefineOptions,
    generate_haddock3_config_body,
    prepare_fixed_structure,
    run_haddock3,
)
from protein_detective.refine.provenance import write_refinement_ro_crate


def refine_structure_task(
    fitted_model: Path, /, *, session_dir: Path, root_refine_dir: Path, fixed_structure: Path, options: RefineOptions
) -> tuple[Path, Path]:
    """Configure and run HADDOCK3 for one fitted model.

    Args:
        fitted_model: Fitted input, absolute or relative to the session directory.
        session_dir: Absolute session directory containing PowerFit results.
        root_refine_dir: Directory for the independent refinement run.
        fixed_structure: Prepared fixed partner with chains renamed to B.
        options: Refinement parameters for HADDOCK3.

    Returns:
        Absolute fitted input and its model-level HADDOCK3 output directory.

    Raises:
        FileExistsError: The model output directory already exists.
        ValueError: The fitted input is outside the session's PowerFit directory.
    """
    abs_fitted_model = (session_dir / fitted_model).resolve()
    refine_run_dir = root_refine_dir / abs_fitted_model.relative_to(session_dir / "powerfit")

    if refine_run_dir.exists():
        msg = f"Refine directory already exists: {refine_run_dir}"
        raise FileExistsError(msg)

    # Keep the workflow config outside the run_dir because HADDOCK3's
    # setup_run refuses to start in a non-empty directory.
    refine_run_dir.parent.mkdir(parents=True, exist_ok=True)
    config_file = refine_run_dir.parent / f"{refine_run_dir.name}.cfg"
    config_body = generate_haddock3_config_body(
        run_dir=refine_run_dir,
        fitted_model=abs_fitted_model,
        fixed_structure=fixed_structure,
        options=options,
    )
    config_file.write_text(config_body)

    run_haddock3(config_file)

    return abs_fitted_model, refine_run_dir


def refine_structures(
    *,
    session_dir: Path,
    refine_dir: Path,
    fitted_models: list[Path],
    fixed_structure: Path,
    options: RefineOptions,
    scheduler_address: str,
) -> list[tuple[Path, Path]]:
    """Refine selected models using the configured scheduler.

    Args:
        session_dir: Absolute session directory containing PowerFit results.
        refine_dir: Directory for the independent refinement run.
        fitted_models: Fitted inputs, absolute or relative to the session directory.
        fixed_structure: Prepared fixed partner with chains renamed to B.
        options: Refinement parameters for HADDOCK3.
        scheduler_address: Dask scheduler address, or sequential execution mode.

    Returns:
        Absolute fitted inputs paired with their model-level output directories.
    """
    return map_with_progress(
        scheduler_address,
        refine_structure_task,
        fitted_models,
        options=options,
        session_dir=session_dir,
        fixed_structure=fixed_structure,
        root_refine_dir=refine_dir,
        map_with_progress_options={
            "tqdm_desc": "Refined structures",
            "tqdm_unit": "file",
        },
    )


def _write_io_csv(*, session_dir: Path, refine_dir: Path, refined: list[tuple[Path, Path]]) -> Path:
    io_csv = refine_dir / "io.csv"
    with io_csv.open("w") as f:
        writer = csv.writer(f)
        writer.writerow(["refine_run_id", "powerfit_run_id", "fitted_model", "refine_run_dir"])
        for fitted_model, refine_run_dir in refined:
            writer.writerow(
                [
                    refine_dir.name,
                    fitted_model.relative_to(session_dir / "powerfit").parts[0],
                    fitted_model.relative_to(session_dir),
                    refine_run_dir.relative_to(session_dir),
                ]
            )
    return io_csv


def create_refinement_run(session_dir: Path, refine_run_id: str | None = None) -> Path:
    """Create an exclusive refinement directory with a safe, independent run ID.

    Args:
        session_dir: Existing session directory in which to create the run.
        refine_run_id: Explicit run ID, starting with an ASCII letter or digit and
            containing only ASCII letters, digits, underscores, dots and hyphens.
            When omitted, use the next numeric ID above the existing maximum, using the refine_run_ prefix.

    Returns:
        Newly created directory under the session's refinement directory.

    Raises:
        ValueError: The explicit run ID is not a safe path component.
        FileExistsError: The selected run directory already exists.
    """
    root = session_dir / "refine"
    if refine_run_id is not None:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", refine_run_id):
            msg = f"Invalid refinement run ID: {refine_run_id!r}"
            raise ValueError(msg)
    else:
        existing = [
            int(match[1])
            for path in root.glob("refine_run_*")
            if (match := re.fullmatch(r"refine_run_([0-9]+)", path.name))
        ]
        refine_run_id = f"refine_run_{max(existing, default=0) + 1:03d}"
    root.mkdir(exist_ok=True)
    run_dir = root / refine_run_id
    run_dir.mkdir()
    return run_dir


def refine_with_haddock3(
    session_dir: Path,
    fixed_structure: Path,
    /,
    *,
    refine_options: RefineOptions | None = None,
    remove_fixed_chains: set[str] | None = None,  # TODO use frozenset and empty frozenset as default?
    refine_run_id: str | None = None,
    powerfit_run_id: str | None = None,
    scheduler_address: str | None = None,
):
    """Refine selected fitted models against a fixed structure with HADDOCK3.

    Store the input/output mapping before launching work and record successful
    results, configurations and effective options in the session's RO-Crate.

    Args:
        session_dir: Session directory containing fitted PowerFit results.
        fixed_structure: Fixed partner in the fitted models' coordinate system.
        refine_options: HADDOCK3 parameters; defaults to the standard refinement options.
        remove_fixed_chains: Original chain identifiers to remove before renaming
            remaining chains to B. Use author chain identifiers for mmCIF inputs.
        refine_run_id: Independent refinement ID; defaults to the next numeric ID
            above the existing maximum, using the refine_run_ prefix.
        powerfit_run_id: Source fitting run to select; defaults to all fitting runs.
        scheduler_address: Dask scheduler address, or 'sequential' to run locally
            without Dask. When omitted, create a local cluster.

    Raises:
        ValueError: No models are selected, an input path or run ID is invalid,
            or the requested chain removal is invalid.
        FileNotFoundError: A selected fitted input or fixed partner is missing.
        FileExistsError: The refinement run directory already exists.
    """
    if refine_options is None:
        refine_options = RefineOptions()
    session_dir = session_dir.resolve()
    start_time = datetime.now(tz=UTC)

    fitted_models_csv = session_dir / "powerfit" / "fitted_models.csv"
    fitted_models_df = pd.read_csv(fitted_models_csv)
    if powerfit_run_id is not None:
        fitted_models_df = fitted_models_df[fitted_models_df["powerfit_run_id"] == powerfit_run_id]

    structures_to_refine = list(
        dict.fromkeys((session_dir / f).resolve() for f in fitted_models_df["fitted_model_file"])
    )
    if not structures_to_refine:
        msg = "No fitted models selected for refinement."
        raise ValueError(msg)
    for model in structures_to_refine:
        relative_model = model.relative_to(session_dir / "powerfit")
        if len(relative_model.parts) != 3:
            msg = f"Expected powerfit/<run>/<structure>/<model> path: {model}"
            raise ValueError(msg)
        if not model.is_file():
            raise FileNotFoundError(model)
    if not fixed_structure.is_file():
        raise FileNotFoundError(fixed_structure)

    refine_dir = create_refinement_run(session_dir=session_dir, refine_run_id=refine_run_id)
    session_fixed_structure = prepare_fixed_structure(
        fixed_structure=fixed_structure,
        refine_dir=refine_dir,
        remove_fixed_chains=remove_fixed_chains,
    )

    if scheduler_address == "sequential":
        context = _sequential_context()
    else:
        scheduler_name = "protein_detective_refine"
        context = configure_dask_scheduler(
            scheduler_address, name=scheduler_name, nproc=min(refine_options.ncores, nr_cpus())
        )

    expected = [(model, refine_dir / model.relative_to(session_dir / "powerfit")) for model in structures_to_refine]
    io_csv = _write_io_csv(session_dir=session_dir, refine_dir=refine_dir, refined=expected)
    with context as cluster:
        real_scheduler_address = cluster if isinstance(cluster, str) else cluster.scheduler_address
        refined = refine_structures(
            session_dir=session_dir,
            refine_dir=refine_dir,
            fitted_models=structures_to_refine,
            fixed_structure=session_fixed_structure,
            options=refine_options,
            scheduler_address=real_scheduler_address,
        )

    write_refinement_ro_crate(
        session_dir=session_dir,
        start_time=start_time,
        session_fixed_structure=session_fixed_structure,
        fixed_structure=fixed_structure,
        refined=refined,
        io_csv=io_csv,
        options=refine_options,
        remove_fixed_chains=remove_fixed_chains,
        powerfit_run_id=powerfit_run_id,
    )
    rprint(f"Refinement run completed with ID: {refine_dir.name}")
