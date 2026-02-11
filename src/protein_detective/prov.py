from argparse import Namespace
from collections.abc import Callable

from rocrate_action_recorder import recorded_argparse


def prov[T](
    input_dirs: list[str] | None = None,
    output_dirs: list[str] | None = None,
    input_files: list[str] | None = None,
    output_files: list[str] | None = None,
    crate_dir_argument: str | None = "session_dir",
) -> Callable[[Callable[[Namespace], T]], Callable[[Namespace], T]]:
    """Decorator to record provenance for protein-detective commands.

    Expects args Namespace given to handler to have a _parser attribute with the argparse.ArgumentParser.

    This is a copy of [rocrate_action_recorder.recorded_argparse][] with parser embedded into args.
    Made to avoid circular import between cli and powerfit.cli modules.
    """
    return recorded_argparse(
        input_dirs=input_dirs,
        output_dirs=output_dirs,
        input_files=input_files,
        output_files=output_files,
        crate_dir_argument=crate_dir_argument,
        enabled_argument="prov",
        parser_argument="_parser",
        dataset_license="CC BY 4.0",
    )
