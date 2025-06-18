import logging
from collections.abc import Iterable, Mapping
from contextlib import contextmanager
from pathlib import Path

from cattrs import unstructure
from cattrs.preconf.json import make_converter
from duckdb import ConstraintException, DuckDBPyConnection
from duckdb import connect as duckdb_connect
from pandas import DataFrame

from protein_detective.alphafold import AlphaFoldEntry
from protein_detective.alphafold.density import DensityFilterQuery, DensityFilterResult
from protein_detective.alphafold.entry_summary import EntrySummary
from protein_detective.pdbe.io import ProteinPdbRow, SingleChainResult
from protein_detective.powerfit.options import PowerfitOptions
from protein_detective.uniprot import PdbResult, Query

logger = logging.getLogger(__name__)
converter = make_converter()

# TODO make all file paths be relative to current session directory
# By using raw_ table to store paths relative to session directory
# and then a view which prepends the session directory to the paths
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
    mmcif_file TEXT,
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

CREATE SEQUENCE IF NOT EXISTS id_powerfit_runs START 1;
CREATE TABLE IF NOT EXISTS powerfit_runs (
    powerfit_run_id INTEGER DEFAULT nextval('id_powerfit_runs') PRIMARY KEY,
    options JSON NOT NULL,
    UNIQUE (options)
);

CREATE TABLE IF NOT EXISTS raw_solutions AS
SELECT
    parse_path(filename)[-3] AS powerfit_run_id,
    parse_path(filename)[-2] AS structure,
    rank, cc, fishz, relz,
    [x,y,z]::FLOAT[3] AS translation,
    [a11, a12, a13, a21, a22, a23, a31, a32, a33]::FLOAT[9] AS rotation,
FROM
    read_csv(getvariable('session_dir') || '/powerfit/*/*/solutions.out', filename=True, normalize_names=True)
;

CREATE VIEW IF NOT EXISTS solutions AS
SELECT
    powerfit_run_id,
    structure,
    rank,
    cc,
    fishz,
    relz,
    translation,
    rotation,
    density_filter_id,
    af_id,
    pdb_id,
    getvariable('session_dir') || '/' || COALESCE(pdb_file, single_chain_pdb_file) AS pdb_file,
    COALESCE(uniprot_acc, af_id) AS uniprot_acc,
FROM raw_solutions
LEFT JOIN (
    SELECT density_filter_id, uniprot_acc AS af_id, pdb_file, parse_filename(pdb_file, true) AS structure
    FROM density_filtered_alphafolds WHERE keep=True
) AS a USING (structure)
LEFT JOIN (
    SELECT uniprot_acc, pdb_id, single_chain_pdb_file, parse_filename(single_chain_pdb_file, true) AS structure
    FROM proteins_pdbs
    WHERE single_chain_pdb_file IS NOT NULL
) AS p USING (structure)
ORDER BY cc DESC;

CREATE TABLE IF NOT EXISTS raw_fitted_pdbs (
    powerfit_run_id INTEGER NOT NULL,
    structure TEXT NOT NULL,
    rank INTEGER NOT NULL,
    -- pdb_file is either foreign key of density_filtered_alphafolds.pdb_file or proteins_pdbs.single_chain_pdb_file
    pdb_file TEXT NOT NULL,
    fitted_file TEXT PRIMARY KEY,
);

CREATE VIEW IF NOT EXISTS fitted_pdbs AS
SELECT
    powerfit_run_id,
    structure,
    rank,
    concat_ws(
        '/',
        getvariable('session_dir'),
        pdb_file
    ) AS pdb_file,
    concat_ws(
        '/',
        getvariable('session_dir'),
        fitted_file
    ) AS fitted_file
FROM raw_fitted_pdbs;
"""


def db_path(session_dir: Path) -> Path:
    """Return the path to the DuckDB database file in the given session directory.

    Args:
        session_dir: The directory where the session data is stored.

    Returns:
        Path to the DuckDB database file.
    """
    return session_dir / "session.db"


def initialize_db(session_dir: Path, con: DuckDBPyConnection):
    """Initialize the DuckDB database by creating the necessary tables and variables.

    Args:
        session_dir: The directory where the session data is stored.
        con: The DuckDB connection to use for executing the DDL statements.
    """
    con.execute("SET VARIABLE session_dir = ?", (str(session_dir),))
    con.execute(ddl)


@contextmanager
def connect(session_dir: Path):
    # wrapper around duckdb.connect to create tables on connect
    database = db_path(session_dir)
    con = duckdb_connect(database)
    initialize_db(session_dir, con)
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


def save_pdb_files(mmcif_files: Mapping[str, Path], con: DuckDBPyConnection):
    """Save PDB files to the database.

    Args:
        mmcif_files: A mapping of PDB IDs to their file paths.
        con: The DuckDB connection to use for saving the data.
    """
    rows = [(str(mmcif_file), pdb_id) for pdb_id, mmcif_file in mmcif_files.items()]
    if len(rows) == 0:
        return
    con.executemany(
        "UPDATE pdbs SET mmcif_file = ? WHERE pdb_id = ?",
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
    SELECT uniprot_acc, pdb_id, mmcif_file, uniprot_chains
    FROM proteins_pdbs AS pp
    JOIN pdbs AS p USING (pdb_id)
    """
    rows = con.execute(query).fetchall()
    return [
        ProteinPdbRow(
            uniprot_acc=row[0],
            id=row[1],
            mmcif_file=Path(row[2]) if row[2] else None,
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


def load_single_chain_pdb_files(con: DuckDBPyConnection) -> list[Path]:
    query = """
    SELECT single_chain_pdb_file
    FROM proteins_pdbs
    WHERE single_chain_pdb_file IS NOT NULL
    """
    rows = con.execute(query).fetchall()
    return [Path(row[0]) for row in rows]


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


def load_density_filtered_alphafolds_files(
    con: DuckDBPyConnection,
) -> list[Path]:
    query = """
    SELECT pdb_file
    FROM density_filtered_alphafolds
    WHERE keep = TRUE
    """
    rows = con.execute(query).fetchall()
    return [Path(row[0]) for row in rows]


def save_powerfit_options(options: PowerfitOptions, con: DuckDBPyConnection) -> int:
    try:
        result = con.execute(
            """INSERT INTO powerfit_runs (options)
            VALUES (?) RETURNING powerfit_run_id""",
            (converter.dumps(options, PowerfitOptions),),
        ).fetchone()
        if result is None or len(result) != 1:
            msg = "Failed to insert powerfit options"
            raise ValueError(msg)
        return result[0]
    except ConstraintException as e:
        # If the options already exist, we can retrieve the existing run ID
        result = con.execute(
            """SELECT powerfit_run_id FROM powerfit_runs
            WHERE options = ?""",
            (converter.dumps(options, PowerfitOptions),),
        ).fetchone()
        if result is None or len(result) != 1:
            msg = "Failed to retrieve existing powerfit run ID"
            raise ValueError(msg) from e
        logger.info("Reusing existing powerfit run with ID %d", result[0])
        return result[0]


def load_powerfit_runs(con: DuckDBPyConnection) -> list[tuple[int, PowerfitOptions, Path]]:
    """Load all PowerFit runs from the database.

    Args:
        con: The DuckDB connection to use for fetching the data.

    Returns:
        A list of tuples containing the PowerFit run ID, options, and density map path.
    """
    con.execute(
        """
        SELECT
            powerfit_run_id,
            options,
            concat_ws(
                '/',
                getvariable('session_dir'),
                'powerfit',
                powerfit_run_id,
                parse_filename(json_extract_string(options, '$.target'))
            ) AS density_map,
        FROM powerfit_runs
    """
    )
    rows = con.fetchall()
    return [(row[0], converter.loads(row[1], PowerfitOptions), Path(row[2])) for row in rows]


def load_powerfit_run(
    powerfit_run_id: int,
    con: DuckDBPyConnection,
) -> tuple[PowerfitOptions, Path]:
    """Load a specific PowerFit run by its ID.

    Args:
        powerfit_run_id: The ID of the PowerFit run to load.
        con: The DuckDB connection to use for fetching the data.

    Returns:
        A tuple containing the PowerFit options and the path to the density map file.

    Raises:
        ValueError: If the PowerFit run with the specified ID does not exist.
    """
    all_runs = load_powerfit_runs(con)
    for run in all_runs:
        if run[0] == powerfit_run_id:
            return run[1], run[2]

    msg = f"PowerFit run with ID {powerfit_run_id} not found."
    raise ValueError(msg)


def powerfit_solutions(con: DuckDBPyConnection, powerfit_run_id: int | None = None) -> DataFrame:
    """Retrieve PowerFit solutions from the solutions.out files.

    Args:
        con: The DuckDB connection to use for fetching the data.
        powerfit_run_id: Optional ID of a specific PowerFit run to filter results. If None, all runs are included.

    Returns:
        A DataFrame containing the PowerFit solutions with columns:

            - powerfit_run_id: The ID of the PowerFit run.
            - structure: The structure identifier.
            - rank: The rank of the solution.
            - cc: The correlation coefficient of the solution.
            - fishz: The Fish-Z score of the solution.
            - relz: The relative Z-score of the solution.
            - translation: The translation vector applied to the structure.
            - rotation: The rotation matrix applied to the structure.
            - density_filter_id: The ID of the density filter applied to the structure, if stucture came from AlphaFold.
            - af_id: The AlphaFold ID associated with the structure, if structure came from AlphaFold.
            - pdb_id: The PDB ID of the structure, if structure came from PDBe.
            - pdb_file: The path to the PDB file of the structure used as input structre for powerfit run.
            - uniprot_acc: The UniProt accession number associated with the structure.
    """
    # TODO check that cc is the column to sort on, to get best first? Or Fish-z	rel-z
    # TODO rank is for each powerfit run, make clearer that this is per run/structure combination

    if powerfit_run_id is None:
        con.execute("FROM solutions")
    else:
        con.execute("FROM solutions WHERE powerfit_run_id = ?", (powerfit_run_id,))
    return con.df()


def save_fitted_pdbs(df: DataFrame, con: DuckDBPyConnection):  # noqa: ARG001
    con.execute("INSERT OR IGNORE INTO raw_fitted_pdbs BY NAME SELECT * FROM df")


def load_fitted_pdbs(con: DuckDBPyConnection) -> DataFrame:
    """Load fitted PDBs from the database.

    Returns:
        A DataFrame containing the fitted PDBs with columns:
            - powerfit_run_id: The ID of the PowerFit run.
            - pdb_file: The path to the original PDB file.
            - fitted_file: The path to the fitted PDB file.
    """
    con.execute("""
        SELECT
            f.* EXCLUDE (pdb_file),
            COALESCE(f.pdb_file, s.pdb_file) AS unfitted_pdb_file,
            s.* EXCLUDE (pdb_file),
        FROM fitted_pdbs AS f
        JOIN solutions AS s USING (powerfit_run_id, structure,rank)
    """)
    return con.df()


# TODO add function to return Local Cross Validation files aka powerfit/10/AF-A8MT65-F1-model_v4/lcc.mrc
