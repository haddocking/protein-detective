from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from cyclopts import Parameter, validators
from cyclopts._path_type import StdioPath
from protein_quest.cli.common import CacheParameter
from protein_quest.cli.retrieve import (
    alphafold,
    pdbe,
)
from rocrate_action_recorder import IOArgumentPath, IOArgumentPaths

from protein_detective.common_cli import Common, write_ro_crate


def _write_ro_crate(
    session_dir: Path,
    start_time: datetime,
    /,
    *,
    alphafold_file: StdioPath,
    pdbe_path: StdioPath,
    pdbe_download_dir: Path,
    af_download_dir: Path,
) -> None:
    ioargs = IOArgumentPaths(
        input_files=[
            IOArgumentPath(
                name="alphafold_ids_file",
                path=alphafold_file,
                help="CSV file containing the AlphaFold identifiers.",
            ),
            IOArgumentPath(
                name="pdbe_ids_file",
                path=pdbe_path,
                help="CSV file containing the PDBe identifiers.",
            ),
        ],
        output_dirs=[
            IOArgumentPath(
                name="pdbe_download_dir",
                path=pdbe_download_dir,
                help="Directory where the PDBe files were downloaded.",
            ),
            IOArgumentPath(
                name="alphafold_download_dir",
                path=af_download_dir,
                help="Directory where the AlphaFold files were downloaded.",
            ),
        ],
    )
    write_ro_crate(
        session_dir,
        start_time,
        command_name="retrieve",
        command_description="Retrieve structure files",
        ioargs=ioargs,
    )


def retrieve(
    session_dir: Annotated[Path, Parameter(validator=validators.Path(file_okay=False, dir_okay=True, exists=True))],
    /,
    *,
    alphafold_db_version: str = "6",
    cache: CacheParameter | None = None,
    _: Common | None = None,
) -> None:
    """Retrieve structure files from AlphaFold and PDBe.

    Based on previously obtained search results.

    Args:
        session_dir: The directory containing the search results.
        alphafold_db_version: The version of the AlphaFold database to use.
        cache: Cache options including no_cache, cache_dir, and copy_method.
    """
    start_time = datetime.now(tz=UTC)

    download_dir = session_dir / "downloads"
    pdbe_download_dir = download_dir / "pdbe"
    pdbe_download_dir.mkdir(parents=True, exist_ok=True)

    pdbe_csv = StdioPath(session_dir / "pdbe.csv")
    pdbe(
        pdbe_csv,
        pdbe_download_dir,
        cache=cache,
    )

    af_download_dir = download_dir / "alphafold"
    af_download_dir.mkdir(parents=True, exist_ok=True)

    alphafold_csv = StdioPath(session_dir / "alphafold.csv")
    alphafold(
        alphafold_csv,
        af_download_dir,
        db_version=alphafold_db_version,
        gzip_files=True,
        cache=cache,
    )

    _write_ro_crate(
        session_dir,
        start_time,
        alphafold_file=alphafold_csv,
        pdbe_path=pdbe_csv,
        pdbe_download_dir=pdbe_download_dir,
        af_download_dir=af_download_dir,
    )
