from argparse import Namespace
from collections.abc import Callable
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path

from rocrate_action_recorder import IOArgumentNames, record_argparse


def prov[T](
    input_dirs: list[str] | None = None,
    output_dirs: list[str] | None = None,
    input_files: list[str] | None = None,
    output_files: list[str] | None = None,
    crate_dir_argument: str | None = "session_dir",
) -> Callable[[Callable[[Namespace], T]], Callable[[Namespace], T]]:
    """Decorator to record provenance for protein-detective commands.

    Expects args Namespace given to handler to have a _parser attribute with the argparse.ArgumentParser.

    This is a copy of :func:`rocrate_action_recorder.recorded_argparse` with parser embedded into args.
    Made to avoid circular import between cli and powerfit.cli modules.
    """

    def decorator(func: Callable[[Namespace], T]) -> Callable[[Namespace], T]:
        @wraps(func)
        def wrapper(args: Namespace) -> T:
            start_datetime = datetime.now(tz=UTC)

            result = func(args)

            parser = args._parser
            enabled_argument = "prov"
            dataset_license = "CC BY 4.0"
            if enabled_argument is None or getattr(args, enabled_argument, False):
                my_crate_dir = None
                if crate_dir_argument:
                    args_crate_dir = getattr(args, crate_dir_argument, None)
                    if args_crate_dir is not None:
                        my_crate_dir = Path(args_crate_dir)
                end_time = datetime.now(tz=UTC)
                ios = IOArgumentNames(
                    input_dirs=input_dirs or [],
                    output_dirs=output_dirs or [],
                    input_files=input_files or [],
                    output_files=output_files or [],
                )
                record_argparse(
                    parser=parser,
                    ns=args,
                    ios=ios,
                    start_time=start_datetime,
                    end_time=end_time,
                    crate_dir=my_crate_dir,
                    dataset_license=dataset_license,
                )

            return result

        return wrapper

    return decorator
