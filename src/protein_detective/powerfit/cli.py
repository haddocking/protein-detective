# PowerFit-related CLI methods moved from cli.py

import argparse
from pathlib import Path

from powerfit_em.powerfit import make_parser as make_powerfit_parser
from rich import print as rprint
from rich.table import Table

from protein_detective.db import connect, list_lcc_files, load_powerfit_runs
from protein_detective.powerfit.options import PowerfitOptions
from protein_detective.powerfit.workflow import powerfit_commands, powerfit_fit_models, powerfit_report, powerfit_runs


def _copy_powerfit_parser_arguments(parser: argparse.ArgumentParser, borrowed_arguments: None | set[str] = None):
    if borrowed_arguments is None:
        borrowed_arguments = {
            "target",
            "resolution",
            "angle",
            "laplace",
            "core_weighted",
            "no_resampling",
            "resampling_rate",
            "no_trimming",
            "trimming_cutoff",
            "nproc",
        }
    powerfit_parser = make_powerfit_parser()

    for powerfit_argument in powerfit_parser._actions:
        if powerfit_argument.dest in borrowed_arguments:
            parser._add_action(powerfit_argument)


def add_powerfit_commands_parser(subparsers):
    # Add the commands sub-command
    parser = subparsers.add_parser("commands", help="Generate PowerFit commands for PDB files in the session directory")

    _copy_powerfit_parser_arguments(parser)

    # Replaces template argument
    parser.add_argument("session_dir", help="Session directory for input and output")

    # Removed --chain, as protein-detective created single chain PDB files
    # Removed --directory argument as protein_detective will generate that argument

    # Removed --num, as we can fit models later with `powerfit fit-models` command

    # Replaces --gpu, from [<platform>:<device>] to boolean flag
    # When enabled and machine has multiple GPUs, then 0:0 is used
    parser.add_argument(
        "-g",
        "--gpu",
        dest="gpu",
        action="store_true",
        help="Off-load the intensive calculations to the GPU. ",
    )

    parser.add_argument(
        "--output",
        dest="output",
        type=argparse.FileType("w", encoding="UTF-8"),
        default="-",
        help="Output file for powerfit commands. If set to '-' (default) will print to stdout.",
    )


def add_powerfit_run_parser(subparsers):
    parser = subparsers.add_parser(
        "run",
        help="Run PowerFit on PDB files in the session directory",
        description="Run PowerFit on PDB files in the session directory and store results.",
    )

    _copy_powerfit_parser_arguments(parser)

    parser.add_argument("session_dir", help="Session directory containing PDB files")
    parser.add_argument(
        "-g",
        "--gpu",
        dest="gpu",
        action="store_true",
        help="Off-load the intensive calculations to the GPU. ",
    )


def add_powerfit_report_parser(subparsers):
    parser = subparsers.add_parser(
        "report",
        help="Generate a report of the best PowerFit solutions.",
    )
    parser.add_argument("session_dir", help="Session directory containing PowerFit results")
    parser.add_argument("--powerfit_run_id", type=int, default=None, help="ID of the PowerFit run to report on")
    parser.add_argument("--top", type=int, default=10, help="Number of top solutions to report")
    parser.add_argument(
        "--output",
        type=argparse.FileType("w", encoding="UTF-8"),
        default="-",
        help="Output file for solutions table. If set to '-' (default) will print to stdout.",
    )


def add_powerfit_fit_models_parser(subparsers):
    # TODO be consistent in docs with PowerFit vs powerfit
    parser = subparsers.add_parser("fit-models", help="Fit models based on PowerFit solutions")
    parser.add_argument("session_dir", help="Session directory containing PowerFit results")
    parser.add_argument(
        "--powerfit_run_id",
        type=int,
        default=None,
        help="ID of the PowerFit run to report on. If not provided, will use the all runs.",
    )
    parser.add_argument("--top", type=int, default=10, help="Number of top solutions to fit models for")
    parser.add_argument(
        "--output",
        type=argparse.FileType("w", encoding="UTF-8"),
        default="-",
        help="Output file for fitted model table. If set to '-' (default) will print to stdout.",
    )


def add_powerfit_list_runs_parser(subparsers):
    parser = subparsers.add_parser("list-runs", help="List all PowerFit runs in the session directory")
    parser.add_argument("session_dir", help="Session directory containing PowerFit results")


def add_powerfit_list_lcc_parser(subparsers):
    parser = subparsers.add_parser("list-lcc", help="List Local Cross Validation (lcc.mrc) files for PowerFit runs")
    parser.add_argument("session_dir", help="Session directory containing PowerFit results")


def add_powerfit_parser(subparsers):
    parser = subparsers.add_parser("powerfit", help="PowerFit related commands")
    powerfit_subparsers = parser.add_subparsers(dest="powerfit_command", required=True)
    add_powerfit_commands_parser(powerfit_subparsers)
    add_powerfit_run_parser(powerfit_subparsers)
    add_powerfit_report_parser(powerfit_subparsers)
    add_powerfit_fit_models_parser(powerfit_subparsers)
    add_powerfit_list_runs_parser(powerfit_subparsers)
    add_powerfit_list_lcc_parser(powerfit_subparsers)


def handler_powerfit_run(args):
    session_dir = Path(args.session_dir)
    powerfit_run_id = powerfit_runs(session_dir, PowerfitOptions.from_args(args))
    rprint(f"PowerFit run completed with ID: {powerfit_run_id}. Use this ID for reporting or fitting models.")


def handle_powerfit(args):
    if args.powerfit_command == "commands":
        handle_powerfit_commands(args)
    elif args.powerfit_command == "run":
        handler_powerfit_run(args)
    elif args.powerfit_command == "report":
        handler_powerfit_report(args)
    elif args.powerfit_command == "fit-models":
        handler_powerfit_fit_models(args)
    elif args.powerfit_command == "list-runs":
        handler_powerfit_list_runs(args)
    elif args.powerfit_command == "list-lcc":
        handler_powerfit_list_lcc(args)


def handle_powerfit_commands(args):
    session_dir = Path(args.session_dir)
    commands, powerfit_run_id = powerfit_commands(session_dir, PowerfitOptions.from_args(args))
    print("# Run the commands below in your own way", file=args.output)
    print("# When you are done", file=args.output)
    print(f"# in {Path().absolute()} directory", file=args.output)
    print(
        f"# run `protein-detective powerfit report {session_dir} {powerfit_run_id}` to show best solutions.",
        file=args.output,
    )
    for command in commands:
        print(command, file=args.output)


def handler_powerfit_report(args):
    session_dir = Path(args.session_dir)
    powerfit_run_id = args.powerfit_run_id

    all_solutions = powerfit_report(session_dir, powerfit_run_id)
    solutions = all_solutions.head(args.top)

    def array_to_str(arr):
        return ":".join(map(str, arr.flatten()))

    # Convert translation and rotation to : delimited string for CSV output
    solutions.loc[:, "translation"] = solutions["translation"].apply(array_to_str)
    solutions.loc[:, "rotation"] = solutions["rotation"].apply(array_to_str)

    solutions.to_csv(args.output, index=False)


def handler_powerfit_fit_models(args):
    session_dir = Path(args.session_dir)
    powerfit_run_id = args.powerfit_run_id
    top = args.top

    fitted = powerfit_fit_models(session_dir, powerfit_run_id, top)
    fitted.to_csv(args.output, index=False)


def handler_powerfit_list_runs(args):
    session_dir = Path(args.session_dir)
    with connect(session_dir, read_only=True) as con:
        runs = load_powerfit_runs(con)

    if len(runs) == 0:
        rprint("No PowerFit runs found.")
        return

    table = Table(title="PowerFit runs")
    table.add_column("ID", justify="right", style="cyan")
    table.add_column("Options", style="magenta")
    table.add_column("Density map (copy)", style="green")
    for row in runs:
        table.add_row(str(row[0]), str(row[1]), str(row[2]))
    rprint(table)


def handler_powerfit_list_lcc(args):
    session_dir = Path(args.session_dir)
    with connect(session_dir, read_only=True) as con:
        lcc_files = list_lcc_files(con)

    if not lcc_files:
        rprint("[yellow]No lcc.mrc files found. Please run at least one powerfit.[/yellow]")
        return

    table = Table(title="PowerFit LCC files")
    table.add_column("Run ID", justify="right", style="cyan")
    table.add_column("Structure", style="magenta")
    table.add_column("LCC file", style="green")
    for run_id, structure, lcc_file in lcc_files:
        table.add_row(str(run_id), structure, lcc_file)
    rprint(table)
