import asyncio
import concurrent
from asyncio import Semaphore
from collections.abc import AsyncGenerator, Iterable
from dataclasses import dataclass
from pathlib import Path

from aiohttp_retry import RetryClient
from cattrs import structure
from tqdm.asyncio import tqdm

from protein_detective.alphafold.entry_summary import EntrySummary
from protein_detective.utils import friendly_session, retrieve_files


@dataclass
class AlphaFoldEntry:
    summary: EntrySummary
    pdb_file: Path
    pae_file: Path

    @property
    def uniprot_acc(self) -> str:
        return self.summary.uniprotAccession


async def fetch_summmary(qualifier: str, session: RetryClient, semaphore: Semaphore) -> list[EntrySummary]:
    url = f"https://alphafold.ebi.ac.uk/api/prediction/{qualifier}"
    async with semaphore, session.get(url) as response:
        response.raise_for_status()
        data = await response.json()
        return structure(data, list[EntrySummary])


async def fetch_summaries(qualifiers: Iterable[str], max_parallel_downloads: int = 5) -> AsyncGenerator[EntrySummary]:
    semaphore = Semaphore(max_parallel_downloads)
    async with friendly_session() as session:
        tasks = [fetch_summmary(qualifier, session, semaphore) for qualifier in qualifiers]
        summaries_per_qualifier: list[list[EntrySummary]] = await tqdm.gather(
            *tasks, desc="Fetching Alphafold summaries"
        )
        for summaries in summaries_per_qualifier:
            for summary in summaries:
                yield summary


def url2name(url: str) -> str:
    """Given a URL, return the final path component as the name of the file."""
    return url.split("/")[-1]


async def fetch_many_async(ids: Iterable[str], save_dir: Path) -> AsyncGenerator[AlphaFoldEntry]:
    """Asynchronously fetches summaries and pdb and pae (predicted alignment error) files from
    [AlphaFold Protein Structure Database](https://alphafold.ebi.ac.uk/).

    Args:
        ids: A set of Uniprot IDs to fetch.
        save_dir: The directory to save the fetched files to.

    Yields:
        A dataclass containing the summary, pdb file, and pae file.
    """
    summaries = [s async for s in fetch_summaries(ids)]

    files = {(summary.pdbUrl, url2name(summary.pdbUrl)) for summary in summaries} | {
        (summary.paeDocUrl, url2name(summary.paeDocUrl)) for summary in summaries
    }
    await retrieve_files(
        files,
        save_dir,
        desc="Downloading AlphaFold files",
    )
    for summary in summaries:
        yield AlphaFoldEntry(
            summary=summary,
            pdb_file=save_dir / url2name(summary.pdbUrl),
            pae_file=save_dir / url2name(summary.paeDocUrl),
        )


def fetch_many(ids: Iterable[str], save_dir: Path) -> list[AlphaFoldEntry]:
    """Synchronously fetches summaries and pdb and pae files from AlphaFold Protein Structure Database.

    Args:
        ids: A set of Uniprot IDs to fetch.
        save_dir: The directory to save the fetched files to.

    Returns:
        A list of AlphaFoldEntry dataclasses containing the summary, pdb file, and pae file.
    """

    async def gather_entries():
        return [entry async for entry in fetch_many_async(ids, save_dir)]

    def run_async_task():
        return asyncio.run(gather_entries())

    # pyrefly: ignore  # noqa: ERA001
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(run_async_task)
        return future.result()
