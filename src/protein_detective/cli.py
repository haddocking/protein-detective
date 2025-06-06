import argparse
from pathlib import Path

from rich import print as rprint

from protein_detective.alphafold import downloadable_formats
from protein_detective.alphafold.density import DensityFilterQuery
from protein_detective.powerfit.argparser import PowerfitOptions, add_powerfit_cli_parser
from protein_detective.uniprot import Query
from protein_detective.workflow import (
    density_filter,
    powerfit_commands,
    prune_pdbs,
    retrieve_structures,
    search_structures_in_uniprot,
    what_retrieve_choices,
)


def add_search_parser(subparsers):
    search_parser = subparsers.add_parser("search", help="Search UniProt for structures")
    search_parser.add_argument("session_dir", help="Session directory to store results")
    search_parser.add_argument("--taxon-id", type=str, help="NCBI Taxon ID")
    search_parser.add_argument(
        "--reviewed",
        type=bool,
        action=argparse.BooleanOptionalAction,
        help="Reviewed=swissprot, no-reviewed=trembl. Default is uniprot=swissprot+trembl.",
        default=None,
    )
    search_parser.add_argument("--subcellular-location-uniprot", type=str, help="Subcellular location (UniProt)")
    search_parser.add_argument(
        "--subcellular-location-go", type=str, help="Subcellular location (GO term, e.g. GO:0005737)"
    )
    search_parser.add_argument(
        "--molecular-function-go", type=str, help="Molecular function (GO term, e.g. GO:0003677)"
    )
    search_parser.add_argument("--limit", type=int, default=10_000, help="Limit number of results")
    return search_parser


def add_retrieve_parser(subparsers):
    retrieve_parser = subparsers.add_parser("retrieve", help="Retrieve structures")
    retrieve_parser.add_argument("session_dir", help="Session directory to store results")
    retrieve_parser.add_argument(
        "--what",
        type=str,
        action="append",
        choices=sorted(what_retrieve_choices),
        help="What to retrieve. Can be specified multiple times. Default is pdbe and alphafold.",
    )
    retrieve_parser.add_argument(
        "--what-af-formats",
        type=str,
        action="append",
        choices=sorted(downloadable_formats),
        help="AlphaFold formats to retrieve. Can be specified multiple times. Default is 'pdb'.",
    )
    return retrieve_parser


def add_density_filter_parser(subparsers):
    density_filter_parser = subparsers.add_parser(
        "density-filter", help="Filter AlphaFoldDB structures based on density confidence"
    )
    density_filter_parser.add_argument("session_dir", help="Session directory for input and output")
    density_filter_parser.add_argument(
        "--confidence-threshold", type=float, default=70.0, help="pLDDT confidence threshold (0-100)"
    )
    density_filter_parser.add_argument(
        "--min-residues", type=int, default=0, help="Minimum number of residues above confidence threshold"
    )
    density_filter_parser.add_argument(
        "--max-residues",
        type=int,
        default=1_000_000,
        help="Maximum number of residues above confidence threshold.",
    )
    return density_filter_parser


def add_prune_pdbs_parser(subparsers):
    prune_pdbs_parser = subparsers.add_parser(
        "prune-pdbs", help="Prune PDBe files to keep only the first chain and rename it to A"
    )
    prune_pdbs_parser.add_argument("session_dir", help="Session directory containing PDB files")
    return prune_pdbs_parser


def add_powerfit_commands_parser(subparsers):
    # Add the commands sub-command
    commands_parser = subparsers.add_parser(
        "commands", help="Generate PowerFit commands for PDB files in the session directory"
    )
    add_powerfit_cli_parser(commands_parser)


def add_powerfit_parser(subparsers):
    powerfit_parser = subparsers.add_parser("powerfit", help="PowerFit related commands")
    powerfit_subparsers = powerfit_parser.add_subparsers(dest="powerfit_command", required=True)
    add_powerfit_commands_parser(powerfit_subparsers)

    return powerfit_parser


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


def handle_powerfit(args):
    if args.powerfit_command == "commands":
        handle_powerfit_commands(args)


def handle_powerfit_commands(args):
    commands = powerfit_commands(PowerfitOptions.from_args(args))
    print("# Run the commands below in your own way", file=args.output)
    print("# When you are done", file=args.output)
    print(f"# in {Path().absolute()} directory", file=args.output)
    print(f"# run `protein-detective powerfit ingest {args.session_dir}` to parse the results.", file=args.output)
    # TODO capture PowerfitOptions in db
    # each options set could have own id that must be passed to ingest command
    # TODO make ingest command that
    # 1. fills db to can query all powerfit/*/solutions.out
    # 2. Store paths to top 10 pdb files in db
    # 3. Store path to lcc.mrc in db
    # 4. Map powerfit output dir back to pdb file in db
    for command in commands:
        print(command, file=args.output)


def main():
    parser = argparse.ArgumentParser(description="Protein Detective CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)
    add_search_parser(subparsers)
    add_retrieve_parser(subparsers)
    add_density_filter_parser(subparsers)
    add_prune_pdbs_parser(subparsers)
    add_powerfit_parser(subparsers)

    args = parser.parse_args()

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
