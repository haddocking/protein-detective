import argparse
import logging
from pathlib import Path
from textwrap import dedent

from protein_quest.alphafold.confidence import ConfidenceFilterQuery
from protein_quest.alphafold.fetch import downloadable_formats
from protein_quest.converter import converter
from protein_quest.ss import SecondaryStructureFilterQuery
from protein_quest.uniprot import Query
from rich import print as rprint
from rich.logging import RichHandler

from protein_detective.__version__ import __version__
from protein_detective.powerfit.cli import (
    add_powerfit_parser,
    handle_powerfit,
)
from protein_detective.workflow import (
    confidence_filter,
    filter_structures,
    is_actionable_ss_query,
    prune_pdbs,
    retrieve_structures,
    search_structures_in_uniprot,
    secondary_structure_filter,
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
    parser.add_argument(
        "--subcellular-location-go",
        type=str,
        action="append",
        help="Subcellular location (GO term, e.g. GO:0005737). Can be specified multiple times.",
    )
    parser.add_argument(
        "--molecular-function-go",
        type=str,
        action="append",
        help="Molecular function (GO term, e.g. GO:0003677). Can be specified multiple times.",
    )
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
        help="AlphaFold formats to retrieve. Can be specified multiple times. Default is 'cif'.",
    )


def add_filter_parser(subparsers: argparse._SubParsersAction):
    description = dedent("""\
    Filter structures based on
                         
    - For PDBe structures the chain of Uniprot protein is written as chain A.
    - For AlphaFold structures filter by confidence (pLDDT) threshold
    - Number of residues in chain A
      - For AlphaFold structures writes new files with low confidence residues (below threshold) removed
    - Number of residues in secondary structure (helices and sheets)
    """)
    parser = subparsers.add_parser(
        "filter",
        help="Filter structures",
        description=description,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("session_dir", type=Path, help="Session directory to store results")

    parser.add_argument(
        "--confidence-threshold",
        type=float,
        default=70.0,
        help="pLDDT confidence threshold (0-100) for AlphaFold structures",
    )

    parser.add_argument("--min-residues", type=int, default=0, help="Minimum number of residues in chain A")
    parser.add_argument(
        "--max-residues",
        type=int,
        default=1_000_000,
        help="Maximum number of residues in chain A",
    )

    parser.add_argument("--abs-min-helix-residues", type=int, help="Minimum number residues in helices")
    parser.add_argument("--abs-max-helix-residues", type=int, help="Maximum number residues in helices")
    parser.add_argument("--abs-min-sheet-residues", type=int, help="Minimum number residues in sheets")
    parser.add_argument("--abs-max-sheet-residues", type=int, help="Maximum number residues in sheets")
    parser.add_argument(
        "--ratio-min-helix-residues", type=float, help="Minimum number residues in helices (fraction of total)"
    )
    parser.add_argument(
        "--ratio-max-helix-residues", type=float, help="Maximum number residues in helices (fraction of total)"
    )
    parser.add_argument(
        "--ratio-min-sheet-residues", type=float, help="Minimum number residues in sheets (fraction of total)"
    )
    parser.add_argument(
        "--ratio-max-sheet-residues", type=float, help="Maximum number residues in sheets (fraction of total)"
    )

    parser.add_argument(
        "--scheduler-address",
        help="Address of the Dask scheduler to connect to. If not provided, will create a local cluster.",
    )


def handle_search(args):
    query = Query(
        taxon_id=args.taxon_id,
        reviewed=args.reviewed,
        subcellular_location_uniprot=args.subcellular_location_uniprot,
        subcellular_location_go=args.subcellular_location_go,
        molecular_function_go=args.molecular_function_go,
    )
    session_dir = Path(args.session_dir)
    nr_uniprot, nr_pdbes, nr_prot2pdbes, nr_afs = search_structures_in_uniprot(query, session_dir, limit=args.limit)
    rprint(
        f"Search completed: {nr_uniprot} UniProt entries found, "
        f"{nr_pdbes} PDBe structures, {nr_prot2pdbes} UniProt to PDB mappings, "
        f"{nr_afs} AlphaFold structures."
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


def handle_filter(args):
    session_dir: Path = args.session_dir
    cf_query = ConfidenceFilterQuery(
        confidence=args.confidence_threshold,
        min_residues=args.min_residues,
        max_residues=args.max_residues,
    )
    ss_query = converter.structure(
        {
            "abs_min_helix_residues": args.abs_min_helix_residues,
            "abs_max_helix_residues": args.abs_max_helix_residues,
            "abs_min_sheet_residues": args.abs_min_sheet_residues,
            "abs_max_sheet_residues": args.abs_max_sheet_residues,
            "ratio_min_helix_residues": args.ratio_min_helix_residues,
            "ratio_max_helix_residues": args.ratio_max_helix_residues,
            "ratio_min_sheet_residues": args.ratio_min_sheet_residues,
            "ratio_max_sheet_residues": args.ratio_max_sheet_residues,
        },
        SecondaryStructureFilterQuery,
    )
    scheduler_address: None | str = args.scheduler_address
    filter_structures(session_dir, cf_query, ss_query, scheduler_address)


def handle_confidence_filter(args):
    cf_query = ConfidenceFilterQuery(
        confidence=args.confidence_threshold,
        min_residues=args.min_residues,
        max_residues=args.max_residues,
    )
    session_dir = Path(args.session_dir)
    ss_query = converter.structure(
        {
            "abs_min_helix_residues": args.abs_min_helix_residues,
            "abs_max_helix_residues": args.abs_max_helix_residues,
            "abs_min_sheet_residues": args.abs_min_sheet_residues,
            "abs_max_sheet_residues": args.abs_max_sheet_residues,
            "ratio_min_helix_residues": args.ratio_min_helix_residues,
            "ratio_max_helix_residues": args.ratio_max_helix_residues,
            "ratio_min_sheet_residues": args.ratio_min_sheet_residues,
            "ratio_max_sheet_residues": args.ratio_max_sheet_residues,
        },
        SecondaryStructureFilterQuery,
    )
    if is_actionable_ss_query(ss_query):
        rprint("Filtering on confidence")
        result = confidence_filter(session_dir, cf_query)
        rprint(f"Filtered {result.nr_kept} structures, written to {result.filtered_dir} directory.")
        rprint(f"Discarded {result.nr_discarded} structures based on confidence.")
        rprint("Filtering on secondary structure")
        sresult = secondary_structure_filter(session_dir, result.filtered_dir, ss_query)
        rprint(f"Filtered {sresult.nr_kept} structures, written to {sresult.filtered_dir} directory.")
        rprint(f"Discarded {sresult.nr_discarded} structures based on secondary structure.")
    else:
        rprint("Filtering on confidence")
        result = confidence_filter(session_dir, cf_query)
        rprint(f"Filtered {result.nr_kept} structures, written to {result.filtered_dir} directory.")
        rprint(f"Discarded {result.nr_discarded} structures based on confidence.")


def handle_prune_pdbs(args):
    session_dir = Path(args.session_dir)
    ss_query = converter.structure(
        {
            "abs_min_helix_residues": args.abs_min_helix_residues,
            "abs_max_helix_residues": args.abs_max_helix_residues,
            "abs_min_sheet_residues": args.abs_min_sheet_residues,
            "abs_max_sheet_residues": args.abs_max_sheet_residues,
            "ratio_min_helix_residues": args.ratio_min_helix_residues,
            "ratio_max_helix_residues": args.ratio_max_helix_residues,
            "ratio_min_sheet_residues": args.ratio_min_sheet_residues,
            "ratio_max_sheet_residues": args.ratio_max_sheet_residues,
        },
        SecondaryStructureFilterQuery,
    )
    if is_actionable_ss_query(ss_query):
        rprint("Pruning PDBs")
        single_chain_dir, nr_files = prune_pdbs(
            session_dir,
            min_residues=args.min_residues,
            max_residues=args.max_residues,
            scheduler_address=args.scheduler_address,
        )
        rprint(f"Written {nr_files} PDB files to {single_chain_dir} directory.")

        rprint("Filtering on secondary structure")
        sresult = secondary_structure_filter(session_dir, single_chain_dir, ss_query)
        rprint(f"Filtered {sresult.nr_kept} structures based on secondary structure")
        rprint(f"Discarded {sresult.nr_discarded} structures based on secondary structure.")
        rprint(f"Written to {sresult.filtered_dir} directory.")
    else:
        single_chain_dir, nr_files = prune_pdbs(
            session_dir,
            min_residues=args.min_residues,
            max_residues=args.max_residues,
            scheduler_address=args.scheduler_address,
        )
        rprint(f"Written {nr_files} PDB files to {single_chain_dir} directory.")


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Protein Detective CLI", prog="protein-detective")
    parser.add_argument("--log-level", default="WARNING", choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True)
    add_search_parser(subparsers)
    add_retrieve_parser(subparsers)
    add_filter_parser(subparsers)
    add_powerfit_parser(subparsers)
    return parser


def main():
    # TODO add rich-argparse
    parser = make_parser()

    args = parser.parse_args()

    logging.basicConfig(level=args.log_level, handlers=[RichHandler(show_level=False)])

    if args.command == "search":
        handle_search(args)
    elif args.command == "retrieve":
        handle_retrieve(args)
    elif args.command == "filter":
        handle_filter(args)
    elif args.command == "powerfit":
        handle_powerfit(args)


if __name__ == "__main__":
    main()
