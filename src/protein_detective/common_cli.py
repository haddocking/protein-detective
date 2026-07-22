from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Annotated

from cyclopts import Group, Parameter
from protein_quest.cli.common import setup_logging
from rich.console import Console
from rocrate_action_recorder import IOArgumentPaths, Program, record

from protein_detective.__version__ import __version__

console = Console(stderr=True)
rprint = console.print
common_group = Group("Common")


@Parameter(name="*", group=common_group)
@dataclass
class Common:
    """Common CLI options shared across all commands.

    Args:
        verbose: Increase verbosity (use multiple times for more detail).
        quiet: Decrease verbosity (use multiple times for less output).
    """

    # Same as protein_quest.cli.common.Common, but without --prov as we use
    # [low level record function](https://rocrate-action-recorder.readthedocs.io/en/latest/autoapi/rocrate_action_recorder/core/index.html#rocrate_action_recorder.core.record).
    # in commands

    verbose: Annotated[int, Parameter(name=("-v", "--verbose"), count=True)] = 0
    quiet: Annotated[int, Parameter(name=("-q", "--quiet"), count=True)] = 0

    def __post_init__(self):
        """Automatically configure logging when Common instance is created."""
        setup_logging(verbose=self.verbose, quiet=self.quiet)


def write_ro_crate(
    session_dir: Path,
    start_time: datetime,
    /,
    *,
    command_name: str,
    command_description: str,
    ioargs: IOArgumentPaths,
) -> None:
    """Write RO-Crate metadata for the command execution.

    Args:
        session_dir: Directory where the RO-Crate metadata will be written.
        start_time: The start time of the command execution.
        command_name: Name of the command being executed.
        command_description: Description of the command being executed.
        ioargs: Input and output arguments for the command execution.
    """
    record(
        program=Program(
            name="protein-detective",
            description="Detect proteins in EM density map",
            version=__version__,
            subcommands={
                command_name: Program(
                    name=f"protein-detective {command_name}",
                    description=command_description,
                )
            },
        ),
        ioargs=ioargs,
        dataset_license="CC-BY-4.0",
        start_time=start_time,
        crate_dir=session_dir,
    )
