"""CLI entry point for protein-detective."""

import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated

import cyclopts
from cyclopts import App, Group, Parameter
from protein_quest.cli.common import setup_logging
from rich.console import Console
from rich.traceback import install as install_rich_traceback

from protein_detective.__version__ import __version__

console = Console(stderr=True)
rprint = console.print

app = App(
    name="protein-detective",
    version=__version__,
    help="Protein Detective CLI",
)

app.register_install_completion_command()
install_rich_traceback(console=console, suppress=[cyclopts])

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

def main(argv: Sequence[str] | None = None) -> None:
    """Main entry point for the CLI.

    Args:
        argv: List of command line arguments. If None, uses sys.argv.
    """
    actual_argv = argv or sys.argv[1:]
    app(actual_argv)
