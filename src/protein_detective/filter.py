from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from cyclopts import Group, Parameter, validators
from cyclopts.types import StdioPath
from protein_quest.cli.convert import structures
from protein_quest.cli.filter import chain, combined, secondary_structure
from protein_quest.filters.combined import CombinedFilterQuery
from protein_quest.filters.ss import SecondaryStructureFilterQuery
from protein_quest.utils import copyfile
from rocrate_action_recorder import IOArgumentPath, IOArgumentPaths

from protein_detective.common_cli import Common, write_ro_crate

ss_group = Group.create_ordered("Secondary structure sub-filter")


@Parameter(name="*")
@dataclass
class FilterOptions:
    combined: CombinedFilterQuery = field(default_factory=CombinedFilterQuery)
    ss: Annotated[SecondaryStructureFilterQuery, Parameter(name="secondary", group=ss_group)] = field(
        default_factory=SecondaryStructureFilterQuery
    )


def _write_ro_crate(
    session_dir: Path,
    start_time: datetime,
    /,
    *,
    pdbe_path: StdioPath,
    pdbe_download_dir: Path,
    downloaded_af_dir: Path,
    pdbe_quality_json: StdioPath,
    uniprots_verified: Path,
    uniprots_verified_stats_file: Path,
    single_chain_dir: Path,
    single_chain_stats_file: Path,
    combined_input_dir: Path,
    combined_output_dir: Path,
    combined_stats_file: StdioPath,
    ss_output_dir: Path | None = None,
    ss_stats_file: StdioPath | None = None,
) -> None:
    ioargs = IOArgumentPaths(
        input_files=[
            IOArgumentPath(
                name="pdbe_ids_file",
                path=pdbe_path,
                help="CSV file containing the PDBe identifiers and Uniprot to chain assignments.",
            ),
            IOArgumentPath(
                name="pdbe_quality_json",
                path=pdbe_quality_json,
                help="JSON file containing the PDBe quality scores.",
            ),
        ],
        input_dirs=[
            IOArgumentPath(
                name="pdbe_download_dir",
                path=pdbe_download_dir,
                help="Directory where the PDBe files were downloaded.",
            ),
            IOArgumentPath(
                name="alphafold_download_dir",
                path=downloaded_af_dir,
                help="Directory where the AlphaFold files were downloaded.",
            ),
        ],
        output_dirs=[
            IOArgumentPath(
                name="uniprots_verified_dir",
                path=uniprots_verified,
                help=(
                    "Directory where the uniprots are verified and injected if needed from "
                    f"{pdbe_download_dir.relative_to(session_dir, walk_up=True)}."
                ),
            ),
            IOArgumentPath(
                name="single_chain_dir",
                path=single_chain_dir,
                help=(
                    "Directory where the single chain structure files are written from "
                    f"{uniprots_verified.relative_to(session_dir, walk_up=True)}."
                ),
            ),
            IOArgumentPath(
                name="combined_input_dir",
                path=combined_input_dir,
                help=(
                    "Directory where files from "
                    f"{single_chain_dir.relative_to(session_dir, walk_up=True)} and "
                    f"{downloaded_af_dir.relative_to(session_dir, walk_up=True)} were copied into."
                ),
            ),
            IOArgumentPath(
                name="combined_output_dir",
                path=combined_output_dir,
                help="Directory where the combined filtered structure files are written to.",
            ),
        ],
        output_files=[
            IOArgumentPath(
                name="uniprots_verified_stats_file",
                path=uniprots_verified_stats_file,
                help="CSV file containing statistics for the uniprot verification step.",
            ),
            IOArgumentPath(
                name="single_chain_stats_file",
                path=single_chain_stats_file,
                help="CSV file containing statistics for the single chain filtering step.",
            ),
            IOArgumentPath(
                name="combined_stats_file",
                path=combined_stats_file,
                help="CSV file containing statistics for the combined filtering step.",
            ),
        ],
    )
    if ss_output_dir:
        ioargs.output_dirs.append(
            IOArgumentPath(
                name="secondary_structure_output_dir",
                path=ss_output_dir,
                help=(
                    "Directory where the secondary structure filtered structure files are "
                    f"written. Source {combined_output_dir.relative_to(session_dir, walk_up=True)} dir."
                ),
            )
        )
    if ss_stats_file:
        ioargs.output_files.append(
            IOArgumentPath(
                name="secondary_structure_stats_file",
                path=ss_stats_file,
                help="CSV file containing statistics for the secondary structure filtering step.",
            )
        )
    write_ro_crate(
        session_dir,
        start_time,
        command_name="filter",
        command_description="Filter structure files based on specified parameters",
        ioargs=ioargs,
    )


def _merge_structure_files(downloaded_af_dir: Path, with_uniprots: Path, combined_input_dir: Path):
    combined_input_dir.mkdir()
    for file in downloaded_af_dir.glob("*"):
        copyfile(file, combined_input_dir / file.name, copy_method="symlink")
    for file in with_uniprots.glob("*"):
        copyfile(file, combined_input_dir / file.name, copy_method="symlink")


def _make_stats_relative_to_session_dir(stats_file: Path, session_dir: Path):
    """Replaces occurrences of `session_dir/` with `/` in given stats text file."""
    content = stats_file.read_text()
    content = content.replace(f"{session_dir}/", "")
    stats_file.write_text(content)


def run_filter(
    session_dir: Annotated[Path, Parameter(validator=validators.Path(file_okay=False, dir_okay=True, exists=True))],
    /,
    *,
    options: FilterOptions | None = None,
    _: Common | None = None,
):
    """Filter structure files based on specified parameters.

    Steps:

    1. Verify expected uniprot accessions are in structure files and inject uniprot accession if missing.
        See [protein-quest convert structure --uniprots](https://www.bonvinlab.org/protein-quest/cli.html#protein-quest-convert-structures).
    2. Convert PDBe structure files to single chain structure files.
        See [protein-quest filter chain](https://www.bonvinlab.org/protein-quest/cli.html#protein-quest-filter-chain).
    3. Filters processed PDBe structure files and AlphaFold structure files based on given parameters.
        See [protein-quest filter combined](https://www.bonvinlab.org/protein-quest/cli.html#protein-quest-filter-combined).
    4. If secondary structure options are given then
        filters passed structure files based on secondary structure.
        See [protein-quest filter secondary-structure](https://www.bonvinlab.org/protein-quest/cli.html#protein-quest-filter-secondary-structure).

    Args:
        session_dir: Directory where the structure files are located.
        options: The filtering options.
    """
    if options is None:
        options = FilterOptions()

    start_time = datetime.now(tz=UTC)

    downloaded_pdbe_dir = session_dir / "downloads" / "pdbe"
    downloaded_af_dir = session_dir / "downloads" / "alphafold"
    pdbe_csv = StdioPath(session_dir / "pdbe.csv")
    pdbe_quality_json = StdioPath(session_dir / "pdbe-quality.json")

    uniprots_verified = session_dir / "uniprots_verified"
    uniprots_verified_stats = StdioPath(session_dir / "uniprots_verified_stats.csv")
    structures(
        downloaded_pdbe_dir,
        output_dir=uniprots_verified,
        uniprots=pdbe_csv,
        write_stats=uniprots_verified_stats,
    )
    _make_stats_relative_to_session_dir(uniprots_verified_stats, session_dir)

    single_chain_dir = session_dir / "single_chain"
    single_chain_stats = StdioPath(session_dir / "single_chain_stats.csv")
    chain(pdbe_csv, uniprots_verified, single_chain_dir, write_stats=single_chain_stats)

    # Combined filter works best if all structure files are in one directory
    combined_input_dir = session_dir / "combined_input"
    _merge_structure_files(downloaded_af_dir, single_chain_dir, combined_input_dir)

    combined_output_dir = session_dir / "combined_output"
    combined_stats_file = StdioPath(session_dir / "combined_stats.csv")
    combined(
        combined_input_dir,
        pdbe_quality_json,
        combined_output_dir,
        filters=options.combined,
        write_stats=combined_stats_file,
    )
    _make_stats_relative_to_session_dir(combined_stats_file, session_dir)

    ss_output_dir = None
    ss_stats_file = None
    if options.ss.is_actionable():
        ss_output_dir = session_dir / "secondary_structure"
        ss_stats_file = StdioPath(session_dir / "secondary_structure_stats.csv")
        secondary_structure(combined_output_dir, ss_output_dir, filters=options.ss, write_stats=ss_stats_file)
        _make_stats_relative_to_session_dir(ss_stats_file, session_dir)

    _write_ro_crate(
        session_dir,
        start_time,
        # Input
        pdbe_path=pdbe_csv,
        pdbe_download_dir=downloaded_pdbe_dir,
        downloaded_af_dir=downloaded_af_dir,
        pdbe_quality_json=pdbe_quality_json,
        # Output
        uniprots_verified=uniprots_verified,
        uniprots_verified_stats_file=uniprots_verified_stats,
        single_chain_dir=single_chain_dir,
        single_chain_stats_file=single_chain_stats,
        combined_input_dir=combined_input_dir,
        combined_output_dir=combined_output_dir,
        combined_stats_file=combined_stats_file,
        ss_output_dir=ss_output_dir,
        ss_stats_file=ss_stats_file,
    )
