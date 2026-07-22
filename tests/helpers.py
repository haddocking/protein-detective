"""Helper functions for testing."""

import sys

from protein_detective.cli import app


def cli(tokens: list[str]):
    """Invoke the CLI with the given tokens.

    Replace default print_non_int_sys_exit result action,
    with action that does not throw SystemExit.
    Also mock sys.argv to simulate CLI invocation.

    Args:
        tokens: List of command line tokens to pass to the CLI.
    """
    old_argv = sys.argv
    sys.argv = ["protein-detective", *tokens]
    try:
        return app(tokens, result_action="return_value")
    finally:
        sys.argv = old_argv
