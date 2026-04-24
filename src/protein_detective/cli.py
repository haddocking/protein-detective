import argparse
import logging
import sys
from pathlib import Path
from textwrap import dedent

from protein_quest.alphafold.confidence import ConfidenceFilterQuery
from protein_quest.alphafold.fetch import downloadable_formats
from protein_quest.converter import converter
from protein_quest.filters.residues import ResidueFilterStatistics
from protein_quest.filters.ss import SecondaryStructureFilterQuery
from protein_quest.io import convert_to_cif_file, glob_structure_files, read_structure
from protein_quest.structure import chains_in_structure, structure2uniprot_accessions
from protein_quest.utils import CopyMethod, copy_methods
from rich.console import Console
from rich.logging import RichHandler
from rich.progress import track
from rich_argparse import RawDescriptionRichHelpFormatter, RichHelpFormatter

from protein_detective.__version__ import __version__
from protein_detective.db import connect, save_filter, save_filtered_structures, save_uniprot_accessions
from protein_detective.filter import FilteredStructure, FilterOptions
from protein_detective.powerfit.cli import (
    add_powerfit_parser,
    handle_powerfit,
)
from protein_detective.search import UniprotQuery
from protein_detective.workflow import (
    filter_structures,
    retrieve_structures,
    search_structures_in_uniprot,
    what_retrieve_choices,
)

console = Console(stderr=True)
rprint = console.print


def add_search_parser(subparsers):
    parser = subparsers.add_parser("search", help="Search UniProt for structures", formatter_class=RichHelpFormatter)
    parser.add_argument("session_dir", help="Session directory to store results")
    # Protein quest based arguments
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
    parser.add_argument("--min-sequence-length", type=int, help="Minimum length of the canonical sequence.")
    parser.add_argument("--max-sequence-length", type=int, help="Maximum length of the canonical sequence.")

    # Detective only arguments
    parser.add_argument(
        "--interaction-partner-seed",
        type=str,
        action="append",
        help=dedent("""\
            UniProt ID to use as interaction partner seed.
            The search will be expanded to include structures identifiers of the found interaction partners.
            Can be specified multiple times.
        """),
    )
    parser.add_argument(
        "--interaction-partner-exclude",
        type=str,
        action="append",
        help="UniProt ID to exclude as found interaction partners. Can be specified multiple times.",
    )
    parser.add_argument(
        "--min-residues",
        type=int,
        help="Minimum number of residues required in the chain mapped to the UniProt accession.",
    )
    parser.add_argument(
        "--max-residues",
        type=int,
        help="Maximum number of residues allowed in chain mapped to the UniProt accession.",
    )

    parser.add_argument("--limit", type=int, default=10_000, help="Limit number of results")


def add_retrieve_parser(subparsers):
    parser = subparsers.add_parser("retrieve", help="Retrieve structures", formatter_class=RichHelpFormatter)
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
      For AlphaFold structures writes new files with low confidence residues (below threshold) removed
    - Number of residues in secondary structure (helices and sheets)
    - For determining the fraction or number of Secondary Structure elements see the following notebook: https://www.bonvinlab.org/protein-detective/SSE_elements.html

    """)
    parser = subparsers.add_parser(
        "filter",
        help="Filter structures",
        description=description,
        formatter_class=RawDescriptionRichHelpFormatter,
    )
    parser.add_argument("session_dir", type=Path, help="Session directory to store results")

    parser.add_argument(
        "--confidence-threshold",
        type=float,
        default=70.0,
        help="pLDDT confidence threshold (0-100) for AlphaFold structures. Default is 70.0.",
    )

    parser.add_argument("--min-residues", type=int, default=0, help="Minimum number of residues in chain A")
    parser.add_argument(
        "--max-residues",
        type=int,
        default=sys.maxsize,
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


def add_import_structures_parser(subparsers: argparse._SubParsersAction):
    description = dedent("""\
        Import structures from a directory into the session.

        The directory should contain structure files in PDB or mmCIF format.

        This can be used to import structures obtained from other sources,
        or to re-import structures after filtering with external tools.
    """)
    parser = subparsers.add_parser(
        "import-structures",
        help="Import structures from a directory into the session",
        description=description,
        formatter_class=RawDescriptionRichHelpFormatter,
    )
    parser.add_argument("structures_dir", type=Path, help="Directory containing structure files to import")
    parser.add_argument("session_dir", type=Path, help="Session directory to store results")
    parser.add_argument(
        "--copy-method",
        choices=copy_methods,
        default="hardlink",
        help=(
            "Method to use for importing files. Default is 'hardlink'. "
            "If 'copy', files will be copied. If 'symlink', symbolic links will be created. "
            "If 'hardlink', hard links will be created (unavailable on Windows)."
        ),
    )
    parser.add_argument(
        "--strict",
        dest="strict",
        action="store_true",
        help=(
            "Raise error if structure files do not meet expected criteria (single chain A, single UniProt accession)."
            " Files that do not meet criteria will be skipped with a warning."
        ),
    )


def handle_search(args):
    query = converter.structure(
        {
            "taxon_id": args.taxon_id,
            "reviewed": args.reviewed,
            "subcellular_location_uniprot": args.subcellular_location_uniprot,
            "subcellular_location_go": args.subcellular_location_go,
            "molecular_function_go": args.molecular_function_go,
            "min_sequence_length": args.min_sequence_length,
            "max_sequence_length": args.max_sequence_length,
            "interaction_partner_seeds": args.interaction_partner_seed or [],
            "interaction_partner_excludes": args.interaction_partner_exclude or [],
            "min_residues": args.min_residues,
            "max_residues": args.max_residues,
        },
        UniprotQuery,
    )
    session_dir = Path(args.session_dir)
    result = search_structures_in_uniprot(query, session_dir, limit=args.limit)
    rprint(
        f"Search completed: {result.nr_uniprot_accessions} UniProt entries found, "
        f"{result.nr_pdbs} PDBe structures, {result.nr_prot2pdb} UniProt to PDB mappings, "
        f"{result.nr_afs} AlphaFold structures."
    )
    if query.interaction_partner_seeds:
        rprint(f"Included {result.nr_interaction_partners} Uniprot entries found as interaction partners.")


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
    cf_query = converter.structure(
        {
            "confidence": args.confidence_threshold,
            "min_residues": args.min_residues,
            "max_residues": args.max_residues,
        },
        ConfidenceFilterQuery,
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
    query = FilterOptions(confidence=cf_query, secondary_structure=ss_query)
    scheduler_address: None | str = args.scheduler_address

    f_dir, total_results = filter_structures(session_dir, query, scheduler_address)

    nr_passed = len([r for r in total_results if r.passed])
    rprint(f"Filtering complete, {nr_passed} structure files in {f_dir} directory.")


def handle_import_structures(args):
    structures_dir: Path = args.structures_dir
    session_dir: Path = args.session_dir
    copy_method: CopyMethod = args.copy_method
    import_dir: Path = session_dir / "imported_structures"
    import_dir.mkdir(exist_ok=True, parents=True)

    results: list[FilteredStructure] = []
    for structure_file in track(
        glob_structure_files(structures_dir), description="Importing structures...", console=console
    ):
        target_file = convert_to_cif_file(
            structure_file.resolve(), import_dir, copy_method=copy_method, output_format=".cif.gz"
        )
        structure = read_structure(target_file)
        try:
            pdb_id = structure.info["_entry.id"]
        except KeyError:
            pdb_id = None
        chains = chains_in_structure(structure)
        chain_ids = {chain.name for chain in chains}
        if chain_ids != {"A"}:
            msg = f"Structure file {structure_file} contains chains {chain_ids}, expected single chain A."
            msg += " Use `protein-quest filter chain` to fix this."
            if args.strict:
                raise ValueError(msg)
            console.print(f"Warning: {msg} Skipping file.", style="yellow")
            continue
        nr_residues = len(next(iter(chains)))
        uniprot_accessions = structure2uniprot_accessions(structure)
        if len(uniprot_accessions) != 1:
            msg = f"Structure file {structure_file} contains {uniprot_accessions} uniprot accessions, expected 1."
            msg += " Use `protein-quest filter uniprot` to fix this."
            if args.strict:
                raise ValueError(msg)
            console.print(f"Warning: {msg} Skipping file.", style="yellow")
            continue

        results.append(
            FilteredStructure(
                residue=ResidueFilterStatistics(
                    input_file=structure_file.absolute().relative_to(session_dir.absolute(), walk_up=True),
                    passed=True,
                    output_file=target_file.relative_to(session_dir),
                    residue_count=nr_residues,
                ),
                pdb_id=pdb_id,
                uniprot_accession=next(iter(uniprot_accessions)),
            )
        )

    with connect(session_dir) as con:
        uniprot_accessions = {r.uniprot_accession for r in results}
        save_uniprot_accessions(uniprot_accessions, con)
        filter_options = FilterOptions(
            confidence=ConfidenceFilterQuery(),
            secondary_structure=SecondaryStructureFilterQuery(),
        )
        filter_id = save_filter(filter_options, con)
        save_filtered_structures(results, filter_id, con)

    console.print(f"Imported {len(results)} structure files into session at {import_dir}", style="green")


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Protein Detective CLI", prog="protein-detective", formatter_class=RichHelpFormatter
    )
    parser.add_argument("--log-level", default="WARNING", choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True)
    add_search_parser(subparsers)
    add_retrieve_parser(subparsers)
    add_filter_parser(subparsers)
    add_import_structures_parser(subparsers)
    add_powerfit_parser(subparsers)
    return parser


def main():
    parser = make_parser()

    args = parser.parse_args()

    logging.basicConfig(level=args.log_level, handlers=[RichHandler(show_level=False, console=console)])

    if args.command == "search":
        handle_search(args)
    elif args.command == "retrieve":
        handle_retrieve(args)
    elif args.command == "filter":
        handle_filter(args)
    elif args.command == "powerfit":
        handle_powerfit(args)
    elif args.command == "import-structures":
        handle_import_structures(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
