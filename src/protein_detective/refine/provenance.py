"""Record refinement provenance and read invocation arguments from RO-Crate."""

import shlex
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from rocrate.metadata import BASENAME
from rocrate.rocrate import ROCrate
from rocrate_action_recorder import IOArgumentPath, IOArgumentPaths

from protein_detective.common_cli import write_ro_crate
from protein_detective.refine.haddock import RefineOptions


def refine_run_arguments_from_rocrate(session_dir: Path) -> dict[str, tuple[str, str]]:
    """Extract fixed structure paths and options from recorded invocations.

    Args:
        session_dir: Session directory containing RO-Crate metadata.

    Returns:
        Refinement run IDs mapped to the original fixed structure path and
        command options, excluding positional arguments; empty when the session
        has no RO-Crate metadata.
    """
    if not (session_dir / BASENAME).is_file():
        return {}
    crate = ROCrate(session_dir)
    runs = {}
    for action in crate.get_by_type("CreateAction"):
        command = "protein-detective refine run"
        if command not in action.id:
            continue
        arguments = shlex.split(action.id.split(command, 1)[1])
        if len(arguments) < 2:
            continue
        fixed_structure = arguments[1]
        options = shlex.join(arguments[2:])
        for result in action.get("result", []):
            parts = Path(result.id).parts
            if len(parts) >= 2 and parts[0] == "refine":
                runs[parts[1]] = (fixed_structure, options)
    return runs


def write_refinement_ro_crate(
    *,
    session_dir: Path,
    start_time: datetime,
    session_fixed_structure: Path,
    fixed_structure: Path,
    refined: list[tuple[Path, Path]],
    io_csv: Path,
    options: RefineOptions,
    remove_fixed_chains: set[str] | None,
    powerfit_run_id: str | None,
):
    """Record refinement inputs, outputs and effective options in RO-Crate.

    Args:
        session_dir: Session directory in which to write RO-Crate metadata.
        start_time: Time at which the refinement invocation started.
        session_fixed_structure: Prepared fixed structure inside the session.
        fixed_structure: Original fixed structure used to prepare the partner.
        refined: Fitted inputs paired with their refinement output directories.
        io_csv: Per-run index containing the input/output mapping.
        options: Effective HADDOCK3 refinement parameters.
        remove_fixed_chains: Original chain identifiers removed before renaming.
        powerfit_run_id: Selected source fitting run, or all runs when omitted.
    """
    ioargs = IOArgumentPaths(
        input_files=[
            IOArgumentPath(
                name="fixed_structure",
                path=session_fixed_structure,
                help=(
                    f"Fixed structure prepared from {fixed_structure.resolve()}; "
                    f"removed chains {sorted(remove_fixed_chains or [])}; "
                    "renamed remaining chains to B."
                ),
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
        ]
        + [
            IOArgumentPath(
                name=f"config_{i}",
                path=refined_path.with_name(f"{refined_path.name}.cfg"),
                help="Effective HADDOCK3 configuration.",
            )
            for i, (_, refined_path) in enumerate(refined)
        ],
    )
    argv = [
        "protein-detective",
        "refine",
        "run",
        str(session_dir),
        str(fixed_structure.resolve()),
        "--refine-run-id",
        io_csv.parent.name,
    ]
    for key, value in asdict(options).items():
        argv.extend([f"--{key.replace('_', '-')}", str(value)])
    for chain in sorted(remove_fixed_chains or []):
        argv.extend(["--remove-fixed-chains", chain])
    if powerfit_run_id is not None:
        argv.extend(["--powerfit-run-id", powerfit_run_id])
    write_ro_crate(
        session_dir,
        start_time,
        command_name="refine run",
        command_description=(
            f"Refinement {io_csv.parent.name}; source PowerFit run: {powerfit_run_id or 'all'}; "
            f"options: {asdict(options)}; removed fixed chains: {sorted(remove_fixed_chains or [])}"
        ),
        ioargs=ioargs,
        argv=argv,
    )
