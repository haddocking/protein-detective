"""Workflow steps"""

import dataclasses
import hashlib
import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, cast

from dask.distributed import Client, progress
from distributed.deploy.cluster import Cluster
from platformdirs import user_cache_dir

from protein_detective.alphafold import DownloadableFormat
from protein_detective.alphafold import fetch_many as af_fetch
from protein_detective.alphafold import relative_to as af_relative_to
from protein_detective.alphafold.density import DensityFilterQuery, filter_on_density
from protein_detective.db import (
    connect,
    copy_search_results,
    load_alphafold_ids,
    load_alphafolds,
    load_pdb_ids,
    load_pdbs,
    load_uniprot_queries,
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

cache_dir = Path(user_cache_dir("protein-detective", ensure_exists=True))
cache_uniprot_root = cache_dir / "uniprot"
cache_uniprot_root.mkdir(parents=True, exist_ok=True)


def _generate_query_hash(query: Query, limit: int) -> str:
    query_dict = asdict(query)
    query_dict["limit"] = limit
    body = json.dumps(query_dict, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


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

    # Reuse cached results in other sessions
    qhash = _generate_query_hash(query, limit)
    cache_path = cache_uniprot_root / qhash
    if cache_path.exists():
        cached_session_dir = cache_path.readlink()
        if session_dir.absolute() != cached_session_dir.absolute() and cached_session_dir.exists():
            with connect(session_dir) as con:
                logger.warning(f"Query seen before, copying search results from {cached_session_dir} session.")
                copy_search_results(cached_session_dir, con)
                # TODO if cached session dir has files downloaded also copy those, do in `retrieve_structures()`
    else:
        cache_path.symlink_to(session_dir.absolute())

    # Reuse existing search results in the current session database
    with connect(session_dir) as con:
        if uniprot_query_exists(query, limit, con):
            logger.warning(
                "Results of this UniProt query already exists in the session database. "
                "Not querying Uniprot SPARQL endpoint again."
            )
            return uniprot_search_counts(con)

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
    session_dir.mkdir(parents=True, exist_ok=True)
    download_dir = session_dir / "downloads"
    download_dir.mkdir(parents=True, exist_ok=True)

    # Check if there is an another session with same query and downloaded files
    with connect(session_dir, read_only=True) as con:
        uniprot_queries = load_uniprot_queries(con)
    if not uniprot_queries:
        msg = "No UniProt queries results found in the session database. Please run a search first."
        raise ValueError(msg)
    query, limit = uniprot_queries[0]
    qhash = _generate_query_hash(query, limit)
    cache_path = cache_uniprot_root / qhash
    if cache_path.exists() and cache_path != session_dir:
        if "pdbe" in what_retrieve_choices:
            with connect(cache_path, read_only=True) as cache_con:
                cached_pdbes = load_pdbs(cache_con)
            if cached_pdbes:
                logger.warning(
                    'PDBe files already downloaded in session "%s". Symlinking instead of downloading.', cache_path
                )
            linked_files = {}
            for pdb in cached_pdbes:
                if pdb.mmcif_file:
                    current_pdb = download_dir / pdb.mmcif_file.name
                    if current_pdb.exists():
                        continue
                    current_pdb.symlink_to(pdb.mmcif_file.resolve())
                    linked_files[pdb.id] = current_pdb.relative_to(session_dir)
            with connect(session_dir) as scon:
                save_pdb_files(linked_files, scon)
        if "alphafold" in what_retrieve_choices and cache_path.exists() and cache_path != session_dir:
            with connect(cache_path, read_only=True) as cache_con:
                cached_afs = load_alphafolds(cache_con)
            if cached_afs:
                logger.warning(
                    'AlphaFold files already downloaded in session "%s". Symlinking instead of downloading.', cache_path
                )
            current_afs = []
            for af in cached_afs:
                # TODO also handle other files like pae, but only pdb is needed for now
                if af.pdb_file:
                    current_af_pdb = download_dir / af.pdb_file.name
                    if not current_af_pdb.exists():
                        current_af_pdb.symlink_to(af.pdb_file.resolve())
                    current_af = dataclasses.replace(af, pdb_file=current_af_pdb.relative_to(session_dir))
                    current_afs.append(current_af)
            with connect(session_dir) as scon:
                save_alphafolds_files(current_afs, scon)
    if linked_files or current_afs:
        return download_dir, len(linked_files), len(current_afs)

    if what is None:
        what = {"pdbe", "alphafold"}
    if not (what <= what_retrieve_choices):
        msg = f"Invalid 'what' argument: {what}. Must be a subset of {what_retrieve_choices}."
        raise ValueError(msg)

    sr_mmcif_files = {}
    if "pdbe" in what:
        # mmCIF files from PDBe for the Uniprot entries in the session.
        pdb_ids = set()
        with connect(session_dir, read_only=True) as con:
            pdb_ids = load_pdb_ids(con)

        mmcif_files = pdbe_fetch(pdb_ids, download_dir)

        with connect(session_dir) as con:
            # make paths relative to session_dir, so db stores paths relative to session_dir
            sr_mmcif_files = {pdb_id: mmcif_file.relative_to(session_dir) for pdb_id, mmcif_file in mmcif_files.items()}
            save_pdb_files(sr_mmcif_files, con)

    afs = []
    if "alphafold" in what:
        # AlphaFold entries for the given query
        af_ids = set()
        with connect(session_dir, read_only=True) as con:
            af_ids = load_alphafold_ids(con)

        afs = af_fetch(af_ids, download_dir, what=what_af_formats)

        with connect(session_dir) as con:
            sr_afs = [af_relative_to(af, session_dir) for af in afs]
            save_alphafolds_files(sr_afs, con)

    return download_dir, len(sr_mmcif_files), len(afs)


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
