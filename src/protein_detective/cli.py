import argparse
import logging
from pathlib import Path

from protein_detective.uniprot import Query
from protein_detective.workflow import retrieve_structures


def add_retrieve_parser(subparsers):
    retrieve_parser = subparsers.add_parser("retrieve", help="Retrieve structures for a UniProt query")
    retrieve_parser.add_argument("session_dir", help="Session directory to store results")
    retrieve_parser.add_argument("--taxon-id", type=str, help="NCBI Taxon ID")
    retrieve_parser.add_argument(
        "--reviewed",
        type=bool,
        action=argparse.BooleanOptionalAction,
        help="Reviewed=swissprot, no-reviewed=trembl. Default is uniprot=swissprot+trembl.",
        default=None,
    )
    retrieve_parser.add_argument("--subcellular-location-uniprot", type=str, help="Subcellular location (UniProt)")
    retrieve_parser.add_argument(
        "--subcellular-location-go", type=str, help="Subcellular location (GO term, e.g. GO:0005737)"
    )
    retrieve_parser.add_argument(
        "--molecular-function-go", type=str, help="Molecular function (GO term, e.g. GO:0003677)"
    )
    retrieve_parser.add_argument("--limit", type=int, default=10_000, help="Limit number of results")
    return retrieve_parser


def handle_retrieve(args):
    query = Query(
        taxon_id=args.taxon_id,
        reviewed=args.reviewed,
        subcellular_location_uniprot=args.subcellular_location_uniprot,
        subcellular_location_go=args.subcellular_location_go,
        molecular_function_go=args.molecular_function_go,
    )
    session_dir = Path(args.session_dir)
    db_path = retrieve_structures(query, session_dir, limit=args.limit)
    logger = logging.getLogger("protein_detective.cli")
    logger.info(f"Structures retrieved and stored in: {db_path}")


def main():
    parser = argparse.ArgumentParser(description="Protein Detective CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)
    add_retrieve_parser(subparsers)

    args = parser.parse_args()

    if args.command == "retrieve":
        handle_retrieve(args)


if __name__ == "__main__":
    main()
