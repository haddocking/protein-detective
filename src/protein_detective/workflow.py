from pathlib import Path

import duckdb

from protein_detective.alphafold import fetch_many as af_fetch
from protein_detective.db import ddl, save_alphafolds, save_pdbs, save_query
from protein_detective.pdbe import fetch as pdb_fetch
from protein_detective.uniprot import Query, search4af, search4pdb


def retrieve_structures(query: Query, session_dir: Path, limit=10_000):
    download_dir = session_dir / "downloads"
    download_dir.mkdir(parents=True, exist_ok=True)
    powerfit_candidate_dir = session_dir / "powerfit_candidates"
    powerfit_candidate_dir.mkdir(parents=True, exist_ok=True)

    # PDBe entries for the given query
    pdbs = search4pdb(query, limit=limit)
    pdb_ids: set[str] = set()
    for pdbresults in pdbs.values():
        for pdbresult in pdbresults:
            pdb_ids.add(pdbresult.id)
    pdb_files = pdb_fetch(pdb_ids, download_dir)
    pdb_files_lookup = dict(zip(pdb_ids, pdb_files, strict=True))

    # AlphaFold entries for the given query
    af_result = search4af(query, limit=limit)
    af_ids = set(af_result.keys())
    afs = af_fetch(af_ids, download_dir)

    db_path = session_dir / "session.db"
    con = duckdb.connect(db_path)
    con.sql(ddl)
    save_query(query, con)
    save_pdbs(pdbs, pdb_files_lookup, con)
    save_alphafolds(afs, con)
    return db_path


def prepare_structures(session_dir: Path):
    # TODO Save processed structures to the powerfit_candidate_dir
    # TODO For each pdb structure remove the low confidence regions

    # TODO For each af structure remove the low confidence regions
    pass
