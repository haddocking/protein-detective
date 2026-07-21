from dataclasses import dataclass
from typing import Annotated

from cyclopts import Group, Parameter
from protein_quest.cli.common import setup_logging

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
