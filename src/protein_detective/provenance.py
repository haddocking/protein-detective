"""Parse recorded command invocations without accessing their historical files."""

import argparse
import shlex
from collections.abc import Mapping
from pathlib import Path


class _RecordOption(argparse.Action):
    """Collect parsed options in their original order for provenance output."""

    def __call__(
        self,
        _parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: list[str],
        option_string: str | None = None,
    ) -> None:
        """Append an option name and its zero or one string values."""
        rest: list[str] = namespace.rest
        if option_string is not None:
            rest.append(option_string)
        rest.extend(values)


def command_tokens(invocation: str, command: tuple[str, ...]) -> list[str] | None:
    """Return arguments following an exact command, allowing an executable path.

    Args:
        invocation: Recorded shell command, including its executable and arguments.
        command: Nonempty tuple of executable basename and subcommand names,
            such as ``("protein-detective", "powerfit", "run")``.

    Returns:
        Shell-tokenized arguments after the matched command, without its
        executable or subcommands. Returns None when quoting is malformed or
        the command is absent. No file or argument-value validation is performed.
    """
    try:
        tokens = shlex.split(invocation)
    except ValueError:
        return None
    for index, token in enumerate(tokens):
        if Path(token).name == command[0] and tokens[index + 1 : index + len(command)] == list(command[1:]):
            return tokens[index + len(command) :]
    return None


def command_arguments(
    invocation: str, command: tuple[str, ...], option_arity: Mapping[str, bool]
) -> tuple[list[str], list[str]] | None:
    """Return positional arguments and remaining option tokens in recorded order.

    Quoted values, interspersed options, equals syntax, and ``--`` are supported.

    Args:
        invocation: Recorded shell command, including its executable and arguments.
        command: Nonempty tuple of executable basename and subcommand names.
        option_arity: Recognized option names mapped to True for options consuming
            one value or False for switches consuming no value.

    Returns:
        A pair of lists: positional arguments and the remaining option tokens,
        preserving order within each list. Option values use separate tokens
        (``--count=2`` becomes ``["--count", "2"]``). The ``--`` delimiter is omitted.
        Returns None for unknown options, missing option values, malformed
        quoting, or an invocation that does not match the command. Does not
        validate positional argument counts, values, or historical file paths.
    """
    arguments = command_tokens(invocation, command)
    if arguments is None:
        return None
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False, exit_on_error=False)
    for name, takes_value in option_arity.items():
        parser.add_argument(name, nargs=1 if takes_value else 0, action=_RecordOption, dest="rest")
    try:
        parsed, unmatched = parser.parse_known_args(arguments, namespace=argparse.Namespace(rest=[]))
    except argparse.ArgumentError:
        return None
    # No positional schema is needed: argparse leaves positional tokens unmatched.
    # Unknown options before the delimiter must not be mistaken for positionals.
    delimiter = unmatched.index("--") if "--" in unmatched else len(unmatched)
    if any(argument.startswith("-") and argument != "-" for argument in unmatched[:delimiter]):
        return None
    positional = unmatched[:delimiter] + unmatched[delimiter + 1 :]
    return positional, parsed.rest
