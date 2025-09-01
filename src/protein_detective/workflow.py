"""Workflow steps"""

import asyncio
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from distributed.deploy.cluster import Cluster
from protein_quest.alphafold.confidence import ConfidenceFilterQuery, filter_files_on_confidence
from protein_quest.alphafold.fetch import DownloadableFormat
from protein_quest.alphafold.fetch import fetch_many as af_fetch
from protein_quest.alphafold.fetch import relative_to as af_relative_to
from protein_quest.filters import filter_files_on_chain, filter_files_on_residues
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
    save_confidence_filtered,
    save_pdb_files,
    save_pdbs,
    save_query,
    save_single_chain_pdb_files,
    save_uniprot_accessions,
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
    session_dir.mkdir(parents=True, exist_ok=True)
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

            # TODO use sync version
            mmcif_files = asyncio.run(pdbe_fetch(pdb_ids, download_pdbe_dir))

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

            afs = af_fetch(af_ids, download_af_dir, what=what_af_formats)

            sr_afs = [af_relative_to(af, session_dir) for af in afs]
            # the af_fetch downloads summaries as <uniprot_acc>.json files
            # TODO do store summary in db and in *.json files, pick one
            save_alphafolds_files(sr_afs, con)

    return download_dir, len(sr_mmcif_files), len(afs)


@dataclass
class ConfidenceFilterSessionResult:
    """Stats of confidence filtering.

    Parameters:
        filtered_dir: The directory where the filtered PDB files are stored.
        nr_kept: The number of structures that were kept after filtering.
        nr_discarded: The number of structures that were discarded after filtering.
    """

    filtered_dir: Path
    nr_kept: int
    nr_discarded: int


def confidence_filter(session_dir: Path, query: ConfidenceFilterQuery) -> ConfidenceFilterSessionResult:
    """Filter the AlphaFoldDB structures based on confidence.

    In AlphaFold PDB files, the b-factor column has the
    predicted local distance difference test (pLDDT).
    All residues with a b-factor above the confidence threshold are counted.
    Then if the count is outside the min and max threshold, the structure is filtered out.
    The remaining structures have the residues with a b-factor below the confidence threshold removed.
    And are written to the session_dir / "confidence_filtered" directory.

    Args:
        session_dir: The directory where the session database is stored.
        query: The confidence filter query containing the confidence thresholds.

    Returns:
        Stats of confidence filtering.
    """
    filtered_dir = session_dir / "confidence_filtered"
    filtered_dir.mkdir(parents=True, exist_ok=True)

    with connect(session_dir) as con:
        afs = load_alphafolds(con)
        alphafold_cif_files = [e.cif_file for e in afs if e.cif_file is not None]
        uniprot_accs = [e.uniprot_acc for e in afs]

        filtered = list(filter_files_on_confidence(alphafold_cif_files, query, filtered_dir))
        for e in filtered:
            if e.filtered_file is not None:
                e.filtered_file = e.filtered_file.relative_to(session_dir)

        save_confidence_filtered(
            query,
            filtered,
            uniprot_accs,
            con,
        )
        nr_kept = len([e for e in filtered if e.filtered_file is not None])
        nr_discarded = len(filtered) - nr_kept
        return ConfidenceFilterSessionResult(
            filtered_dir=filtered_dir,
            nr_kept=nr_kept,
            nr_discarded=nr_discarded,
        )


def prune_pdbs(
    session_dir: Path, min_residues: int, max_residues: int, scheduler_address: str | Cluster | None
) -> tuple[Path, int]:
    """Prune the PDB files to only keep the first chain of the found Uniprot entries.

    Only writes PDB files that have a single chain with a number of residues
    between `min_residues` and `max_residues` (inclusive).

    Also rename that chain to A.

    Args:
        session_dir: The directory where the session database is stored.
        min_residues: The minimum number of residues for the single chain.
        max_residues: The maximum number of residues for the single chain.
        scheduler_address: The address of the Dask scheduler.

    Returns:
        A tuple containing the directory where the single chain PDB files are stored,
        and the number of PDB files that passed the residue filter and where written.
    """
    single_chain_dir = session_dir / "single_chain"
    single_chain_dir.mkdir(parents=True, exist_ok=True)

    with connect(session_dir, read_only=True) as con:
        proteinpdbs = load_pdbs(con)

    # this code looks more complicated than I want to because:
    # In protein-quest we are just working with pdb files,
    # but in protein-detective we keep track which
    # pdb+chain belongs to which uniprot entry
    # so there is a lot of bookkeeping needed
    path2chains = {(p.mmcif_file, p.chain) for p in proteinpdbs if p.mmcif_file is not None}

    with tempfile.TemporaryDirectory() as intermediate_dir:
        intermediate_path = Path(intermediate_dir)
        logger.debug("Writing intermediate files to %s", intermediate_dir)

        logger.info("Filtering PDB files on chain")
        chain_filtered = filter_files_on_chain(path2chains, intermediate_path, scheduler_address=scheduler_address)
        intermediate_files = [f.output_file for f in chain_filtered if f.output_file is not None]
        logger.info("Write %i files with just chain A", len(intermediate_files))
        logger.info("Filtering PDB files on number of residues in chain A")
        residue_filtered = list(
            filter_files_on_residues(intermediate_files, single_chain_dir, min_residues, max_residues)
        )

    # make paths relative to session_dir, so db stores paths relative to session_dir
    for r in residue_filtered:
        if r.output_file is not None:
            r.output_file = r.output_file.relative_to(session_dir)

    with connect(session_dir) as con:
        save_single_chain_pdb_files(proteinpdbs, chain_filtered, residue_filtered, min_residues, max_residues, con)

    return single_chain_dir, len([f for f in residue_filtered if f.passed])
