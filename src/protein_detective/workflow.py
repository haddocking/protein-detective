from pathlib import Path

import duckdb

from protein_detective.alphafold import fetch_many as af_fetch
from protein_detective.alphafold.density import filter_on_density
from protein_detective.db import ddl, save_alphafolds, save_pdbs, save_query, save_uniprot_accessions
from protein_detective.pdbe import fetch as pdb_fetch
from protein_detective.uniprot import Query, search4af, search4pdb, search4uniprot


def retrieve_structures(query: Query, session_dir: Path, limit=10_000) -> Path:
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
    """
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
    pdb_files_lookup = dict(zip(pdb_ids, pdb_files, strict=True))

    # AlphaFold entries for the given query
    af_result = search4af(uniprot_accessions, limit=limit)
    af_ids = set(af_result.keys())
    afs = af_fetch(af_ids, download_dir)

    db_path = session_dir / "session.db"
    con = duckdb.connect(db_path)
    con.sql(ddl)
    save_query(query, con)
    save_uniprot_accessions(uniprot_accessions, con)
    save_pdbs(pdbs, pdb_files_lookup, con)
    save_alphafolds(afs, con)
    return db_path


def prepare_structures(session_dir: Path):
    # TODO Save processed structures to the powerfit_candidate_dir
    # TODO For each pdb structure remove the low confidence regions

    # TODO For each af structure remove the low confidence regions
    pass


def density_filter(session_dir: Path, confidence: float, min_threshold: int, max_threshold: int):
    """Filter the structures based on density confidence.

    For AlphaFoldDB entries use the b-factor column of the PDB file.
    All residues with a b-factor above the confidence threshold are counted.
    Then if the count is outside the min and max threshold, the structure is filtered out.
    The remaining structures have the residues with a b-factor below the confidence threshold removed.
    And are written to the session_dir / "density_filtered" directory.

    """
    density_filtered = filter_on_density(session_dir, confidence, min_threshold, max_threshold)

    # TODO store filter workflow step args in db
    # TODO store which files where filtered in db
