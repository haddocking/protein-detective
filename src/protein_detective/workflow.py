"""Workflow steps"""

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from distributed.deploy.cluster import Cluster
from protein_quest.alphafold.fetch import DownloadableFormat
from protein_quest.alphafold.fetch import fetch_many_async as af_fetch
from protein_quest.pdbe.fetch import fetch as pdbe_fetch
from protein_quest.pdbe.result import filter_pdb_results_on_chain_length
from protein_quest.pdbe.ws import Scores, fetch_summary_quality_scores_in_batches
from protein_quest.uniprot import (
    map_uniprot_accessions2uniprot_details,
    search4af,
    search4pdb,
    search4uniprot,
)
from protein_quest.utils import DirectoryCacher

from protein_detective.db import (
    check_uniprot_query_exists,
    connect,
    load_alphafold_ids,
    load_alphafolds,
    load_pdb_ids,
    load_pdbs,
    load_uniprot_accessions,
    save_alphafolds,
    save_alphafolds_files,
    save_filter,
    save_filtered_structures,
    save_pdb_files,
    save_pdb_quality_scores,
    save_pdbs,
    save_query,
    save_uniprot_accessions,
    save_uniprot_details,
)
from protein_detective.filter import (
    FilteredStructure,
    FilterOptions,
    filter_structures_with_combined_filter,
)
from protein_detective.powerfit.parallel import configure_dask_scheduler
from protein_detective.search import UniprotQuery, search_for_interaction_partners

logger = logging.getLogger(__name__)


@dataclass
class UniprotSearchResult:
    """Result of a UniProt search.

    Parameters:
        nr_uniprot_accessions: Number of UniProt accessions found.
        nr_pdbs: Number of PDB structures found.
        nr_prot2pdb: Number of UniProt to PDB mappings found.
        nr_afs: Number of AlphaFold structures found.
        nr_interaction_partners: Number of interaction partners found.
    """

    nr_uniprot_accessions: int
    nr_pdbs: int
    nr_prot2pdb: int
    nr_afs: int
    nr_interaction_partners: int


def search_structures_in_uniprot(query: UniprotQuery, session_dir: Path, limit: int = 10_000) -> UniprotSearchResult:
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

    logger.warning("Searching UniProt")
    uniprot_accessions = _get_saved_uniprot_accessions(query, session_dir)
    if uniprot_accessions:
        logger.warning(f"Reusing {len(uniprot_accessions)} previously found UniProt accessions")
    else:
        uniprot_accessions = search4uniprot(query, limit)
        logger.warning(f"Found {len(uniprot_accessions)} UniProt accessions matching the query")
    logger.warning("Searching for interaction partners")
    logger.debug(uniprot_accessions)
    uniprot_accessions_of_partners = search_for_interaction_partners(query, limit)
    logger.debug(uniprot_accessions_of_partners)
    nr_interaction_partners = len(uniprot_accessions_of_partners)
    logger.warning(f"Found {nr_interaction_partners} interaction partners")
    uniprot_accessions.update(uniprot_accessions_of_partners)
    with connect(session_dir) as con:
        save_query(query, con)
        save_uniprot_accessions(uniprot_accessions, con)

    logger.warning("Searching for PDB references")
    pdbs = search4pdb(uniprot_accessions, limit=limit)
    if query.min_residues or query.max_residues:
        pdbs = filter_pdb_results_on_chain_length(pdbs, query.min_residues, query.max_residues, keep_invalid=True)

    pdb_ids = {pdb.id.lower() for pdb_results in pdbs.values() for pdb in pdb_results}
    logger.warning("Fetching PDBe validation quality scores")
    scores = asyncio.run(fetch_summary_quality_scores_in_batches(pdb_ids)) if pdb_ids else {}
    with connect(session_dir) as con:
        nr_pdbs, nr_prot2pdb = save_pdbs(pdbs, con)
        save_pdb_quality_scores(scores, con)

    logger.warning("Searching for AlphaFold references")
    af_result = search4af(
        uniprot_accessions,
        min_sequence_length=query.min_sequence_length,
        max_sequence_length=query.max_sequence_length,
        limit=limit,
    )
    with connect(session_dir) as con:
        nr_afs = save_alphafolds(af_result, con)

    logger.warning(f"Fetching details for {len(uniprot_accessions)} UniProt accessions")
    uniprot_details = list(map_uniprot_accessions2uniprot_details(uniprot_accessions))
    with connect(session_dir) as con:
        save_uniprot_details(uniprot_details, con)

    return UniprotSearchResult(
        nr_uniprot_accessions=len(uniprot_accessions),
        nr_pdbs=nr_pdbs,
        nr_prot2pdb=nr_prot2pdb,
        nr_afs=nr_afs,
        nr_interaction_partners=nr_interaction_partners,
    )


def _get_saved_uniprot_accessions(query: UniprotQuery, session_dir: Path) -> set[str]:
    with connect(session_dir) as con:
        # As this most likely first query we need to open in non-read-only mode
        # to allow creating of the database
        uniprot_query_exists = check_uniprot_query_exists(query, con)
        if uniprot_query_exists:
            logger.warning("Query already exists in session, reusing previously found UniProt accessions")
            return load_uniprot_accessions(con)
    return set()


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
        what_af_formats: A set of formats to download from AlphaFold (e.g., "summary", "pdb", "cif").
            If None, defaults to {"cif"}.

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

    cacher = DirectoryCacher()

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
        with connect(session_dir, read_only=True) as con:
            pdb_ids = load_pdb_ids(con)
        mmcif_files = await pdbe_fetch(pdb_ids, download_pdbe_dir, cacher=cacher)
        # make paths relative to session_dir, so db stores paths relative to session_dir
        sr_mmcif_files = {pdb_id: mmcif_file.relative_to(session_dir) for pdb_id, mmcif_file in mmcif_files.items()}
        with connect(session_dir) as con:
            save_pdb_files(sr_mmcif_files, con)

    afs = []
    if "alphafold" in what:
        # AlphaFold entries for the given query
        af_ids = set()
        if what_af_formats is None:
            what_af_formats = {"cif"}
        download_af_dir = download_dir / "alphafold"
        download_af_dir.mkdir(parents=True, exist_ok=True)
        with connect(session_dir, read_only=True) as con:
            af_ids = load_alphafold_ids(con)
        afs = [
            entry async for entry in af_fetch(af_ids, download_af_dir, what_af_formats, gzip_files=True, cacher=cacher)
        ]
        sr_afs = [af.relative_to(session_dir) for af in afs]
        with connect(session_dir) as con:
            save_alphafolds_files(sr_afs, con)

    return download_dir, len(sr_mmcif_files), len(afs)


def filter_structures(
    session_dir: Path,
    options: FilterOptions,
    scheduler_address: str | Cluster | None = None,
) -> tuple[Path, list[FilteredStructure]]:
    """Filter the structures in the session based on confidence, number of residues, and secondary structure.

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

    with configure_dask_scheduler(
        scheduler_address,
        name="filter-chain",
    ) as scheduler_address:
        with connect(session_dir, read_only=True) as con:
            logger.info("Gathering AlphaFold files from session in %s", session_dir)
            afs = load_alphafolds(con)
            logger.info("Found %i AlphaFold files", len(afs))
            logger.info("Gathering PDBe files from session in %s", session_dir)
            proteinpdbs = load_pdbs(con)
            logger.info("Found %i PDBe files", len(proteinpdbs))

        scores = {
            proteinpdb.pdb_id.lower(): Scores(
                geometry_quality=proteinpdb.geometry_quality,
                data_quality=None,
                overall_quality=None,
                experiment_data_available=False,
            )
            for proteinpdb in proteinpdbs
            if proteinpdb.pdb_id is not None and proteinpdb.geometry_quality is not None
        }

        total_results = filter_structures_with_combined_filter(
            afs=afs,
            proteinpdbs=proteinpdbs,
            scores=scores,
            session_dir=session_dir,
            options=options,
            final_dir=final_dir,
            scheduler_address=scheduler_address,
        )

    # Save filtering results to database
    logger.info("Saving filtering results to database in %s", session_dir)
    total_results_values = [r.make_relative_to(session_dir) for r in total_results.values()]
    with connect(session_dir) as con:
        # TODO filter results not in db
        filter_id = save_filter(options, con)
        save_filtered_structures(total_results_values, filter_id, con)

    return final_dir, total_results_values
