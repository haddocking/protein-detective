from pathlib import Path

import duckdb

from protein_detective.alphafold import fetch_many as af_fetch
from protein_detective.db import ddl
from protein_detective.pdbe import fetch as pdb_fetch
from protein_detective.uniprot import Query, search4af, search4pdb


async def flow(query: Query, session_dir: Path):
    download_dir = session_dir / "downloads"
    download_dir.mkdir(parents=True, exist_ok=True)
    powerfit_candidate_dir = session_dir / "powerfit_candidates"
    powerfit_candidate_dir.mkdir(parents=True, exist_ok=True)

    # PDBe entries for the given query
    pdbs = search4pdb(query)
    pdb_ids = set()
    for pdbresults in pdbs.values():
        for pdbresult in pdbresults:
            pdb_ids.add(pdbresult.id)
    await pdb_fetch(pdb_ids, download_dir)

    # AlphaFold entries for the given query
    af_result = search4af(query)
    af_ids = set(af_result.keys())
    afs = [af async for af in af_fetch(af_ids, download_dir)]

    db_path = session_dir / "session.db"
    con = duckdb.connect(db_path)
    con.sql(ddl)
    # TODO Store uniprot -> structure mapping in sqlite/duckdb db

    # TODO Store alphafold summaries in the db

    # TODO Save processed structures to the powerfit_candidate_dir
    # TODO For each pdb structure remove the low confidence regions

    # TODO For each af structure remove the low confidence regions
