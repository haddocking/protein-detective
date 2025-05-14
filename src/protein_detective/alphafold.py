from collections.abc import AsyncGenerator
from pathlib import Path

from pydantic import BaseModel

from protein_detective.alphafold_client.api.public_api_api import PublicApiApi
from protein_detective.alphafold_client.api_client import ApiClient
from protein_detective.alphafold_client.configuration import Configuration
from protein_detective.alphafold_client.models.entry_summary import EntrySummary
from protein_detective.utils import retrieve_files


class AlphaFoldEntry(BaseModel):
    summary: EntrySummary
    pdb_file: Path
    pae_file: Path

async def fetch_summmary(qualifier: str) -> list[EntrySummary]:
    configuration = Configuration("https://alphafold.ebi.ac.uk/api", retries=3)
    async with ApiClient(configuration) as api_client:
        api_instance = PublicApiApi(api_client)
        return await api_instance.get_predictions_api_prediction_qualifier_get(qualifier)


async def fetch_summaries(qualifiers: set[str]) -> AsyncGenerator[EntrySummary]:
    # TODO run in parallel, currently this is sequential
    for qualifier in qualifiers:
        summary = await fetch_summmary(qualifier)
        for entry in summary:
            yield entry


def url2name(url: str) -> str:
    """Given a URL, return the final path component as the name of the file."""
    return url.split("/")[-1]


async def fetch(ids: set[str], save_dir: Path, max_parallel_downloads: int = 5) -> AsyncGenerator[AlphaFoldEntry]:
    """Asynchronously fetches summary and pdb and pae (predicted alignment error) file from
    [AlphaFold Protein Structure Database](https://alphafold.ebi.ac.uk/).

    Args:
        ids: A set of Uniprot IDs to fetch.
        save_dir: The directory to save the fetched files to.
        max_parallel_downloads: The maximum number of parallel downloads.

    Yields:
        A dataclass containing the summary, pdb file, and pae file.
    """
    async for summary in fetch_summaries(ids):
        files = {
            (summary.pdb_url, url2name(summary.pdb_url)),
            (summary.pae_doc_url, url2name(summary.pae_doc_url)),
        }
        await retrieve_files(
            files,
            save_dir,
            max_parallel_downloads,
        )
        yield AlphaFoldEntry.model_construct(
            summary=summary,
            pdb_file=save_dir / url2name(summary.pdb_url),
            pae_file=save_dir / url2name(summary.pae_doc_url),
        )
