"""Workflow steps"""

import asyncio
import logging
from pathlib import Path
from typing import Literal

from distributed.deploy.cluster import Cluster
from protein_quest.alphafold.fetch import DownloadableFormat
from protein_quest.alphafold.fetch import fetch_many_async as af_fetch
from protein_quest.alphafold.fetch import relative_to as af_relative_to
from protein_quest.pdbe.fetch import fetch as pdbe_fetch
from protein_quest.uniprot import Query, search4af, search4pdb, search4uniprot

from protein_detective.db import (
    connect,
    load_alphafold_ids,
    load_alphafolds,
    load_pdb_ids,
    load_pdbs,
    save_alphafolds,
    save_alphafolds_files,
    save_filter,
    save_filtered_structures,
    save_pdb_files,
    save_pdbs,
    save_query,
    save_uniprot_accessions,
)
from protein_detective.filter import (
    FilteredStructure,
    FilterOptions,
    filter_alphafold_structures,
    filter_pdbe_structures,
)

logger = logging.getLogger(__name__)


def search_structures_in_uniprot(query: Query, session_dir: Path, limit: int = 10_000) -> tuple[int, int, int, int]:
    """Searches for protein structures in UniProt database.

    Args:
        query: The search query.
        session_dir: The directory to store the search results.
        limit: The maximum number of results to return from each database query.

    Returns:
        A tuple containing the number of UniProt accessions, the number of PDB structures,
        number of UniProt to PDB mappings,
        and the number of AlphaFold structures found.
    """
    session_dir.mkdir(parents=True, exist_ok=True)

    uniprot_accessions = search4uniprot(query, limit)
    pdbs = search4pdb(uniprot_accessions, limit=limit)
    af_result = search4af(uniprot_accessions, limit=limit)

    with connect(session_dir) as con:
        save_query(query, con)
        save_uniprot_accessions(uniprot_accessions, con)
        nr_pdbs, nr_prot2pdb = save_pdbs(pdbs, con)
        nr_afs = save_alphafolds(af_result, con)

    return len(uniprot_accessions), nr_pdbs, nr_prot2pdb, nr_afs


WhatRetrieve = Literal["pdbe", "alphafold"]
"""Types of what to retrieve."""
what_retrieve_choices: set[WhatRetrieve] = {"pdbe", "alphafold"}
"""Set of what can be retrieved."""


def retrieve_structures(
    session_dir: Path, what: set[WhatRetrieve] | None = None, what_af_formats: set[DownloadableFormat] | None = None
) -> tuple[Path, int, int]:
    """Retrieve structure files from PDBe and AlphaFold databases for the Uniprot entries in the session.

    Args:
        session_dir: The directory to store downloaded files and the session database.
        what: A tuple of strings indicating which databases to retrieve files from.
        what_af_formats: A tuple of formats to download from AlphaFold (e.g., "pdb", "cif").

    Returns:
        A tuple containing the download directory, the number of PDBe mmCIF files downloaded,
        and the number of AlphaFold files downloaded.
    """
    return asyncio.run(async_retrieve_structures(session_dir, what, what_af_formats))


async def async_retrieve_structures(
    session_dir: Path, what: set[WhatRetrieve] | None = None, what_af_formats: set[DownloadableFormat] | None = None
) -> tuple[Path, int, int]:
    """
    Retrieve structure files from PDBe and AlphaFold databases for the Uniprot entries in the session asynchronously.

    Args:
        session_dir: The directory to store downloaded files and the session database.
        what: A set of strings indicating which databases to retrieve files from ("pdbe", "alphafold").
        what_af_formats: A set of formats to download from AlphaFold (e.g., "pdb", "cif").

    Returns:
        A tuple containing:
            - The download directory (Path)
            - The number of PDBe mmCIF files downloaded (int)
            - The number of AlphaFold files downloaded (int)
    """
    if not session_dir.exists() or not session_dir.is_dir():
        raise NotADirectoryError(session_dir)
    download_dir = session_dir / "downloads"
    download_dir.mkdir(parents=True, exist_ok=True)

    if what is None:
        what = {"pdbe", "alphafold"}
    if not (what <= what_retrieve_choices):
        msg = f"Invalid 'what' argument: {what}. Must be a subset of {what_retrieve_choices}."
        raise ValueError(msg)

    sr_mmcif_files = {}
    if "pdbe" in what:
        download_pdbe_dir = download_dir / "pdbe"
        download_pdbe_dir.mkdir(parents=True, exist_ok=True)
        # mmCIF files from PDBe for the Uniprot entries in the session.
        pdb_ids = set()
        with connect(session_dir) as con:
            pdb_ids = load_pdb_ids(con)
            mmcif_files = await pdbe_fetch(pdb_ids, download_pdbe_dir)
            # make paths relative to session_dir, so db stores paths relative to session_dir
            sr_mmcif_files = {pdb_id: mmcif_file.relative_to(session_dir) for pdb_id, mmcif_file in mmcif_files.items()}
            save_pdb_files(sr_mmcif_files, con)

    afs = []
    if "alphafold" in what:
        # AlphaFold entries for the given query
        af_ids = set()
        if what_af_formats is None:
            what_af_formats = {"cif"}
        download_af_dir = download_dir / "alphafold"
        download_af_dir.mkdir(parents=True, exist_ok=True)
        with connect(session_dir) as con:
            af_ids = load_alphafold_ids(con)
            afs = [entry async for entry in af_fetch(af_ids, download_af_dir, what_af_formats)]
            sr_afs = [af_relative_to(af, session_dir) for af in afs]
            save_alphafolds_files(sr_afs, con)

    return download_dir, len(sr_mmcif_files), len(afs)


def filter_structures(
    session_dir: Path,
    options: FilterOptions,
    scheduler_address: str | Cluster | None = None,
) -> tuple[Path, list[FilteredStructure]]:
    """Filter the structures in the session based on confidence, number of residues, and secondary structure.

    Also uncompresses *.cif.gz files to *.cif files for compatibility with powerfit.

    Args:
        session_dir: The directory containing the session data, including structure files.
        options: The filter options containing confidence and secondary structure filter queries.
        scheduler_address: Address of the Dask scheduler for distributed filtering.
            If None then a local cluster is used.

    Returns:
        A tuple containing:
            - The directory with the filtered structures.
            - A list of FilteredStructure objects containing the filtering results for each structure.
    """
    if not session_dir.exists() or not session_dir.is_dir():
        raise NotADirectoryError(session_dir)
    final_dir = session_dir / "filtered"
    final_dir.mkdir(parents=True, exist_ok=True)

    # Filter AlphaFolds
    with connect(session_dir, read_only=True) as con:
        logger.info("Gathering AlphaFold files from session in %s", session_dir)
        afs = load_alphafolds(con)
        logger.info("Found %i AlphaFold files", len(afs))
    total_results = filter_alphafold_structures(afs, session_dir, options, final_dir)

    # Filter PDBe structures
    with connect(session_dir, read_only=True) as con:
        logger.info("Gathering PDBe files from session in %s", session_dir)
        proteinpdbs = load_pdbs(con)
        logger.info("Found %i PDBe files", len(proteinpdbs))
    pdbe_total_results = filter_pdbe_structures(
        proteinpdbs=proteinpdbs,
        session_dir=session_dir,
        options=options,
        final_dir=final_dir,
        scheduler_address=scheduler_address,
    )
    total_results.update(pdbe_total_results)

    # Save filtering results to database
    logger.info("Saving filtering results to database in %s", session_dir)
    total_results_values = [r.make_relative_to(session_dir) for r in total_results.values()]
    with connect(session_dir) as con:
        filter_id = save_filter(options, con)
        save_filtered_structures(total_results_values, filter_id, con)

    return final_dir, total_results_values
