import json
from pathlib import Path

from protein_detective.utils import retrieve_files

UrlFilePair = tuple[str, str]


def _map_id2summary(uniprot_id: str) -> UrlFilePair:
    url = f"https://alphafold.ebi.ac.uk/api/prediction/{uniprot_id}"
    return url, f"{uniprot_id}.summary.json"


def parse_summary(summary_file: Path) -> tuple[set[UrlFilePair], set[UrlFilePair]]:
    """Parses the summary file and returns a dictionary with the parsed data.

    Args:
        summary_file: The path to the summary file.

    Returns:
        List of tuples containing the URL and filename of the bcif and pae files.

    """

    bcifs = set()
    paes = set()
    with Path.open(summary_file) as f:
        data = json.load(f)
        for model in data:
            if "bcifUrl" in model:
                url = model["bcifUrl"]
                fn = url.split("/")[-1]
                bcifs.add(
                    (
                        url,
                        fn,
                    )
                )
            if "paeDocUrl" in model:
                url = model["paeDocUrl"]
                fn = url.split("/")[-1]
                paes.add(
                    (
                        url,
                        fn,
                    )
                )
    return bcifs, paes


async def fetch(ids: set[str], save_dir: Path, max_parallel_downloads: int = 5):
    """Asynchronously fetches summary, bcif and pae (predicted alignment error) file from
    [AlphaFold Protein Structure Database](https://alphafold.ebi.ac.uk/).

    Args:
        ids: A set of Uniprot IDs to fetch.
        save_dir: The directory to save the fetched files to.
        max_parallel_downloads: The maximum number of parallel downloads.

    """
    # Downloading alphafold files is a 2-step process:
    # 1. Download the summary file for each Uniprot ID
    # 2. Parse the summary file to get the URLs for the bcif and pae files
    meta_urls = {_map_id2summary(uniprot_id) for uniprot_id in ids}
    await retrieve_files(meta_urls, save_dir, max_parallel_downloads)

    summary_files = [save_dir / f"{uniprot_id}.summary.json" for uniprot_id in ids]
    for summary_file in summary_files:
        bcifs, paes = parse_summary(summary_file)
        all_files = bcifs.union(paes)
        await retrieve_files(all_files, save_dir, max_parallel_downloads)
