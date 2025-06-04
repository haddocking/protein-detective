import asyncio
import concurrent.futures
from collections.abc import Iterable, Mapping
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


def fetch(ids: Iterable[str], save_dir: Path, max_parallel_downloads: int = 5) -> Mapping[str, Path]:
    """Fetches gzipped PDB files from the PDBe database.

    Args:
        ids: A set of PDB IDs to fetch.
        save_dir: The directory to save the fetched PDB files to.
        max_parallel_downloads: The maximum number of parallel downloads.

    Returns:
        A dict of id and paths to the downloaded PDB files.
    """

    # The future result, is in a different order than the input ids,
    # so we need to map the ids to the urls and filenames.

    id2urls = {pdb_id: _map_id(pdb_id) for pdb_id in ids}
    urls = list(id2urls.values())
    id2paths = {pdb_id: save_dir / fn for pdb_id, (_, fn) in id2urls.items()}

    def run_async_task():
        return asyncio.run(retrieve_files(urls, save_dir, max_parallel_downloads, desc="Downloading PDBe files"))

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(run_async_task)
        result = future.result()
        if set(result) != set(id2paths.values()):
            msg = "Not all files were downloaded successfully."
            raise ValueError(msg)
        return id2paths
