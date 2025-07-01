"""Workflow steps"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from protein_detective.alphafold import DownloadableFormat
from protein_detective.alphafold import fetch_many as af_fetch
from protein_detective.alphafold import relative_to as af_relative_to
from protein_detective.alphafold.density import DensityFilterQuery, filter_on_density
from protein_detective.db import (
    connect,
    load_alphafold_ids,
    load_alphafolds,
    load_pdb_ids,
    load_pdbs,
    save_alphafolds,
    save_alphafolds_files,
    save_density_filtered,
    save_pdb_files,
    save_pdbs,
    save_query,
    save_single_chain_pdb_files,
    save_uniprot_accessions,
)
from protein_detective.pdbe.fetch import fetch as pdbe_fetch
from protein_detective.pdbe.io import SingleChainQuery, write_single_chain_pdb_files
from protein_detective.uniprot import Query, search4af, search4pdb, search4uniprot

logger = logging.getLogger(__name__)


def search_structures_in_uniprot(query: Query, session_dir: Path, limit: int = 10_000) -> tuple[int, int, int]:
    """Searches for protein structures in UniProt database.

    Args:
        query: The search query.
        session_dir: The directory to store the search results.
        limit: The maximum number of results to return from each database query.

    Returns:
        A tuple containing the number of UniProt accessions, the number of PDB structures,
        and the number of AlphaFold structures found.
    """
    session_dir.mkdir(parents=True, exist_ok=True)

    uniprot_accessions = search4uniprot(query, limit)
    pdbs = search4pdb(uniprot_accessions, limit=limit)
    af_result = search4af(uniprot_accessions, limit=limit)

    with connect(session_dir) as con:
        save_query(query, con)
        save_uniprot_accessions(uniprot_accessions, con)
        save_pdbs(pdbs, con)
        save_alphafolds(af_result, con)

    nr_pdbs = len(set().union(*pdbs.values()))
    nr_afs = len(set().union(*af_result.values()))
    return len(uniprot_accessions), nr_pdbs, nr_afs


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
        # mmCIF files from PDBe for the Uniprot entries in the session.
        pdb_ids = set()
        with connect(session_dir) as con:
            pdb_ids = load_pdb_ids(con)

            mmcif_files = pdbe_fetch(pdb_ids, download_dir)

            # make paths relative to session_dir, so db stores paths relative to session_dir
            sr_mmcif_files = {pdb_id: mmcif_file.relative_to(session_dir) for pdb_id, mmcif_file in mmcif_files.items()}
            save_pdb_files(sr_mmcif_files, con)

    afs = []
    if "alphafold" in what:
        # AlphaFold entries for the given query
        af_ids = set()
        with connect(session_dir) as con:
            af_ids = load_alphafold_ids(con)

            afs = af_fetch(af_ids, download_dir, what=what_af_formats)

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


def prune_pdbs(session_dir: Path, query: SingleChainQuery) -> tuple[Path, int]:
    """Prune the PDB files to only keep the first chain of the found Uniprot entries.

    Only writes PDB files that have a single chain with a number of residues
    between `min_residues` and `max_residues` (inclusive).

    Also rename that chain to A.

    Args:
        session_dir: The directory where the session database is stored.
        query: The single chain query containing the minimum and maximum number of residues.

    Returns:
        A tuple containing the directory where the single chain PDB files are stored,
        and the number of PDB files that passed the residue filter and where written.
    """
    single_chain_dir = session_dir / "single_chain"
    single_chain_dir.mkdir(parents=True, exist_ok=True)

    with connect(session_dir) as con:
        proteinpdbs = load_pdbs(con)
        new_files = list(
            write_single_chain_pdb_files(
                proteinpdbs,
                session_dir,
                single_chain_dir=single_chain_dir,
                query=query,
            )
        )
        save_single_chain_pdb_files(new_files, query, con)

        return single_chain_dir, len([f for f in new_files if f.passed])
