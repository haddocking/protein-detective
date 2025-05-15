from collections.abc import AsyncGenerator
from dataclasses import dataclass
from pathlib import Path

import aiohttp
from cattrs import structure

from protein_detective.utils import retrieve_files


# Modelled after EntrySummary in https://alphafold.ebi.ac.uk/api/openapi.json
@dataclass
class EntrySummary:
    entryId: str
    gene: str | None
    sequenceChecksum: str | None
    sequenceVersionDate: str | None
    uniprotAccession: str
    uniprotId: str
    uniprotDescription: str
    taxId: int
    organismScientificName: str
    uniprotStart: int
    uniprotEnd: int
    uniprotSequence: str
    modelCreatedDate: str
    latestVersion: int
    allVersions: list[int]
    bcifUrl: str
    cifUrl: str
    pdbUrl: str
    paeImageUrl: str
    paeDocUrl: str
    amAnnotationsUrl: str | None
    amAnnotationsHg19Url: str | None
    amAnnotationsHg38Url: str | None
    isReviewed: bool | None
    isReferenceProteome: bool | None

@dataclass
class AlphaFoldEntry:
    summary: EntrySummary
    pdb_file: Path
    pae_file: Path

async def fetch_summmary(qualifier: str) -> list[EntrySummary]:
    async with aiohttp.ClientSession() as session:
        url = f"https://alphafold.ebi.ac.uk/api/prediction/{qualifier}"
        async with session.get(url) as response:
            response.raise_for_status()
            data = await response.json()
            return structure(data, list[EntrySummary])


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
