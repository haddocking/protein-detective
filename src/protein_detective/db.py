
ddl = """\
CREATE TABLE IF NOT EXISTS proteins (
    uniprot_id TEXT PRIMARY KEY,
);

CREATE TABLE IF NOT EXISTS pdbs (
    pdb_id TEXT PRIMARY KEY,
    method TEXT NOT NULL,
    chain TEXT NOT NULL,
    resolution REAL,
)

CREATE TABLE IF NOT EXISTS proteins_pdbs (
    uniprot_id TEXT,
    pdb_id TEXT,
    FOREIGN KEY (uniprot_id) REFERENCES proteins (uniprot_id),
    FOREIGN KEY (pdb_id) REFERENCES pdbs (pdb_id),
    PRIMARY KEY (uniprot_id, pdb_id)
);
"""
