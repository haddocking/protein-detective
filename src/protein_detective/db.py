from collections.abc import Iterable
from pathlib import Path

from cattrs import unstructure
from duckdb import DuckDBPyConnection

from protein_detective.alphafold import AlphaFoldEntry
from protein_detective.uniprot import PdbResult, Query

ddl = """\
CREATE TABLE IF NOT EXISTS uniprot_searches (
    query JSON,
);

CREATE TABLE IF NOT EXISTS proteins (
    uniprot_acc TEXT PRIMARY KEY,
);

CREATE TABLE IF NOT EXISTS pdbs (
    pdb_id TEXT PRIMARY KEY,
    method TEXT NOT NULL,
    resolution REAL,
    pdb_file TEXT,
);

-- pdb could have multiple proteins so use many-to-many table
CREATE TABLE IF NOT EXISTS proteins_pdbs (
    uniprot_acc TEXT,
    pdb_id TEXT,
    chain TEXT NOT NULL,
    FOREIGN KEY (uniprot_acc) REFERENCES proteins (uniprot_acc),
    FOREIGN KEY (pdb_id) REFERENCES pdbs (pdb_id),
    PRIMARY KEY (uniprot_acc, pdb_id)
);

CREATE TABLE IF NOT EXISTS alphafolds (
    uniprot_acc TEXT PRIMARY KEY,
    summary JSON,
    pdb_file TEXT,
    pae_file TEXT,
)

"""


def save_query(query: Query, con: DuckDBPyConnection):
    con.execute("INSERT INTO uniprot_searches (query) VALUES (?)", (unstructure(query),))


def save_uniprot_accessions(uniprot_accessions: Iterable[str], con: DuckDBPyConnection):
    con.executemany(
        "INSERT OR IGNORE INTO proteins (uniprot_acc) VALUES (?)",
        [(uniprot_acc,) for uniprot_acc in uniprot_accessions],
    )


def save_pdbs(uniprot2pdbs: dict[str, set[PdbResult]], pdb_files: dict[str, Path], con: DuckDBPyConnection):
    save_uniprot_accessions(uniprot2pdbs.keys(), con)
    pdb_rows = []
    for pdb_results in uniprot2pdbs.values():
        pdb_rows.extend([(pdb.id, pdb.method, pdb.resolution, str(pdb_files[pdb.id])) for pdb in pdb_results])
    con.executemany("INSERT OR IGNORE INTO pdbs (pdb_id, method, resolution, pdb_file) VALUES (?, ?, ?, ?)", pdb_rows)
    prot2pdb_rows = []
    for uniprot_acc, pdb_results in uniprot2pdbs.items():
        prot2pdb_rows.extend([(uniprot_acc, pdb.id, pdb.chain) for pdb in pdb_results])
    con.executemany("INSERT OR IGNORE INTO proteins_pdbs (uniprot_acc, pdb_id, chain) VALUES (?, ?, ?)", prot2pdb_rows)


def save_alphafolds(afs: list[AlphaFoldEntry], con: DuckDBPyConnection):
    af_rows = []
    for af in afs:
        uniprot_acc = af.summary.uniprotAccession
        summary = unstructure(af.summary)
        pdb_file = str(af.pdb_file)
        pae_file = str(af.pae_file)
        af_rows.append((uniprot_acc, summary, pdb_file, pae_file))
    con.executemany(
        "INSERT OR IGNORE INTO alphafolds (uniprot_acc, summary, pdb_file, pae_file) VALUES (?, ?, ?, ?)", af_rows
    )
    protein_rows = [af.summary.uniprotAccession for af in afs]
    save_uniprot_accessions(protein_rows, con)
