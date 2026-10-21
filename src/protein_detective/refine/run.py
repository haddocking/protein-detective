"""Select fitted structures and coordinate independent refinement runs."""

import csv
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from protein_quest.parallel import configure_dask_scheduler, map_with_progress, nr_cpus

from protein_detective.common_cli import rprint
from protein_detective.filter import _sequential_context
from protein_detective.refine.haddock import (
    RefineOptions,
    generate_haddock3_config_body,
    generate_unrefined_config_body,
    prepare_fitted_and_known,
    prepare_known_structure,
    run_haddock3,
)
from protein_detective.refine.provenance import write_refinement_ro_crate
from protein_detective.refine.reconstruct import reconstruct_refined_structures


@dataclass
class KnownStructure:
    """Known partner inputs and the original chains omitted from refinement."""

    processed_known_structure: Path
    original_known_structure: Path
    remove_known_chains: set[str] | None


def refine_structure_task(
    fitted_model: Path,
    /,
    *,
    session_dir: Path,
    root_refine_dir: Path,
    known_structure: KnownStructure,
    options: RefineOptions,
    haddock_log_level: int = logging.INFO,
) -> tuple[Path, Path]:
    """Configure and run HADDOCK3 for one fitted model.

    Args:
        fitted_model: Fitted input, absolute or relative to the session directory.
        session_dir: Absolute session directory containing PowerFit results.
        root_refine_dir: Directory for the independent refinement run.
        known_structure: Prepared and original partner paths with omitted chain IDs.
        options: Refinement parameters for HADDOCK3.
        haddock_log_level: Logging level of HADDOCK3 messages.

    Returns:
        Absolute fitted input and its directory containing both workflows.

    Raises:
        FileExistsError: The model output directory already exists.
        ValueError: The fitted input is outside the session's PowerFit directory.
    """
    abs_fitted_model = (session_dir / fitted_model).resolve()
    refine_run_dir = root_refine_dir / abs_fitted_model.relative_to(session_dir / "powerfit")

    if refine_run_dir.exists():
        msg = f"Refine directory already exists: {refine_run_dir}"
        raise FileExistsError(msg)

    refine_run_dir.mkdir(parents=True)
    baseline_dir = refine_run_dir / "baseline"
    baseline_dir.mkdir()
    complex_file = prepare_fitted_and_known(abs_fitted_model, known_structure.processed_known_structure, baseline_dir)
    baseline_config = baseline_dir / "workflow.cfg"
    baseline_config.write_text(generate_unrefined_config_body(baseline_dir, complex_file, options.ncores))
    run_haddock3(baseline_config, haddock_log_level)

    refinement_dir = refine_run_dir / "refinement"
    refinement_dir.mkdir()
    config_file = refinement_dir / "workflow.cfg"
    config_body = generate_haddock3_config_body(
        run_dir=refinement_dir,
        fitted_model=abs_fitted_model,
        processed_known_structure=known_structure.processed_known_structure,
        options=options,
    )
    config_file.write_text(config_body)

    run_haddock3(config_file, haddock_log_level)
    reconstruct_refined_structures(
        refinement_dir,
        known_structure.original_known_structure,
        remove_known_chains=known_structure.remove_known_chains,
    )

    return abs_fitted_model, refine_run_dir


def refine_structures(
    *,
    session_dir: Path,
    refine_dir: Path,
    fitted_models: list[Path],
    known_structure: KnownStructure,
    options: RefineOptions,
    scheduler_address: str,
    haddock_log_level: int = logging.INFO,
) -> list[tuple[Path, Path]]:
    """Refine selected models using the configured scheduler.

    Args:
        session_dir: Absolute session directory containing PowerFit results.
        refine_dir: Directory for the independent refinement run.
        fitted_models: Fitted inputs, absolute or relative to the session directory.
        known_structure: Prepared and original partner paths with omitted chain IDs.
        options: Refinement parameters for HADDOCK3.
        scheduler_address: Dask scheduler address, or sequential execution mode.
        haddock_log_level: Logging level of HADDOCK3 messages.

    Returns:
        Absolute fitted inputs paired with their directories containing both workflows.
    """
    return map_with_progress(
        scheduler_address,
        refine_structure_task,
        fitted_models,
        options=options,
        session_dir=session_dir,
        known_structure=known_structure,
        root_refine_dir=refine_dir,
        haddock_log_level=haddock_log_level,
        map_with_progress_options={
            "tqdm_desc": "Refined structures",
            "tqdm_unit": "file",
        },
    )


def _write_io_csv(
    *,
    session_dir: Path,
    refine_dir: Path,
    refined: list[tuple[Path, Path]],
    original_known_structure: Path,
    processed_known_structure: Path,
) -> Path:
    io_csv = refine_dir / "io.csv"
    with io_csv.open("w") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "refine_run_id",
                "powerfit_run_id",
                "fitted_model",
                "refine_run_dir",
                "original_known_structure",
                "processed_known_structure",
            ]
        )
        for fitted_model, refine_run_dir in refined:
            writer.writerow(
                [
                    refine_dir.name,
                    fitted_model.relative_to(session_dir / "powerfit").parts[0],
                    fitted_model.relative_to(session_dir),
                    refine_run_dir.relative_to(session_dir),
                    original_known_structure.relative_to(session_dir),
                    processed_known_structure.relative_to(session_dir),
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
    input_known_structure: Path,
    /,
    *,
    refine_options: RefineOptions | None = None,
    remove_known_chains: set[str] | None = None,  # TODO use frozenset and empty frozenset as default?
    refine_run_id: str | None = None,
    powerfit_run_id: str | None = None,
    scheduler_address: str | None = None,
    haddock_log_level: int = logging.INFO,
):
    """Refine selected fitted models against a known structure with HADDOCK3.

    Store the input/output mapping before launching work and record successful
    results, configurations and effective options in the session's RO-Crate.

    Args:
        session_dir: Session directory containing fitted PowerFit results.
        input_known_structure: Known partner in the fitted models' coordinate system.
        refine_options: HADDOCK3 parameters; defaults to the standard refinement options.
        remove_known_chains: Original chain identifiers to remove before renaming
            remaining chains to B. Use author chain identifiers for mmCIF inputs.
        refine_run_id: Independent refinement ID; defaults to the next numeric ID
            above the existing maximum, using the refine_run_ prefix.
        powerfit_run_id: Source fitting run to select; defaults to all fitting runs.
        scheduler_address: Dask scheduler address, or 'sequential' to run locally
            without Dask. When omitted, create a local cluster.
        haddock_log_level: Logging level of HADDOCK3 messages.
            Applied inside each worker, as workers do not share the logging configuration.

    Raises:
        ValueError: No models are selected, an input path or run ID is invalid,
            or the requested chain removal is invalid.
        FileNotFoundError: A selected fitted input or known partner is missing.
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

    refine_dir = create_refinement_run(session_dir=session_dir, refine_run_id=refine_run_id)
    processed_known_structure, original_known_structure = prepare_known_structure(
        input_known_structure=input_known_structure,
        refine_dir=refine_dir,
        remove_known_chains=remove_known_chains,
    )

    if scheduler_address == "sequential":
        context = _sequential_context()
    else:
        scheduler_name = "protein_detective_refine"
        context = configure_dask_scheduler(
            scheduler_address, name=scheduler_name, nproc=min(refine_options.ncores, nr_cpus())
        )

    expected = [(model, refine_dir / model.relative_to(session_dir / "powerfit")) for model in structures_to_refine]
    io_csv = _write_io_csv(
        session_dir=session_dir,
        refine_dir=refine_dir,
        refined=expected,
        original_known_structure=original_known_structure,
        processed_known_structure=processed_known_structure,
    )
    with context as cluster:
        real_scheduler_address = cluster if isinstance(cluster, str) else cluster.scheduler_address
        refined = refine_structures(
            session_dir=session_dir,
            refine_dir=refine_dir,
            fitted_models=structures_to_refine,
            known_structure=KnownStructure(
                processed_known_structure=processed_known_structure,
                original_known_structure=original_known_structure,
                remove_known_chains=remove_known_chains,
            ),
            options=refine_options,
            scheduler_address=real_scheduler_address,
            haddock_log_level=haddock_log_level,
        )

    write_refinement_ro_crate(
        session_dir=session_dir,
        start_time=start_time,
        processed_known_structure=processed_known_structure,
        input_known_structure=input_known_structure,
        original_known_structure=original_known_structure,
        refined=refined,
        io_csv=io_csv,
        options=refine_options,
        remove_known_chains=remove_known_chains,
        powerfit_run_id=powerfit_run_id,
    )
    rprint(f"Refinement run completed with ID: {refine_dir.name}")
