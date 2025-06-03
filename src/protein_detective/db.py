from collections.abc import Iterable, Mapping
from contextlib import contextmanager
from pathlib import Path

from cattrs import unstructure
from cattrs.preconf.json import make_converter
from duckdb import DuckDBPyConnection
from duckdb import connect as duckdb_connect

from protein_detective.alphafold import AlphaFoldEntry
from protein_detective.alphafold.density import DensityFilterQuery, DensityFilterResult
from protein_detective.alphafold.entry_summary import EntrySummary
from protein_detective.pdbe.io import ProteinPdbRow, SingleChainResult
from protein_detective.uniprot import PdbResult, Query

converter = make_converter()

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
    pdb_file TEXT NOT NULL,
);

-- pdb could have multiple proteins so use many-to-many table
CREATE TABLE IF NOT EXISTS proteins_pdbs (
    uniprot_acc TEXT NOT NULL,
    pdb_id TEXT NOT NULL,
    chain TEXT NOT NULL,
    single_chain_pdb_file TEXT,
    FOREIGN KEY (uniprot_acc) REFERENCES proteins (uniprot_acc),
    FOREIGN KEY (pdb_id) REFERENCES pdbs (pdb_id),
    PRIMARY KEY (uniprot_acc, pdb_id)
);

CREATE TABLE IF NOT EXISTS alphafolds (
    uniprot_acc TEXT PRIMARY KEY,
    summary JSON NOT NULL,
    pdb_file TEXT NOT NULL,
    pae_file TEXT NOT NULL,
);

CREATE SEQUENCE IF NOT EXISTS id_density_filters START 1;
CREATE TABLE IF NOT EXISTS density_filters (
    density_filter_id INTEGER DEFAULT nextval('id_density_filters') PRIMARY KEY,
    confidence REAL NOT NULL,
    min_threshold INTEGER NOT NULL,
    max_threshold INTEGER NOT NULL,
    UNIQUE (confidence, min_threshold, max_threshold)
);

CREATE TABLE IF NOT EXISTS density_filtered_alphafolds (
    density_filter_id INTEGER NOT NULL,
    uniprot_acc TEXT NOT NULL,
    nr_residues_above_confidence INTEGER NOT NULL,
    keep BOOLEAN,
    pdb_file TEXT,
    PRIMARY KEY (density_filter_id, uniprot_acc),
    FOREIGN KEY (density_filter_id) REFERENCES density_filters (density_filter_id),
    FOREIGN KEY (uniprot_acc) REFERENCES alphafolds (uniprot_acc),
);
"""


def db_path(session_dir: Path) -> Path:
    """Return the path to the DuckDB database file in the given session directory."""
    return session_dir / "session.db"


@contextmanager
def connect(session_dir: Path):
    # wrapper around duckdb.connect to create tables on connect
    database = db_path(session_dir)
    con = duckdb_connect(database)
    con.sql(ddl)
    yield con
    con.close()


def save_query(query: Query, con: DuckDBPyConnection):
    con.execute("INSERT INTO uniprot_searches (query) VALUES (?)", (unstructure(query),))


def save_uniprot_accessions(uniprot_accessions: Iterable[str], con: DuckDBPyConnection):
    rows = [(uniprot_acc,) for uniprot_acc in uniprot_accessions]
    if len(rows) == 0:
        return
    con.executemany(
        "INSERT OR IGNORE INTO proteins (uniprot_acc) VALUES (?)",
        rows,
    )


def save_pdbs(
    uniprot2pdbs: Mapping[str, Iterable[PdbResult]],
    pdb_files: Mapping[str, Path],
    con: DuckDBPyConnection,
):
    save_uniprot_accessions(uniprot2pdbs.keys(), con)
    pdb_rows = []
    for pdb_results in uniprot2pdbs.values():
        pdb_rows.extend([(pdb.id, pdb.method, pdb.resolution, str(pdb_files[pdb.id])) for pdb in pdb_results])
    if len(pdb_rows) > 0:
        con.executemany(
            "INSERT OR IGNORE INTO pdbs (pdb_id, method, resolution, pdb_file) VALUES (?, ?, ?, ?)",
            pdb_rows,
        )
    prot2pdb_rows = []
    for uniprot_acc, pdb_results in uniprot2pdbs.items():
        prot2pdb_rows.extend([(uniprot_acc, pdb.id, pdb.chain) for pdb in pdb_results])
    if len(prot2pdb_rows) == 0:
        return
    con.executemany(
        "INSERT OR IGNORE INTO proteins_pdbs (uniprot_acc, pdb_id, chain) VALUES (?, ?, ?)",
        prot2pdb_rows,
    )


def load_pdbs(con: DuckDBPyConnection) -> list[ProteinPdbRow]:
    query = """
    SELECT p.uniprot_acc, p.pdb_id, p.pdb_file, pp.chain
    FROM proteins_pdbs pp
    JOIN pdbs p ON pp.pdb_id = p.pdb_id
    """
    rows = con.execute(query).fetchall()
    return [
        ProteinPdbRow(
            uniprot_acc=row[0],
            id=row[1],
            pdb_file=Path(row[2]),
            chain=row[3],
        )
        for row in rows
    ]


def save_alphafolds(afs: list[AlphaFoldEntry], con: DuckDBPyConnection):
    af_rows = []
    for af in afs:
        uniprot_acc = af.uniprot_acc
        summary = unstructure(af.summary)
        pdb_file = str(af.pdb_file)
        pae_file = str(af.pae_file)
        af_rows.append((uniprot_acc, summary, pdb_file, pae_file))
    con.executemany(
        "INSERT OR IGNORE INTO alphafolds (uniprot_acc, summary, pdb_file, pae_file) VALUES (?, ?, ?, ?)",
        af_rows,
    )
    protein_rows = [af.summary.uniprotAccession for af in afs]
    save_uniprot_accessions(protein_rows, con)


def load_alphafolds(con: DuckDBPyConnection) -> list[AlphaFoldEntry]:
    query = """
    SELECT summary, pdb_file, pae_file
    FROM alphafolds
    """
    rows = con.execute(query).fetchall()
    return [
        AlphaFoldEntry(
            summary=converter.loads(row[0], EntrySummary),
            pdb_file=Path(row[1]),
            pae_file=Path(row[2]),
        )
        for row in rows
    ]


def save_single_chain_pdb_files(files: list[SingleChainResult], con: DuckDBPyConnection):
    con.executemany(
        "UPDATE proteins_pdbs SET single_chain_pdb_file = ? WHERE uniprot_acc = ? AND pdb_id = ?",
        [(str(file.output_file), file.uniprot_acc, file.pdb_id) for file in files],
    )


def save_density_filtered(
    query: DensityFilterQuery,
    files: list[DensityFilterResult],
    uniprot_accessions: list[str],
    con: DuckDBPyConnection,
):
    result = con.execute(
        """INSERT OR IGNORE INTO density_filters
        (confidence, min_threshold, max_threshold)
        VALUES (?, ?, ?)
        RETURNING density_filter_id""",
        (query.confidence, query.min_threshold, query.max_threshold),
    ).fetchone()
    if result is None:
        # Already exists, so just fetch the id
        result = con.execute(
            """SELECT density_filter_id FROM density_filters
            WHERE confidence = ? AND min_threshold = ? AND max_threshold = ?""",
            (query.confidence, query.min_threshold, query.max_threshold),
        ).fetchone()
    if result is None or len(result) != 1:
        msg = "Failed to insert or retrieve density filter"
        raise ValueError(msg)
    density_filter_id = result[0]

    values = []
    for file, uniprot_accession in zip(files, uniprot_accessions, strict=False):
        values.append(
            (
                density_filter_id,
                uniprot_accession,
                file.count,
                file.density_filtered_file is not None,
                str(file.density_filtered_file) if file.density_filtered_file else None,
            )
        )
    con.executemany(
        """INSERT OR IGNORE INTO density_filtered_alphafolds
        (density_filter_id, uniprot_acc, nr_residues_above_confidence, keep, pdb_file)
        VALUES (?, ?, ?, ?, ?)""",
        values,
    )
