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
    -- TODO dont use optional pdb_file, but use a pdb_files table, this makes using the rows less iffy
    pdb_file TEXT,
);

-- pdb could have multiple proteins so use many-to-many table
CREATE TABLE IF NOT EXISTS proteins_pdbs (
    uniprot_acc TEXT NOT NULL,
    pdb_id TEXT NOT NULL,
    uniprot_chains TEXT NOT NULL,
    single_chain_pdb_file TEXT,
    FOREIGN KEY (uniprot_acc) REFERENCES proteins (uniprot_acc),
    FOREIGN KEY (pdb_id) REFERENCES pdbs (pdb_id),
    PRIMARY KEY (uniprot_acc, pdb_id)
);

CREATE TABLE IF NOT EXISTS alphafolds (
    uniprot_acc TEXT PRIMARY KEY,
    summary JSON,
    bcif_file TEXT,
    cif_file TEXT,
    pdb_file TEXT,
    pae_image_file TEXT,
    pae_doc_file TEXT,
    am_annotations_file TEXT,
    am_annotations_hg19_file TEXT,
    am_annotations_hg38_file TEXT,
    FOREIGN KEY (uniprot_acc) REFERENCES proteins (uniprot_acc)
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
    """Return the path to the DuckDB database file in the given session directory.

    Args:
        session_dir: The directory where the session data is stored.

    Returns:
        Path to the DuckDB database file.
    """
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
    con: DuckDBPyConnection,
):
    save_uniprot_accessions(uniprot2pdbs.keys(), con)
    pdb_rows = []
    for pdb_results in uniprot2pdbs.values():
        pdb_rows.extend([(pdb.id, pdb.method, pdb.resolution) for pdb in pdb_results])
    if len(pdb_rows) > 0:
        con.executemany(
            "INSERT OR IGNORE INTO pdbs (pdb_id, method, resolution) VALUES (?, ?, ?)",
            pdb_rows,
        )
    prot2pdb_rows = []
    for uniprot_acc, pdb_results in uniprot2pdbs.items():
        prot2pdb_rows.extend([(uniprot_acc, pdb.id, pdb.uniprot_chains) for pdb in pdb_results])
    if len(prot2pdb_rows) == 0:
        return
    con.executemany(
        "INSERT OR IGNORE INTO proteins_pdbs (uniprot_acc, pdb_id, uniprot_chains) VALUES (?, ?, ?)",
        prot2pdb_rows,
    )


def save_pdb_files(pdb_files: Mapping[str, Path], con: DuckDBPyConnection):
    """Save PDB files to the database.

    Args:
        pdb_files: A mapping of PDB IDs to their file paths.
        con: The DuckDB connection to use for saving the data.
    """
    rows = [(str(pdb_file), pdb_id) for pdb_id, pdb_file in pdb_files.items()]
    if len(rows) == 0:
        return
    con.executemany(
        "UPDATE pdbs SET pdb_file = ? WHERE pdb_id = ?",
        rows,
    )


def load_pdb_ids(con: DuckDBPyConnection) -> set[str]:
    """Load PDB IDs from the database.

    Args:
        con: The DuckDB connection to use for fetching the data.

    Returns:
        A set of PDB IDs.
    """
    query = "SELECT pdb_id FROM pdbs"
    rows = con.execute(query).fetchall()
    return {row[0] for row in rows}


def load_pdbs(con: DuckDBPyConnection) -> list[ProteinPdbRow]:
    query = """
    SELECT uniprot_acc, pdb_id, pdb_file, uniprot_chains
    FROM proteins_pdbs AS pp
    JOIN pdbs AS p USING (pdb_id)
    """
    rows = con.execute(query).fetchall()
    return [
        ProteinPdbRow(
            uniprot_acc=row[0],
            id=row[1],
            pdb_file=Path(row[2]) if row[2] else None,
            uniprot_chains=row[3],
        )
        for row in rows
    ]


def save_alphafolds(afs: dict[str, set[str]], con: DuckDBPyConnection):
    rows = []
    for af_ids_of_uniprot in afs.values():
        rows.extend([(af_id,) for af_id in af_ids_of_uniprot])
    if len(rows) == 0:
        return
    con.executemany(
        "INSERT OR IGNORE INTO alphafolds (uniprot_acc) VALUES (?)",
        rows,
    )

    save_uniprot_accessions(afs.keys(), con)


def save_alphafolds_files(afs: list[AlphaFoldEntry], con: DuckDBPyConnection):
    rows = [
        (
            converter.dumps(af.summary, EntrySummary),
            str(af.bcif_file) if af.bcif_file else None,
            str(af.cif_file) if af.cif_file else None,
            str(af.pdb_file) if af.pdb_file else None,
            str(af.pae_image_file) if af.pae_image_file else None,
            str(af.pae_doc_file) if af.pae_doc_file else None,
            str(af.am_annotations_file) if af.am_annotations_file else None,
            str(af.am_annotations_hg19_file) if af.am_annotations_hg19_file else None,
            str(af.am_annotations_hg38_file) if af.am_annotations_hg38_file else None,
            af.uniprot_acc,
        )
        for af in afs
    ]
    if len(rows) == 0:
        # executemany can not be called with an empty list, it raises error, so we return early
        return
    con.executemany(
        """UPDATE alphafolds SET
            summary = ?,
            bcif_file = ?,
            cif_file = ?,
            pdb_file = ?,
            pae_image_file = ?,
            pae_doc_file = ?,
            am_annotations_file = ?,
            am_annotations_hg19_file = ?,
            am_annotations_hg38_file = ?
        WHERE uniprot_acc = ?
        """,
        rows,
    )


def load_alphafold_ids(con: DuckDBPyConnection) -> set[str]:
    query = """
    SELECT uniprot_acc
    FROM alphafolds
    """
    rows = con.execute(query).fetchall()
    return {row[0] for row in rows}


def load_alphafolds(con: DuckDBPyConnection) -> list[AlphaFoldEntry]:
    query = """
    SELECT 
    uniprot_acc, 
    summary, 
    bcif_file,
    cif_file,
    pdb_file,
    pae_image_file,
    pae_doc_file,
    am_annotations_file,
    am_annotations_hg19_file,
    am_annotations_hg38_file
    FROM alphafolds
    """
    rows = con.execute(query).fetchall()
    return [
        AlphaFoldEntry(
            uniprot_acc=row[0],
            summary=converter.loads(row[1], EntrySummary) if row[0] else None,
            bcif_file=Path(row[2]) if row[2] else None,
            cif_file=Path(row[3]) if row[3] else None,
            pdb_file=Path(row[4]) if row[4] else None,
            pae_image_file=Path(row[5]) if row[5] else None,
            pae_doc_file=Path(row[6]) if row[6] else None,
            am_annotations_file=Path(row[7]) if row[7] else None,
            am_annotations_hg19_file=Path(row[8]) if row[8] else None,
            am_annotations_hg38_file=Path(row[9]) if row[9] else None,
        )
        for row in rows
    ]


def save_single_chain_pdb_files(files: list[SingleChainResult], con: DuckDBPyConnection):
    if len(files) == 0:
        return
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
