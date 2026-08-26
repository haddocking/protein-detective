"""Create a DuckDB database from the session directory, including all CSV files and the RO-Crate metadata."""
# Whenever changes occur in this file,
# the mermaid er diagram in docs/meta.ipynb should be updated to reflect the changes.

from pathlib import Path

import duckdb
from rocrate.metadata import BASENAME

from protein_detective.powerfit.workflow import powerfit_solutions_query

DDLStatement = tuple[str, dict[str, str]]
"""SQL DDL statement and named parameters (use $ prefix in SQL) to be passed to DuckDB connection.execute()"""


def rocrate_as_duckdb_ddl(session_dir: Path) -> list[DDLStatement]:
    rocrate_path = session_dir / BASENAME
    params = {"rocrate_path": str(rocrate_path)}
    return [
        (
            """\
            CREATE TABLE rocrate_nodes AS
            SELECT "@id" AS id, "@type" AS type, * EXCLUDE("@id", "@type")
            FROM (
                SELECT unnest("@graph", max_depth:=2) FROM read_json($rocrate_path)
            );
            """,
            params,
        ),
        (
            """\
            CREATE TABLE rocrate_create_actions AS
            SELECT
                id,
                type,
                name,
                agent,
                endTime,
                instrument,
                object,
                result,
                startTime,
                substr(name, strpos(name, 'protein-detective ')) AS command
            FROM rocrate_nodes
            WHERE type = 'CreateAction';
            """,
            {},
        ),
        (
            """\
            CREATE TABLE rocrate_inodes AS
            SELECT id, type, description, name
            FROM rocrate_nodes
            WHERE type = 'File' OR type = 'Dataset';
            """,
            {},
        ),
        (
            """\
            CREATE TABLE rocrate_objects AS
            SELECT id AS action_id, json_extract_string(unnest(object), '@id') AS object_id
            FROM rocrate_create_actions;
            """,
            {},
        ),
        (
            """\
            CREATE TABLE rocrate_results AS
            SELECT id AS action_id, json_extract_string(unnest(result), '@id') AS result_id
            FROM rocrate_create_actions;
            """,
            {},
        ),
    ]


def _uniprot_stats_csv_as_duckdb_ddl(uniprot_txt: Path) -> list[DDLStatement]:
    return [
        (
            """\
            CREATE TABLE uniprot AS
            SELECT uniprot_accession
            FROM read_csv($uniprot_txt, header = false, columns={'uniprot_accession': 'VARCHAR'});
            """,
            {"uniprot_txt": str(uniprot_txt)},
        ),
    ]


def _alphafold_stats_csv_as_duckdb_ddl(alphafold_csv: Path) -> list[DDLStatement]:
    return [
        (
            """\
            CREATE TABLE alphafold AS
            SELECT * FROM read_csv($alphafold_csv);
            """,
            {"alphafold_csv": str(alphafold_csv)},
        )
    ]


def _pdbe_stats_csv_as_duckdb_ddl(pdbe_csv: Path) -> list[DDLStatement]:
    return [
        (
            """\
            CREATE TABLE pdbe AS
            SELECT * FROM read_csv($pdbe_csv);
            """,
            {"pdbe_csv": str(pdbe_csv)},
        )
    ]


def _uniprots_verified_stats_csv_as_duckdb_ddl(
    uniprots_verified_stats_csv: Path,
) -> list[DDLStatement]:
    return [
        (
            """\
            CREATE TABLE uniprots_verified_stats AS
            SELECT *
            FROM read_csv($uniprots_verified_stats_csv);
            """,
            {"uniprots_verified_stats_csv": str(uniprots_verified_stats_csv)},
        ),
    ]


def _merge_structure_files_csv_as_duckdb_ddl(
    merge_structure_files_csv: Path,
) -> list[DDLStatement]:
    return [
        (
            """\
            CREATE TABLE merge_structure_files AS
            SELECT *
            FROM read_csv($merge_structure_files_csv);
            """,
            {"merge_structure_files_csv": str(merge_structure_files_csv)},
        ),
    ]


def _combined_stats_csv_as_duckdb_ddl(combined_stats_csv: Path) -> list[DDLStatement]:
    return [
        (
            """\
            CREATE TABLE combined_stats AS
            SELECT *
            FROM read_csv($combined_stats_csv);
            """,
            {"combined_stats_csv": str(combined_stats_csv)},
        ),
    ]


def _secondary_structure_stats_csv_as_duckdb_ddl(
    secondary_structure_stats_csv: Path,
) -> list[DDLStatement]:
    return [
        (
            """\
            CREATE TABLE secondary_structure_stats AS
            SELECT * FROM read_csv($secondary_structure_stats_csv);
            """,
            {"secondary_structure_stats_csv": str(secondary_structure_stats_csv)},
        )
    ]


def _fittable_structures_csv_as_duckdb_ddl(fittable_structures_csv: Path) -> list[DDLStatement]:
    return [
        (
            """\
            CREATE TABLE fittable_structures AS
            SELECT *
            FROM read_csv($fittable_structures_csv);
            """,
            {"fittable_structures_csv": str(fittable_structures_csv)},
        ),
    ]


def _fitted_models_csv_as_duckdb_ddl(fitted_models_csv: Path) -> list[DDLStatement]:
    return [
        (
            """\
            CREATE TABLE fitted_models AS
            SELECT *
            FROM read_csv($fitted_models_csv);
            """,
            {"fitted_models_csv": str(fitted_models_csv)},
        ),
    ]


def _pdbe_retrieve_stats_csv_as_duckdb_ddl(pdbe_retrieve_stats_csv: Path) -> list[DDLStatement]:
    return [
        (
            """\
            CREATE TABLE pdbe_retrieve_stats AS
            SELECT *
            FROM read_csv($pdbe_retrieve_stats_csv);
            """,
            {"pdbe_retrieve_stats_csv": str(pdbe_retrieve_stats_csv)},
        ),
    ]


def _alphafold_retrieve_stats_csv_as_duckdb_ddl(
    alphafold_retrieve_stats_csv: Path,
) -> list[DDLStatement]:
    return [
        (
            """\
            CREATE TABLE alphafold_retrieve_stats AS
            SELECT *
            FROM read_csv($alphafold_retrieve_stats_csv);
            """,
            {"alphafold_retrieve_stats_csv": str(alphafold_retrieve_stats_csv)},
        ),
    ]


def _search_csv_as_duckdb_ddl(session_dir: Path) -> list[DDLStatement]:
    statements: list[DDLStatement] = []
    uniprot_txt = session_dir / "uniprot.txt"
    has_uniprot = uniprot_txt.exists()
    if has_uniprot:
        statements.extend(_uniprot_stats_csv_as_duckdb_ddl(uniprot_txt))

    alphafold_csv = session_dir / "alphafold.csv"
    if alphafold_csv.exists():
        statements.extend(_alphafold_stats_csv_as_duckdb_ddl(alphafold_csv))

    pdbe_csv = session_dir / "pdbe.csv"
    if pdbe_csv.exists():
        statements.extend(_pdbe_stats_csv_as_duckdb_ddl(pdbe_csv))

    return statements


def _retrieve_csv_as_duckdb_ddl(session_dir: Path) -> list[DDLStatement]:
    statements: list[DDLStatement] = []

    pdbe_retrieve_stats_csv = session_dir / "pdbe_stats.csv"
    if pdbe_retrieve_stats_csv.exists():
        statements.extend(_pdbe_retrieve_stats_csv_as_duckdb_ddl(pdbe_retrieve_stats_csv))

    alphafold_retrieve_stats_csv = session_dir / "alphafold_stats.csv"
    if alphafold_retrieve_stats_csv.exists():
        statements.extend(_alphafold_retrieve_stats_csv_as_duckdb_ddl(alphafold_retrieve_stats_csv))

    return statements


def _filter_csv_as_duckdb_ddl(session_dir: Path) -> list[DDLStatement]:
    statements: list[DDLStatement] = []

    uniprots_verified_stats_csv = session_dir / "uniprots_verified_stats.csv"
    if uniprots_verified_stats_csv.exists():
        statements.extend(_uniprots_verified_stats_csv_as_duckdb_ddl(uniprots_verified_stats_csv))

    combined_stats_csv = session_dir / "combined_stats.csv"
    if combined_stats_csv.exists():
        statements.extend(_combined_stats_csv_as_duckdb_ddl(combined_stats_csv))

    secondary_structure_stats_csv = session_dir / "secondary_structure_stats.csv"
    if secondary_structure_stats_csv.exists():
        statements.extend(_secondary_structure_stats_csv_as_duckdb_ddl(secondary_structure_stats_csv))

    return statements


def stats_csv_as_duckdb_ddl(session_dir: Path) -> list[DDLStatement]:
    statements: list[DDLStatement] = []
    statements.extend(_search_csv_as_duckdb_ddl(session_dir))

    merge_structure_files_csv = session_dir / "merge_structure_files.csv"
    if merge_structure_files_csv.exists():
        statements.extend(_merge_structure_files_csv_as_duckdb_ddl(merge_structure_files_csv))

    statements.extend(_retrieve_csv_as_duckdb_ddl(session_dir))
    statements.extend(_filter_csv_as_duckdb_ddl(session_dir))

    fittable_structures_csv = session_dir / "powerfit" / "fittable_structures.csv"
    if fittable_structures_csv.exists():
        statements.extend(_fittable_structures_csv_as_duckdb_ddl(fittable_structures_csv))

    fitted_models_csv = session_dir / "powerfit" / "fitted_models.csv"
    if fitted_models_csv.exists():
        statements.extend(_fitted_models_csv_as_duckdb_ddl(fitted_models_csv))

    return statements


def structure_files_as_duckdb_ddl(session_dir: Path) -> list[DDLStatement]:
    cif_pattern = session_dir / "**" / "*.cif.gz"
    pdb_pattern = session_dir / "**" / "*.pdb"
    return [
        (
            """\
            CREATE TABLE structure_files AS
            SELECT file, parse_dirpath(file) AS parent_dir, parse_filename(file) AS filename FROM (
                -- TODO replace only works on unixy systems
                SELECT replace(file, $session_dir || '/', '') AS file FROM glob($cif_pattern)
                UNION ALL
                SELECT replace(file, $session_dir || '/', '') AS file FROM glob($pdb_pattern)
            );
            """,
            {
                "session_dir": str(session_dir),
                "cif_pattern": str(cif_pattern),
                "pdb_pattern": str(pdb_pattern),
            },
        ),
    ]


def solutions_as_duckdb_ddl(session_dir: Path, powerfit_run_id: str | None = None) -> list[DDLStatement]:
    solutions_pattern = session_dir / "powerfit" / "*" / "*" / "solutions.out"
    if powerfit_run_id:
        solutions_pattern = session_dir / "powerfit" / powerfit_run_id / "*" / "solutions.out"
    return [
        (
            "CREATE TABLE solutions AS\n"
            + powerfit_solutions_query("JOIN fittable_structures USING (structure)")
            + ";",
            {"solutions_pattern": str(solutions_pattern)},
        ),
    ]


def ddl(session_dir: Path, powerfit_run_id: str | None = None) -> list[DDLStatement]:
    statements: list[DDLStatement] = []
    statements.extend(structure_files_as_duckdb_ddl(session_dir))
    statements.extend(rocrate_as_duckdb_ddl(session_dir))
    statements.extend(stats_csv_as_duckdb_ddl(session_dir))
    statements.extend(solutions_as_duckdb_ddl(session_dir, powerfit_run_id=powerfit_run_id))
    return statements


def _execute_ddl_statements(con: duckdb.DuckDBPyConnection, statements: list[DDLStatement]) -> None:
    for statement, params in statements:
        con.execute(statement, params)


def in_memory_duckdb_connection(session_dir: Path, powerfit_run_id: str | None = None):
    statements = ddl(session_dir, powerfit_run_id=powerfit_run_id)
    con = duckdb.connect(database=":memory:")
    _execute_ddl_statements(con, statements)
    return con


def create_meta_duckdb_file(session_dir: Path, duckdb_file: Path | None = None, powerfit_run_id: str | None = None):
    statements = ddl(session_dir, powerfit_run_id=powerfit_run_id)
    if duckdb_file is None:
        duckdb_file = session_dir / "meta.duckdb"
    con = duckdb.connect(database=str(duckdb_file))
    _execute_ddl_statements(con, statements)
    con.close()
