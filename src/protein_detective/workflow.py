"""Workflow steps.

High level function that are the public API of the package.

Functions where data is fetched and processed
and where that data is saved and/or loaded from session database.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from dask.distributed import Client, progress
from distributed.deploy.cluster import Cluster

from protein_detective.alphafold import DownloadableFormat
from protein_detective.alphafold import fetch_many as af_fetch
from protein_detective.alphafold import relative_to as af_relative_to
from protein_detective.alphafold.density import DensityFilterQuery, filter_on_density
from protein_detective.cache import (
    find_session_with_same_query,
    symlink_cached_alphafold_files,
    symlink_cached_pdbe_files,
    try_reusing_search_results_from_another_session,
)
from protein_detective.db import (
    SearchCounts,
    connect,
    load_alphafolds,
    load_pdbs,
    save_alphafolds,
    save_alphafolds_files,
    save_density_filtered,
    save_pdb_files,
    save_pdbs,
    save_query,
    save_single_chain_pdb_files,
    save_uniprot_accessions,
    uniprot_query_exists,
    uniprot_search_counts,
)
from protein_detective.pdbe.fetch import fetch as pdbe_fetch
from protein_detective.pdbe.io import (
    SingleChainQuery,
    SingleChainResult,
    write_single_chain_pdb_file,
)
from protein_detective.powerfit.parallel import configure_dask_scheduler
from protein_detective.uniprot import Query, search4af, search4pdb, search4uniprot

logger = logging.getLogger(__name__)


def search_structures_in_uniprot(query: Query, session_dir: Path, limit: int = 10_000) -> SearchCounts:
    """Searches for protein structures in UniProt database.

    Checks if the query results are already in another session with the same query.
    If found will copy them instead of fetching them from Uniprot SPARQL endpoint again.

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

    # Reuse existing search results in the current session database
    with connect(session_dir) as con:
        if uniprot_query_exists(query, limit, con):
            logger.warning(
                "Results of this UniProt query already exists in the session database. "
                "Not querying Uniprot SPARQL endpoint again."
                "To force re-query, delete the session database."
            )
            return uniprot_search_counts(con)

    counts = try_reusing_search_results_from_another_session(query, session_dir, limit)
    if counts is not None:
        return counts

    # Perform the searches in UniProt
    uniprot_accessions = search4uniprot(query, limit)
    pdbs = search4pdb(uniprot_accessions, limit=limit)
    af_result = search4af(uniprot_accessions, limit=limit)

    # Store in db
    with connect(session_dir) as con:
        save_query(query, limit, con)
        save_uniprot_accessions(uniprot_accessions, con)
        nr_pdbs, nr_prot2pdb = save_pdbs(pdbs, con)
        nr_afs = save_alphafolds(af_result, con)

    return len(uniprot_accessions), nr_pdbs, nr_prot2pdb, nr_afs


def retrieve_pdbe_structures(session_dir: Path) -> tuple[Path, int]:
    """Retrieve structure files from PDBe for the Uniprot entries in the session.

    Does not download files that are already downloaded in the session.
    Checks if the files are already downloaded in another session with the same query
    if found will symlink them instead of downloading again.

    Args:
        session_dir: The directory to store downloaded files and the session database.

    Returns:
        A tuple containing the download directory and the number of PDBe mmCIF files downloaded.
    """
    download_dir = session_dir / "downloads"
    download_dir.mkdir(parents=True, exist_ok=True)

    # Do not download or symlink if files are already there.
    # The database has columns for paths that are NULL when the file has not been retrieved.
    # need to check that non null values are on the file system.
    with connect(session_dir, read_only=True) as con:
        pdbs = load_pdbs(con)
    retrieved_files = [p.mmcif_file for p in pdbs if p.mmcif_file is not None and p.mmcif_file.exists()]
    if len(pdbs) == len(retrieved_files):
        logger.warning("All PDBe files already downloaded in this session. Not downloading again.")
        return download_dir, len(retrieved_files)

    cached_session_dir = find_session_with_same_query(session_dir)
    if cached_session_dir:
        return download_dir, symlink_cached_pdbe_files(session_dir, download_dir, cached_session_dir)

    # Download mmCIF files from PDBe for the Uniprot entries in the session.
    pdb_ids = {p.id for p in pdbs}
    mmcif_files = pdbe_fetch(pdb_ids, download_dir)

    with connect(session_dir) as con:
        # make paths relative to session_dir, so db stores paths relative to session_dir
        sr_mmcif_files = {pdb_id: mmcif_file.relative_to(session_dir) for pdb_id, mmcif_file in mmcif_files.items()}
        save_pdb_files(sr_mmcif_files, con)

    return download_dir, len(mmcif_files)


def retrieve_alphafold_structures(session_dir: Path, what: set[DownloadableFormat]) -> tuple[Path, int]:
    """Retrieve structure files from AlphaFold database for the Uniprot entries in the session.

    Does not download files that are already downloaded in the session.
    Checks if the files are already downloaded in another session with the same query
    if found will symlink them instead of downloading again.

    Args:
        session_dir: The directory to store downloaded files and the session database.
        what: A set of formats to download from AlphaFold.

    Returns:
        A tuple containing the download directory and the number of AlphaFold entries downloaded.
    """
    download_dir = session_dir / "downloads"
    download_dir.mkdir(parents=True, exist_ok=True)

    # check if all AlphaFold files are already downloaded in the session
    with connect(session_dir, read_only=True) as con:
        entries = load_alphafolds(con)
    nr_downloaded = 0
    nr_expected_downloaded = len(entries) * len(what)
    for entry in entries:
        for af_format in what:
            af_file = entry.by_format(af_format)
            if af_file is not None and af_file.exists():
                nr_downloaded += 1
    if nr_downloaded == nr_expected_downloaded:
        logger.warning("All AlphaFold files already downloaded in this session. Not downloading again.")
        return download_dir, len(entries)

    # find session with same query and symlink files
    cached_session_dir = find_session_with_same_query(session_dir)
    if cached_session_dir:
        return download_dir, symlink_cached_alphafold_files(session_dir, what, download_dir, cached_session_dir)

    # Download
    af_ids = {e.uniprot_acc for e in entries if e.uniprot_acc}
    afs = af_fetch(af_ids, download_dir, what=what)

    with connect(session_dir) as con:
        sr_afs = [af_relative_to(af, session_dir) for af in afs]
        save_alphafolds_files(sr_afs, con)
    return download_dir, len(afs)


WhatRetrieve = Literal["pdbe", "alphafold"]
"""Types of what to retrieve."""
what_retrieve_choices: set[WhatRetrieve] = {"pdbe", "alphafold"}
"""Set of what can be retrieved."""


def retrieve_structures(
    session_dir: Path, what: set[WhatRetrieve] | None = None, what_af_formats: set[DownloadableFormat] | None = None
) -> tuple[Path, int, int]:
    """Retrieve structure files from PDBe and AlphaFold databases for the Uniprot entries in the session.

    Does not download files that are already downloaded in the session.
    Checks if the files are already downloaded in another session with the same query
    if found will symlink them instead of downloading again.

    Args:
        session_dir: The directory to store downloaded files and the session database.
        what: A tuple of strings indicating which databases to retrieve files from.
        what_af_formats: A tuple of formats to download from AlphaFold. Defaults to {"pdb"}.

    Returns:
        A tuple containing the download directory, the number of PDBe mmCIF files downloaded,
        and the number of AlphaFold files downloaded.

    Raises:
        ValueError: If `what` is not a subset of `what_retrieve_choices`
    """
    session_dir.mkdir(parents=True, exist_ok=True)

    if what is None:
        what = {"pdbe", "alphafold"}
    if not (what <= what_retrieve_choices):
        msg = f"Invalid 'what' argument: {what}. Must be a subset of {what_retrieve_choices}."
        raise ValueError(msg)
    if len(what) == 0:
        msg = f"At least one of {what_retrieve_choices} must be specified in 'what'."
        raise ValueError(msg)
    if what_af_formats is None:
        what_af_formats = {"pdb"}

    nr_pdbe_files = 0
    download_dir = session_dir / "downloads"
    if "pdbe" in what:
        download_dir, nr_pdbe_files = retrieve_pdbe_structures(session_dir)
    nr_af_files = 0
    if "alphafold" in what:
        download_dir, nr_af_files = retrieve_alphafold_structures(session_dir, what_af_formats)
    return download_dir, nr_pdbe_files, nr_af_files


@dataclass
class DensityFilterSessionResult:
    """Stats of density filtering.

    Parameters:
        density_filtered_dir: The directory where the filtered PDB files are stored.
        nr_kept: The number of structures that were kept after filtering.
        nr_discarded: The number of structures that were discarded after filtering.
    """

    density_filtered_dir: Path
    nr_kept: int
    nr_discarded: int


def density_filter(session_dir: Path, query: DensityFilterQuery) -> DensityFilterSessionResult:
    """Filter the AlphaFoldDB structures based on density confidence.

    In AlphaFold PDB files, the b-factor column has the
    predicted local distance difference test (pLDDT).
    All residues with a b-factor above the confidence threshold are counted.
    Then if the count is outside the min and max threshold, the structure is filtered out.
    The remaining structures have the residues with a b-factor below the confidence threshold removed.
    And are written to the session_dir / "density_filtered" directory.

    Args:
        session_dir: The directory where the session database is stored.
        query: The density filter query containing the confidence thresholds.

    Returns:
        Stats of density filtering.
    """
    density_filtered_dir = session_dir / "density_filtered"
    density_filtered_dir.mkdir(parents=True, exist_ok=True)

    with connect(session_dir) as con:
        afs = load_alphafolds(con)
        alphafold_pdb_files = [e.pdb_file for e in afs if e.pdb_file is not None]
        uniproc_accs = [e.uniprot_acc for e in afs]

        density_filtered = list(filter_on_density(alphafold_pdb_files, query, density_filtered_dir))
        for e in density_filtered:
            if e.density_filtered_file is not None:
                e.density_filtered_file = e.density_filtered_file.relative_to(session_dir)

        save_density_filtered(
            query,
            density_filtered,
            uniproc_accs,
            con,
        )
        nr_kept = len([e for e in density_filtered if e.density_filtered_file is not None])
        nr_discarded = len(density_filtered) - nr_kept
        return DensityFilterSessionResult(
            density_filtered_dir=density_filtered_dir,
            nr_kept=nr_kept,
            nr_discarded=nr_discarded,
        )


def prune_pdbs(
    session_dir: Path, query: SingleChainQuery, scheduler_address: str | Cluster | None = None
) -> tuple[Path, int]:
    """Prune the PDB files to only keep the first chain of the found Uniprot entries.

    Only writes PDB files that have a single chain with a number of residues
    between `min_residues` and `max_residues` (inclusive).

    Also rename that chain to A.

    Args:
        session_dir: The directory where the session database is stored.
        query: The single chain query containing the minimum and maximum number of residues.
        scheduler_address: Address of the Dask scheduler or a Cluster instance or None for local execution.

    Returns:
        A tuple containing the directory where the single chain PDB files are stored,
        and the number of PDB files that passed the residue filter and where written.
    """
    single_chain_dir = session_dir / "single_chain"
    single_chain_dir.mkdir(parents=True, exist_ok=True)

    with connect(session_dir, read_only=True) as con:
        proteinpdbs = load_pdbs(con)

    # TODO reuse dask scheduler?
    # TODO make function lazy?
    scheduler_address = configure_dask_scheduler(
        None,
        name="prune-pdbs",
    )

    with Client(scheduler_address) as client:
        logger.info(f"Follow progress on dask dashboard at: {client.dashboard_link}")
        futures = client.map(
            write_single_chain_pdb_file,
            proteinpdbs,
            session_dir=session_dir,
            single_chain_dir=single_chain_dir,
            query=query,
        )

        progress(futures)

        results = client.gather(futures)
        new_files = cast("list[SingleChainResult]", results)

    with connect(session_dir) as con:
        save_single_chain_pdb_files(new_files, query, con)

    return single_chain_dir, len([f for f in new_files if f.passed])
