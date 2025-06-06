import argparse
from pathlib import Path

from rich import print  # noqa: A004

from protein_detective.alphafold.density import DensityFilterQuery
from protein_detective.uniprot import Query
from protein_detective.workflow import (
    density_filter,
    prune_pdbs,
    retrieve_structures,
    search_structures_in_uniprot,
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
    print(
        f"Search completed: {nr_uniprot} UniProt entries found, "
        f"{nr_pdbes} PDBe structures, {nr_afs} AlphaFold structures."
    )


def handle_retrieve(args):
    session_dir = Path(args.session_dir)
    download_dir, nr_pdbes, nr_afs = retrieve_structures(session_dir)
    print(
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
    print(f"Filtered {result.nr_kept} structures, written to {result.density_filtered_dir} directory.")
    print(f"Discarded {result.nr_discarded} structures based on density confidence.")


def handle_prune_pdbs(args):
    session_dir = Path(args.session_dir)
    single_chain_dir, nr_files = prune_pdbs(session_dir)
    print(f"Written {nr_files} PDB files to {single_chain_dir} directory.")


def main():
    parser = argparse.ArgumentParser(description="Protein Detective CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)
    add_search_parser(subparsers)
    add_retrieve_parser(subparsers)
    add_density_filter_parser(subparsers)
    add_prune_pdbs_parser(subparsers)

    args = parser.parse_args()

    if args.command == "search":
        handle_search(args)
    elif args.command == "retrieve":
        handle_retrieve(args)
    elif args.command == "density-filter":
        handle_density_filter(args)
    elif args.command == "prune-pdbs":
        handle_prune_pdbs(args)


if __name__ == "__main__":
    main()
