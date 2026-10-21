"""Record refinement provenance and read invocation arguments from RO-Crate."""

import shlex
from dataclasses import asdict, fields
from datetime import datetime
from pathlib import Path

from rocrate.metadata import BASENAME
from rocrate.rocrate import ROCrate
from rocrate_action_recorder import IOArgumentPath, IOArgumentPaths

from protein_detective.common_cli import write_ro_crate
from protein_detective.provenance import command_arguments
from protein_detective.refine.haddock import RefineOptions


def refine_run_arguments_from_rocrate(session_dir: Path) -> dict[str, str]:
    """Extract command options from recorded refinement invocations.

    Args:
        session_dir: Session directory containing RO-Crate metadata.

    Returns:
        Refinement run IDs mapped to command options, excluding positional
        arguments. Empty when the session has no RO-Crate metadata.
    """
    if not (session_dir / BASENAME).is_file():
        return {}
    crate = ROCrate(session_dir)
    runs = {}
    for action in crate.get_by_type("CreateAction"):
        option_arity = {
            "--" + field.name.replace("_", "-"): not isinstance(field.default, bool) for field in fields(RefineOptions)
        }
        option_arity.update(
            dict.fromkeys(
                (
                    "--remove-known-chains",
                    "--refine-run-id",
                    "--powerfit-run-id",
                    "--scheduler-address",
                ),
                True,
            )
        )
        option_arity.update(dict.fromkeys(("--verbose", "--quiet", "-v", "-q"), False))
        parsed = command_arguments(action.id, ("protein-detective", "refine", "run"), option_arity)
        if parsed is None or len(parsed[0]) != 2:
            continue
        options = shlex.join(parsed[1])
        for result in action.get("result", []):
            parts = Path(result.id).parts
            if len(parts) >= 2 and parts[0] == "refine":
                runs[parts[1]] = options
    return runs


def write_refinement_ro_crate(
    *,
    session_dir: Path,
    start_time: datetime,
    processed_known_structure: Path,
    input_known_structure: Path,
    refined: list[tuple[Path, Path]],
    io_csv: Path,
    options: RefineOptions,
    remove_known_chains: set[str] | None,
    powerfit_run_id: str | None,
    original_known_structure: Path | None = None,
):
    """Record refinement inputs, outputs and effective options in RO-Crate.

    Args:
        session_dir: Session directory in which to write RO-Crate metadata.
        start_time: Time at which the refinement invocation started.
        processed_known_structure: Prepared known structure inside the session.
        input_known_structure: Original known structure used to prepare the partner.
        refined: Fitted inputs paired with their refinement output directories.
        io_csv: Per-run index containing the input/output mapping.
        options: Effective HADDOCK3 refinement parameters.
        remove_known_chains: Original chain identifiers removed before renaming.
        powerfit_run_id: Selected source fitting run, or all runs when omitted.
        original_known_structure: Unmodified known input saved inside the session.
    """
    ioargs = IOArgumentPaths(
        input_files=[
            IOArgumentPath(
                name="processed_known_structure",
                path=processed_known_structure,
                help=(
                    f"Known structure prepared from {input_known_structure.resolve()}; "
                    f"removed chains {sorted(remove_known_chains or [])}; "
                    "renamed remaining chains to B."
                ),
            ),
        ]
        + (
            [
                IOArgumentPath(
                    name="original_known_structure", path=original_known_structure, help="Original known input."
                )
            ]
            if original_known_structure is not None
            else []
        )
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
                help="Baseline and refinement haddock3 results.",
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
        command_name="refine run",
        command_description=(
            f"Refinement {io_csv.parent.name}; source PowerFit run: {powerfit_run_id or 'all'}; "
            f"options: {asdict(options)}; removed known chains: {sorted(remove_known_chains or [])}"
        ),
        ioargs=ioargs,
    )
