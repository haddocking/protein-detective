import asyncio
from pathlib import Path

from protein_detective.utils import retrieve_files


def _map_id(pdb_id: str) -> tuple[str, str]:
    """
    Map PDB id to a download gzipped pdb url and file.
    """
    fn = f"pdb{pdb_id.lower()}.ent.gz"
    middle = pdb_id.lower()[1:3]
    url = f"https://ftp.ebi.ac.uk/pub/databases/rcsb/pdb-remediated/data/structures/divided/pdb/{middle}/{fn}"
    return url, fn


def fetch(ids: set[str], save_dir: Path, max_parallel_downloads: int = 5) -> list[Path]:
    """Fetches gzipped PDB files from the PDBe database.

    Args:
        ids: A set of PDB IDs to fetch.
        save_dir: The directory to save the fetched PDB files to.
        max_parallel_downloads: The maximum number of parallel downloads.

    Returns:
        A list of paths to the downloaded PDB files.
    """

    urls = {_map_id(pdb_id) for pdb_id in ids}
    return asyncio.run(retrieve_files(urls, save_dir, max_parallel_downloads))
