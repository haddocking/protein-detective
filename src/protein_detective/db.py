"""Module for managing the DuckDB database used for storing metadata for session."""

import logging
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from importlib.resources import read_text
from pathlib import Path

from cattrs import unstructure
from cattrs.preconf.json import make_converter
from duckdb import ConstraintException, DuckDBPyConnection, InvalidInputException
from duckdb import connect as duckdb_connect
from pandas import DataFrame

from protein_detective.alphafold import AlphaFoldEntry
from protein_detective.alphafold.density import DensityFilterQuery, DensityFilterResult
from protein_detective.alphafold.entry_summary import EntrySummary
from protein_detective.pdbe.io import ProteinPdbRow, SingleChainQuery, SingleChainResult
from protein_detective.powerfit.options import PowerfitOptions
from protein_detective.uniprot import PdbResult, Query

logger = logging.getLogger(__name__)
converter = make_converter()


ddl: str = read_text("protein_detective", "ddl.sql")
"""The DDL statements to create the database schema to hold session metadata.

Paths to files in the database are stored relative to the session directory.
So you can move the session directory around without breaking the paths.

Just after connection to the database, you need to set the session_dir as DuckDB variable
with `con.execute("SET VARIABLE session_dir = ?", (str(session_dir),))`.
This is done for you if you use [connect()][protein_detective.db.connect] function.

For example with cwd ~/ and session_dir "session1" and
file "~/session1/foo.pdb" then return to consumer as
"session1/foo.pdb", but stored in the database as "foo.pdb"

Some tables are prefixed with `raw_` to store file paths relative to the session directory.
The views (table name without `raw_`) then prepend the session directory
(using the DuckDB `session_dir` variable) to the paths,
so the paths are pointing to the correct files.
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

    # read_csv in solutions table requires at least one solutions.out file to exist
    # so we create an header only solutions.out file so pattern always matches
    solution_header_file = session_dir / "powerfit" / "0" / "dummy" / "solutions.out"
    if not solution_header_file.exists():
        solution_header_file.parent.mkdir(parents=True, exist_ok=True)
        solutions_header = "rank,cc,Fish-z,rel-z,x,y,z,a11,a12,a13,a21,a22,a23,a31,a32,a33\n"
        solution_header_file.write_text(solutions_header)

    con.execute(ddl)


@contextmanager
def connect(session_dir: Path, read_only: bool = False) -> Iterator[DuckDBPyConnection]:
    """Context manager to connect to the DuckDB database holding session metadata.

    Examples:
        To query in read only mode.

        ```python
        session_dir = Path("path/to/session")
        with connect(session_dir, read_only=True) as con:
            result = con.execute("SELECT * FROM proteins").fetchall()
        ```

    Args:
        session_dir: The directory where the session data is stored.
        read_only: If True, the connection will be read-only.
            If read only then database can be read by multiple processes.
            If not read only then database can be read and written to by a single process.

    Yields:
        DuckDBPyConnection: The connection to the DuckDB database.
    """
    # wrapper around duckdb.connect to create tables on connect
    database = db_path(session_dir)
    con = duckdb_connect(database, read_only=read_only)
    try:
        initialize_db(session_dir, con)
    except InvalidInputException as e:
        if "read-only mode" in str(e):
            logger.info("Database is in read-only mode, skipping initialization.")
        else:
            raise
    yield con
    con.close()


def save_query(query: Query, con: DuckDBPyConnection):
    """Save a UniProt search query to the database.

    Args:
        query: The UniProt search query to save.
        con: The DuckDB connection to use for saving the data.
    """
    con.execute("INSERT INTO uniprot_searches (query) VALUES (?)", (unstructure(query),))


def save_uniprot_accessions(uniprot_accessions: Iterable[str], con: DuckDBPyConnection):
    """Save UniProt accessions to the database.

    Args:
        uniprot_accessions: An iterable of UniProt accessions to save.
        con: The DuckDB connection to use for saving the data.
    """
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
    """Save PDB entries and their associations with UniProt accessions to the database.

    Args:
        uniprot2pdbs: A mapping of UniProt accessions to their associated PDB.
        con: The DuckDB connection to use for saving the data.
    """
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
    """Load PDB entries from the database.

    Args:
        con: The DuckDB connection to use for fetching the data.

    Returns:
        A list of protein pdb rows.
    """
    query = """
    SELECT
        uniprot_acc,
        pdb_id,
        if(length(mmcif_file), concat_ws('/', getvariable('session_dir'), mmcif_file), NULL) AS mmcif_file,
        uniprot_chains
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
    """Save AlphaFold entries to the database.

    Args:
        afs: A dictionary mapping UniProt accessions to sets of AlphaFold IDs.
        con: The DuckDB connection to use for saving the data.

    """
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
    """Save AlphaFold files to the database.

    Args:
        afs: A list of AlphaFold entries.
        con: The DuckDB connection to use for saving the data.

    """
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
    """Load AlphaFold IDs from the database.

    Args:
        con: The DuckDB connection to use for fetching the data.

    Returns:
        A set of AlphaFold IDs (UniProt accessions).
    """
    query = """
    SELECT uniprot_acc
    FROM alphafolds
    """
    rows = con.execute(query).fetchall()
    return {row[0] for row in rows}


def load_alphafolds(con: DuckDBPyConnection) -> list[AlphaFoldEntry]:
    """Load AlphaFold entries from the database.
    Args:
        con: The DuckDB connection to use for fetching the data.

    Returns:
        A list of AlphaFold entries.

    """
    query = """
    SELECT
        uniprot_acc,
        summary,
        if(length(bcif_file), concat_ws('/', getvariable('session_dir'), bcif_file), NULL) AS bcif_file,
        if(length(cif_file), concat_ws('/', getvariable('session_dir'), cif_file), NULL) AS cif_file,
        if(length(pdb_file), concat_ws('/', getvariable('session_dir'), pdb_file), NULL) AS pdb_file,
        if(length(pae_image_file), concat_ws('/', getvariable('session_dir'), pae_image_file), NULL) AS pae_image_file,
        if(length(pae_doc_file), concat_ws('/', getvariable('session_dir'), pae_doc_file), NULL) AS pae_doc_file,
        if(
            length(am_annotations_file),
            concat_ws('/', getvariable('session_dir'), am_annotations_file),
            NULL
        ) AS am_annotations_file,
        if(
            length(am_annotations_hg19_file),
            concat_ws('/', getvariable('session_dir'), am_annotations_hg19_file),
            NULL
        ) AS am_annotations_hg19_file,
        if(
            length(am_annotations_hg38_file),
            concat_ws('/', getvariable('session_dir'), am_annotations_hg38_file),
            NULL
        ) AS am_annotations_hg38_file
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


def save_filter(filter_options: dict, con: DuckDBPyConnection) -> int:
    result = con.execute(
        """
        INSERT OR IGNORE INTO filters (filter_options) VALUES (?) RETURNING filter_id
                         """,
        (filter_options,),
    ).fetchone()
    if result is None:
        # Already exists, so just fetch the id
        result = con.execute(
            """
            SELECT filter_id FROM filters WHERE filter_options = ?
            """,
            (filter_options,),
        ).fetchone()
    if result is None or len(result) != 1:
        msg = "Failed to insert or retrieve filter"
        raise ValueError(msg)
    return result[0]


def save_single_chain_pdb_files(files: list[SingleChainResult], query: SingleChainQuery, con: DuckDBPyConnection):
    """Save single chain PDB files to the database.

    Args:
        files: A list of objects containing the PDB file paths and metadata.
        query: The single chain query parameters.
        con: The DuckDB connection to use for saving the data.

    """
    filter_options = unstructure(query)
    filter_id = save_filter(filter_options, con)

    if len(files) == 0:
        return
    rows = []
    for file in files:
        output_file = None
        if file.passed:
            output_file = str(file.output_file)
        rows.append(
            (filter_id, file.uniprot_acc, file.pdb_id, {"nr_residues": file.nr_residues}, file.passed, output_file)
        )
    con.executemany(
        """INSERT OR IGNORE INTO filtered_pdbs
        (filter_id, uniprot_acc, pdb_id, filter_stats, passed, output_file)
        VALUES (?, ?, ?, ?, ?, ?)""",
        rows,
    )


def load_single_chain_pdb_files(con: DuckDBPyConnection) -> list[Path]:
    """Load single chain PDB files from the database.

    Args:
        con: The DuckDB connection to use for fetching the data.

    Returns:
        A list of paths to the single chain PDB files.
    """
    # TODO do not ignore filter_id column
    query = """
    SELECT
        concat_ws('/', getvariable('session_dir'), output_file),
    FROM filtered_pdbs
    WHERE output_file IS NOT NULL
    """
    rows = con.execute(query).fetchall()
    return [Path(row[0]) for row in rows]


def save_density_filtered(
    query: DensityFilterQuery,
    files: list[DensityFilterResult],
    uniprot_accessions: list[str],
    con: DuckDBPyConnection,
):
    """Save density filtered AlphaFold results to the database.

    Args:
        query: The density filter query parameters.
        files: A list of the results.
        uniprot_accessions: A list of UniProt accessions corresponding to the results.
        con: The DuckDB connection to use for saving the data.

    Raises:
        ValueError: If the density filter could not be inserted or retrieved.
    """
    filter_options = unstructure(query)
    filter_id = save_filter(filter_options, con)

    values = []
    for file, uniprot_accession in zip(files, uniprot_accessions, strict=False):
        values.append(
            (
                filter_id,
                uniprot_accession,
                file.count,
                file.density_filtered_file is not None,
                str(file.density_filtered_file) if file.density_filtered_file else None,
            )
        )
    con.executemany(
        """INSERT OR IGNORE INTO density_filtered_alphafolds
        (filter_id, uniprot_acc, filter_stats, keep, pdb_file)
        VALUES (?, ?, ?, ?, ?)""",
        values,
    )


def load_density_filtered_alphafolds_files(
    con: DuckDBPyConnection,
) -> list[Path]:
    """Load density filtered AlphaFold PDB files from the database.

    Args:
        con: The DuckDB connection to use for fetching the data.

    Returns:
        A list of paths to the density filtered AlphaFold PDB files.
    """
    query = """
    SELECT
        concat_ws('/', getvariable('session_dir'), pdb_file) AS pdb_file
    FROM density_filtered_alphafolds
    WHERE keep = TRUE AND pdb_file IS NOT NULL
    """
    rows = con.execute(query).fetchall()
    return [Path(row[0]) for row in rows]


def save_powerfit_options(options: PowerfitOptions, con: DuckDBPyConnection) -> int:
    """Save PowerFit options of a powerfit run to the database.

    Args:
        options: The PowerFit options to save.
        con: The DuckDB connection to use for saving the data.

    Returns:
        The ID of the PowerFit run created or reused.

    Raises:
        ValueError: If the options could not be saved or retrieved.
    """
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
            - filter_id: The ID of the filter applied to the structure, if stucture came from AlphaFold.
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


def save_fitted_models(df: DataFrame, con: DuckDBPyConnection):  # noqa: ARG001
    """Save fitted model PDB files to the database.

    Args:
        df: A DataFrame containing the fitted model data with columns:
            - powerfit_run_id: The ID of the PowerFit run.
            - structure: The structure identifier.
            - rank: The rank of the solution.
            - unfitted_model_file: The path to the original model PDB file.
            - fitted_model_file: The path to the fitted model PDB file.
        con: The DuckDB connection to use for saving the data.
    """
    con.execute("INSERT OR IGNORE INTO raw_fitted_models BY NAME SELECT * FROM df")


def load_fitted_models(con: DuckDBPyConnection) -> DataFrame:
    """Load fitted model PDB files from the database.

    Args:
        con: The DuckDB connection to use for fetching the data.

    Returns:
        A DataFrame containing the fitted model PDB file with columns:

            - unfitted_model_file: The path to the original model PDB file.
            - fitted_model_file: The path to the fitted model PDB file.

            and all columns returned by [powerfit_solutions][protein_detective.db.powerfit_solutions]
            with `pdb_file` renamed to `unfitted_model_file` column..
    """
    con.execute("""
        SELECT
            f.* EXCLUDE (unfitted_model_file),
            coalesce(f.unfitted_model_file, s.pdb_file) AS unfitted_model_file,
            s.* EXCLUDE (powerfit_run_id, structure, rank, pdb_file),
        FROM fitted_models AS f
        JOIN solutions AS s USING (powerfit_run_id, structure, rank)
    """)

    return con.df()


def list_lcc_files(con: DuckDBPyConnection) -> list[tuple[int, str, str]]:
    """List Local Cross Validation files (lcc.mrc).

    Args:
        con: The DuckDB connection to use for fetching the data.

    Returns:
        A list of tuples containing the PowerFit run ID, structure, and path to the lcc.mrc file.
    """
    con.execute("""
        SELECT
            parse_path(file)[-3]::integer AS powerfit_run_id,
            parse_path(file)[-2] AS structure,
            file as lcc_file,
        FROM
            -- <session_dir>/powerfit/10/AF-A8MT65-F1-model_v4/lcc.mrc
            glob(concat_ws('/', getvariable('session_dir'), 'powerfit/*/*/lcc.mrc'))

    """)
    return con.fetchall()
