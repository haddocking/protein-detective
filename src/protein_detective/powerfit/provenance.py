"""Read PowerFit run arguments and target associations from RO-Crate metadata."""

import shlex
from pathlib import Path
from typing import TypedDict

from rocrate.metadata import BASENAME
from rocrate.rocrate import ROCrate

from protein_detective.provenance import command_tokens


class PowerfitRunArguments(TypedDict):
    """Recorded run fields; unknown values are None.

    Attributes:
        used_target: Session-relative target explicitly associated with the run.
        options: Shell-quoted arguments following the recorded PowerFit command.
        action_id: Identifier of the associated RO-Crate creation action.
    """

    used_target: str | None
    options: str | None
    action_id: str | None


def powerfit_run_arguments_from_rocrate(session_dir: Path) -> dict[str, PowerfitRunArguments]:
    """Extract recorded fitting runs without guessing targets from filenames.

    Args:
        session_dir: Session directory containing RO-Crate metadata.

    Returns:
        Run IDs mapped to ``used_target``, ``options``, and ``action_id``.
        The target is the unique input described as the density used for fitting
        and located directly inside the recorded run directory. Missing or
        ambiguous targets are None. Options preserve all command arguments after
        ``powerfit run``, including the original target and session paths.
        Returns an empty dictionary when no fitting actions or crate exist.

    Notes:
        Only recorded ``powerfit/<run>`` Dataset outputs identify runs here.
        Discovering incomplete, unrecorded directories is the metadata loader's
        responsibility. This function does not inspect target file contents or
        require recorded files to still exist. Run directories cannot be reused,
        so each run has one recorded fitting action.
    """
    if not (session_dir / BASENAME).is_file():
        return {}
    runs: dict[str, PowerfitRunArguments] = {}
    crate = ROCrate(session_dir)
    for action in crate.get_by_type("CreateAction"):
        arguments = command_tokens(action.id, ("protein-detective", "powerfit", "run"))
        if arguments is None:
            continue
        for result in action.get("result", []):
            run_dir = Path(result.id)
            if len(run_dir.parts) != 2 or run_dir.parts[0] != "powerfit" or result.type != "Dataset":
                continue
            targets = {
                obj.id
                for obj in action.get("object", [])
                if str(obj.get("description") or "").startswith("Density map used for fitting.")
                and Path(obj.id).parent == run_dir
            }
            runs[run_dir.name] = {
                "used_target": next(iter(targets)) if len(targets) == 1 else None,
                "options": shlex.join(arguments),
                "action_id": action.id,
            }
    return runs
