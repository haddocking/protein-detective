from dataclasses import dataclass
from pathlib import Path

from protein_detective.alphafold import fetch_many as af_fetch
from protein_detective.alphafold.density import DensityFilterQuery, filter_on_density
from protein_detective.db import (
    connect,
    load_alphafolds,
    load_pdbs,
    save_alphafolds,
    save_density_filtered,
    save_pdbs,
    save_query,
    save_single_chain_pdb_files,
    save_uniprot_accessions,
)
from protein_detective.pdbe.fetch import fetch as pdb_fetch
from protein_detective.pdbe.io import write_single_chain_pdb_files
from protein_detective.uniprot import Query, search4af, search4pdb, search4uniprot


def retrieve_structures(query: Query, session_dir: Path, limit=10_000) -> tuple[Path, int, int]:
    """Find uniprot entries based on query and
    retrieve structure files from PDBe and AlphaFold databases for the found Uniprot entries.

    Args:
        query: The search query.
        session_dir: The directory to store downloaded files and the session database.
        limit: The maximum number of results to retrieve.

    Returns:
        The path to the DuckDB database containing non-file data like
        * AlphaFold entry summaries and
        * Which PDB chains correspond to which Uniprot accessions.
        And the number of PDBe and AlphaFoldDB entries found.
    """
    session_dir.mkdir(parents=True, exist_ok=True)
    download_dir = session_dir / "downloads"
    download_dir.mkdir(parents=True, exist_ok=True)

    uniprot_accessions = search4uniprot(query, limit)

    # PDBe entries for the given query
    pdbs = search4pdb(uniprot_accessions, limit=limit)
    pdb_ids: set[str] = set()
    for pdbresults in pdbs.values():
        for pdbresult in pdbresults:
            pdb_ids.add(pdbresult.id)
    pdb_files = pdb_fetch(pdb_ids, download_dir)
    # make paths in pdbs relative to session_dir, so db stores paths relative to session_dir
    sr_pdb_files = {pdb_id: pdb_file.relative_to(session_dir) for pdb_id, pdb_file in pdb_files.items()}

    # AlphaFold entries for the given query
    af_result = search4af(uniprot_accessions, limit=limit)
    af_ids = set(af_result.keys())
    afs = af_fetch(af_ids, download_dir)
    for af in afs:
        af.pdb_file = af.pdb_file.relative_to(session_dir)

    with connect(session_dir) as con:
        save_query(query, con)
        save_uniprot_accessions(uniprot_accessions, con)
        save_pdbs(pdbs, sr_pdb_files, con)
        save_alphafolds(afs, con)
    return download_dir, len(sr_pdb_files), len(afs)


@dataclass
class DensityFilterSessionResult:
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

    """
    density_filtered_dir = session_dir / "density_filtered"
    density_filtered_dir.mkdir(parents=True, exist_ok=True)

    with connect(session_dir) as conn:
        afs = load_alphafolds(conn)
        alphafold_pdb_files = [session_dir / e.pdb_file for e in afs]
        uniproc_accs = [e.uniprot_acc for e in afs]

        density_filtered = list(filter_on_density(alphafold_pdb_files, query, density_filtered_dir))
        for e in density_filtered:
            if e.density_filtered_file is not None:
                e.density_filtered_file = e.density_filtered_file.relative_to(session_dir)

        save_density_filtered(
            query,
            density_filtered,
            uniproc_accs,
            conn,
        )
        nr_kept = len([e for e in density_filtered if e.density_filtered_file is not None])
        nr_discarded = len(density_filtered) - nr_kept
        return DensityFilterSessionResult(
            density_filtered_dir=density_filtered_dir,
            nr_kept=nr_kept,
            nr_discarded=nr_discarded,
        )


def prune_pdbs(session_dir: Path) -> tuple[Path, int]:
    """Prune the PDB files to only keep the first chain of the found Uniprot entries.

    And rename that chain to A.
    """
    single_chain_dir = session_dir / "single_chain"
    single_chain_dir.mkdir(parents=True, exist_ok=True)

    with connect(session_dir) as conn:
        proteinpdbs = load_pdbs(conn)
        new_files = list(write_single_chain_pdb_files(proteinpdbs, session_dir, single_chain_dir))
        save_single_chain_pdb_files(new_files, conn)

        return single_chain_dir, len(new_files)
