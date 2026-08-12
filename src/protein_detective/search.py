from csv import DictReader
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from cyclopts import Group, Parameter, validators
from cyclopts._path_type import StdioPath
from cyclopts.types import NonNegativeInt, PositiveInt
from protein_quest.cli.search import alphafold, complexes, pdbe, pdbe_quality, uniprot
from protein_quest.uniprot import Query
from rocrate_action_recorder import IOArgumentPath, IOArgumentPaths

from protein_detective.common_cli import Common, write_ro_crate

uniprot_group = Group.create_ordered("UniProt sub-search")
alphafold_group = Group.create_ordered("AlphaFold sub-search")
pdbe_group = Group.create_ordered("PDBe sub-search")
interaction_partners_group = Group.create_ordered("Interaction partners sub-search")


@dataclass
class AlphafoldOptions:
    """Options for the AlphaFold sub-search.

    Parameters:
        limit: Maximum number of AlphaFold entries to return.
            Use '0' to skip the AlphaFold sub-search.
    """

    limit: NonNegativeInt = 10_000


@dataclass
class PdbeOptions:
    """Options for the PDBe sub-search.

    Parameters:
        limit: Maximum number of PDBe entries to return.
            Use '0' to skip the PDBe sub-search.
        min_residues: Minimum chain length for PDBe.
        max_residues: Maximum chain length for PDBe.
        top_resolution_per_uniprot_accession: Best-N PDBe per UniProt.
    """

    limit: NonNegativeInt = 10_000
    min_residues: PositiveInt | None = None
    max_residues: PositiveInt | None = None
    top_resolution_per_uniprot_accession: PositiveInt = 5


@dataclass
class InteractionPartnerOptions:
    """Options for the interaction partners sub-search.

    Parameters:
        seed: UniProt ID to use as interaction partner seed.
            The search will be expanded to include structure identifiers of the found interaction partners.
            Can be specified multiple times.
        exclude: UniProt ID to exclude as found interaction partners.
            Can be specified multiple times.
        limit: Maximum number of interaction partners to return.
    """

    seed: Annotated[set[str], Parameter(negative="")] = field(default_factory=set)
    exclude: Annotated[set[str], Parameter(negative="")] = field(default_factory=set)
    limit: PositiveInt = 10_000


@Parameter(name="*")
@dataclass
class SearchOptions:
    """Options for the search workflow.

    Parameters:
        query: UniProt search query.
        limit_uniprot: Maximum number of UniProt accessions to return.
        alphafold: Options for the AlphaFold sub-search.
        pdbe: Options for the PDBe sub-search.
        interaction: Options for the interaction partners sub-search.
    """

    query: Annotated[Query, Parameter(name="*", group=uniprot_group)] = field(default_factory=Query)
    limit_uniprot: Annotated[PositiveInt, Parameter(group=uniprot_group)] = 10_000
    alphafold: Annotated[AlphafoldOptions, Parameter(group=alphafold_group)] = field(default_factory=AlphafoldOptions)
    pdbe: Annotated[PdbeOptions, Parameter(group=pdbe_group)] = field(default_factory=PdbeOptions)
    interaction: Annotated[InteractionPartnerOptions, Parameter(group=interaction_partners_group)] = field(
        default_factory=InteractionPartnerOptions
    )


def _create_interaction_partner_seeds_file(session_dir: Path, seeds: set[str]) -> StdioPath:
    seeds_path = StdioPath(session_dir / "interaction_partner_seeds.txt")
    with seeds_path.open("w") as f:
        for seed in sorted(seeds):
            f.write(seed + "\n")
    return seeds_path


def _add_complex_members_to_uniprot(
    complexes_path: StdioPath, uniprot_path: StdioPath, seeds: set[str], excludes: set[str]
) -> StdioPath:
    uniprot_accessions_of_partners = set()
    with complexes_path.open() as f:
        reader = DictReader(f)
        for complex_row in reader:
            members = complex_row["members"].split(";")
            uniprot_accessions_of_partners.update(members)

        # Exclude seeds and excludes from results
    uniprot_accessions_of_partners.difference_update(seeds)
    uniprot_accessions_of_partners.difference_update(excludes)

    with uniprot_path.open() as f:
        uniprot_accessions = {line.strip() for line in f if line.strip()}
    uniprot_accessions.update(uniprot_accessions_of_partners)
    uniprot_with_interaction_partners_path = StdioPath(uniprot_path.parent / "uniprot_with_interaction_partners.txt")
    with uniprot_with_interaction_partners_path.open("w") as f:
        for uniprot_accession in sorted(uniprot_accessions):
            f.write(uniprot_accession + "\n")
    return uniprot_with_interaction_partners_path


def _write_ro_crate(
    session_dir: Path,
    start_time: datetime,
    /,
    *,
    uniprot_path: StdioPath,
    alphafold_file: StdioPath | None,
    pdbe_path: StdioPath | None,
    pdbe_quality_file: StdioPath | None,
    seeds_path: StdioPath | None,
    complexes_path: StdioPath | None,
    uniprot_with_interaction_partners_path: StdioPath,
) -> None:
    ioargs = IOArgumentPaths(
        output_files=[
            IOArgumentPath(
                name="uniprot",
                path=uniprot_path,
                help="UniProt accessions",
            ),
        ]
    )
    if alphafold_file:
        ioargs.output_files.append(
            IOArgumentPath(
                name="alphafold",
                path=alphafold_file,
                help="AlphaFold identifiers",
            ),
        )
    if pdbe_path and pdbe_quality_file:
        ioargs.output_files.extend(
            [
                IOArgumentPath(
                    name="pdbe",
                    path=pdbe_path,
                    help="PDBe identifiers",
                ),
                IOArgumentPath(
                    name="pdbe_quality",
                    path=pdbe_quality_file,
                    help="PDBe validation quality reports",
                ),
            ]
        )
    if seeds_path and complexes_path:
        ioargs.output_files.append(
            IOArgumentPath(
                name="interaction_partner_seeds",
                path=seeds_path,
                help="Interaction partner seeds",
            )
        )
        ioargs.output_files.append(
            IOArgumentPath(
                name="complexes",
                path=complexes_path,
                help="Complexes of interaction partners",
            )
        )
        ioargs.output_files.append(
            IOArgumentPath(
                name="uniprot_with_interaction_partners",
                path=uniprot_with_interaction_partners_path,
                help=(
                    "UniProt accessions of "
                    f"{uniprot_path.relative_to(session_dir, walk_up=True)} "
                    "combined with uniprot accessions of interaction partners"
                ),
            )
        )
    write_ro_crate(
        session_dir,
        start_time,
        command_name="search",
        command_description="Search for candidate protein structures",
        ioargs=ioargs,
    )


def search(
    session_dir: Annotated[Path, Parameter(validator=validators.Path(file_okay=False, dir_okay=False))],
    /,
    *,
    options: SearchOptions | None = None,
    _: Common | None = None,
) -> None:
    """Search for candidate protein structures.

    * Searches for UniProt accessions, writes `<session_dir>/uniprot.txt`.
    * If interaction partner seeds are given, searches for interaction partners.
        and adds partners to the list of UniProt accessions.
        Writes `<session_dir>/interaction_partner_seeds.txt`, `<session_dir>/complexes.csv`
        and `<session_dir>/uniprot_with_interaction_partners.txt`.
    * Searches for AlphaFold structures for the UniProt accessions.
        Writes `<session_dir>/alphafold.csv`.
    * Searches for PDBe structures for the UniProt accessions.
        Writes `<session_dir>/pdbe.csv`.
    * Searches for PDBe validation quality reports for the found PDBe structures.
        Writes `<session_dir>/pdbe-quality.json`.
    * Writes `<session_dir>/ro-crate-metadata.json` to keep track of used arguments and its output files.

    Args:
        session_dir: RO-Crate session directory.
        options: Search options.
    """
    if options is None:
        options = SearchOptions()
    session_dir.mkdir(parents=True, exist_ok=True)

    start_time = datetime.now(tz=UTC)

    uniprot_path = StdioPath(session_dir / "uniprot.txt")
    uniprot(uniprot_path, query=options.query, limit=options.limit_uniprot)

    final_uniprot_path = uniprot_path
    seeds_path = None
    complexes_path = None
    if options.interaction.seed:
        complexes_path = StdioPath(session_dir / "complexes.csv")
        seeds_path = _create_interaction_partner_seeds_file(session_dir, options.interaction.seed)

        complexes(
            seeds_path,
            complexes_path,
            limit=options.interaction.limit,
        )

        uniprot_with_interaction_partners_path = _add_complex_members_to_uniprot(
            complexes_path=complexes_path,
            uniprot_path=uniprot_path,
            seeds=options.interaction.seed,
            excludes=options.interaction.exclude,
        )
        final_uniprot_path = uniprot_with_interaction_partners_path

    if options.alphafold.limit > 0:
        alphafold_file = StdioPath(session_dir / "alphafold.csv")
        alphafold(
            final_uniprot_path,
            alphafold_file,
            limit=options.alphafold.limit,
        )
    else:
        alphafold_file = None

    if options.pdbe.limit > 0:
        pdbe_path = StdioPath(session_dir / "pdbe.csv")
        pdbe(
            final_uniprot_path,
            pdbe_path,
            limit=options.pdbe.limit,
            min_residues=options.pdbe.min_residues,
            max_residues=options.pdbe.max_residues,
            top_resolution_per_uniprot_accession=options.pdbe.top_resolution_per_uniprot_accession,
        )

        pdbe_quality_file = StdioPath(session_dir / "pdbe-quality.json")
        pdbe_quality(
            pdbe_path,
            pdbe_quality_file,
        )
    else:
        pdbe_path = None
        pdbe_quality_file = None

    _write_ro_crate(
        session_dir,
        start_time,
        uniprot_path=uniprot_path,
        alphafold_file=alphafold_file,
        pdbe_path=pdbe_path,
        pdbe_quality_file=pdbe_quality_file,
        seeds_path=seeds_path,
        complexes_path=complexes_path,
        uniprot_with_interaction_partners_path=final_uniprot_path,
    )
