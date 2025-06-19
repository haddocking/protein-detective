import argparse
import logging
from pathlib import Path

from powerfit_em.powerfit import make_parser as make_powerfit_parser
from rich import print as rprint
from rich.logging import RichHandler
from rich.table import Table

from protein_detective.alphafold import downloadable_formats
from protein_detective.alphafold.density import DensityFilterQuery
from protein_detective.db import connect, load_powerfit_runs
from protein_detective.powerfit.options import PowerfitOptions
from protein_detective.uniprot import Query
from protein_detective.workflow import (
    density_filter,
    powerfit_commands,
    powerfit_fit_models,
    powerfit_report,
    powerfit_runs,
    prune_pdbs,
    retrieve_structures,
    search_structures_in_uniprot,
    what_retrieve_choices,
)


def add_search_parser(subparsers):
    parser = subparsers.add_parser("search", help="Search UniProt for structures")
    parser.add_argument("session_dir", help="Session directory to store results")
    parser.add_argument("--taxon-id", type=str, help="NCBI Taxon ID")
    parser.add_argument(
        "--reviewed",
        action=argparse.BooleanOptionalAction,
        help="Reviewed=swissprot, no-reviewed=trembl. Default is uniprot=swissprot+trembl.",
        default=None,
    )
    parser.add_argument("--subcellular-location-uniprot", type=str, help="Subcellular location (UniProt)")
    parser.add_argument("--subcellular-location-go", type=str, help="Subcellular location (GO term, e.g. GO:0005737)")
    parser.add_argument("--molecular-function-go", type=str, help="Molecular function (GO term, e.g. GO:0003677)")
    parser.add_argument("--limit", type=int, default=10_000, help="Limit number of results")


def add_retrieve_parser(subparsers):
    parser = subparsers.add_parser("retrieve", help="Retrieve structures")
    parser.add_argument("session_dir", help="Session directory to store results")
    parser.add_argument(
        "--what",
        type=str,
        action="append",
        choices=sorted(what_retrieve_choices),
        help="What to retrieve. Can be specified multiple times. Default is pdbe and alphafold.",
    )
    parser.add_argument(
        "--what-af-formats",
        type=str,
        action="append",
        choices=sorted(downloadable_formats),
        help="AlphaFold formats to retrieve. Can be specified multiple times. Default is 'pdb'.",
    )


def add_density_filter_parser(subparsers):
    parser = subparsers.add_parser("density-filter", help="Filter AlphaFoldDB structures based on density confidence")
    parser.add_argument("session_dir", help="Session directory for input and output")
    parser.add_argument("--confidence-threshold", type=float, default=70.0, help="pLDDT confidence threshold (0-100)")
    parser.add_argument(
        "--min-residues", type=int, default=0, help="Minimum number of residues above confidence threshold"
    )
    parser.add_argument(
        "--max-residues",
        type=int,
        default=1_000_000,
        help="Maximum number of residues above confidence threshold.",
    )


def add_prune_pdbs_parser(subparsers):
    parser = subparsers.add_parser(
        "prune-pdbs", help="Prune PDBe files to keep only the first chain and rename it to A"
    )
    parser.add_argument("session_dir", help="Session directory containing PDB files")


def add_powerfit_commands_parser(subparsers):
    # Add the commands sub-command
    parser = subparsers.add_parser("commands", help="Generate PowerFit commands for PDB files in the session directory")
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

    # Add all arguments from PowerFit options
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


def add_powerfit_parser(subparsers):
    parser = subparsers.add_parser("powerfit", help="PowerFit related commands")
    powerfit_subparsers = parser.add_subparsers(dest="powerfit_command", required=True)
    add_powerfit_commands_parser(powerfit_subparsers)
    add_powerfit_run_parser(powerfit_subparsers)
    add_powerfit_report_parser(powerfit_subparsers)
    add_powerfit_fit_models_parser(powerfit_subparsers)
    add_powerfit_list_runs_parser(powerfit_subparsers)


def handle_search(args):
    query = Query(
        taxon_id=args.taxon_id,
        reviewed=args.reviewed,
        subcellular_location_uniprot=args.subcellular_location_uniprot,
        subcellular_location_go=args.subcellular_location_go,
        molecular_function_go=args.molecular_function_go,
    )
    session_dir = Path(args.session_dir)
    nr_uniprot, nr_pdbes, nr_afs = search_structures_in_uniprot(query, session_dir, limit=args.limit)
    rprint(
        f"Search completed: {nr_uniprot} UniProt entries found, "
        f"{nr_pdbes} PDBe structures, {nr_afs} AlphaFold structures."
    )


def handle_retrieve(args):
    session_dir = Path(args.session_dir)
    download_dir, nr_pdbes, nr_afs = retrieve_structures(
        session_dir,
        what=set(args.what) if args.what else None,
        what_af_formats=set(args.what_af_formats) if args.what_af_formats else None,
    )
    rprint(
        "Structures retrieved successfully: "
        f"{nr_pdbes} PDBe structures, {nr_afs} AlphaFold structures downloaded to {download_dir}"
    )


def handle_density_filter(args):
    query = DensityFilterQuery(
        confidence=args.confidence_threshold,
        min_threshold=args.min_residues,
        max_threshold=args.max_residues,
    )
    session_dir = Path(args.session_dir)
    result = density_filter(session_dir, query)
    rprint(f"Filtered {result.nr_kept} structures, written to {result.density_filtered_dir} directory.")
    rprint(f"Discarded {result.nr_discarded} structures based on density confidence.")


def handle_prune_pdbs(args):
    session_dir = Path(args.session_dir)
    single_chain_dir, nr_files = prune_pdbs(session_dir)
    rprint(f"Written {nr_files} PDB files to {single_chain_dir} directory.")


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
    with connect(session_dir) as con:
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


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Protein Detective CLI", prog="protein-detective")
    parser.add_argument("--log-level", default="WARNING", choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])

    subparsers = parser.add_subparsers(dest="command", required=True)
    add_search_parser(subparsers)
    add_retrieve_parser(subparsers)
    add_density_filter_parser(subparsers)
    add_prune_pdbs_parser(subparsers)
    add_powerfit_parser(subparsers)
    return parser


def main():
    parser = make_parser()

    args = parser.parse_args()

    logging.basicConfig(level=args.log_level, handlers=[RichHandler(show_level=False)])

    if args.command == "search":
        handle_search(args)
    elif args.command == "retrieve":
        handle_retrieve(args)
    elif args.command == "density-filter":
        handle_density_filter(args)
    elif args.command == "prune-pdbs":
        handle_prune_pdbs(args)
    elif args.command == "powerfit":
        handle_powerfit(args)


if __name__ == "__main__":
    main()
