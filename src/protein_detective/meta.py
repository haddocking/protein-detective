"""Create a DuckDB database from the session directory, including all CSV files and the RO-Crate metadata."""
# Whenever changes occur in this file,
# the mermaid er diagram in docs/meta.ipynb should be updated to reflect the changes.

from pathlib import Path
from typing import Annotated

import duckdb
from cyclopts import Parameter, validators
from rocrate.metadata import BASENAME

from protein_detective.common_cli import rprint
from protein_detective.powerfit.workflow import powerfit_solutions_query

DDLStatement = tuple[str, dict[str, str | list[str]]]
"""SQL DDL statement and named parameters (use $ prefix in SQL) to be passed to DuckDB connection.execute()"""


def rocrate_as_duckdb_ddl(session_dir: Path) -> list[DDLStatement]:
    rocrate_path = session_dir / BASENAME
    params: dict[str, str | list[str]] = {"rocrate_path": str(rocrate_path)}
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


def refinement_run_io_paths(session_dir: Path, refine_run_id: str | None = None) -> list[Path]:
    """Find paths to refinement run IO mapping files.

    Args:
        session_dir: Session directory containing refinement runs.
        refine_run_id: Run to select; when omitted, include all runs.

    Returns:
        Matching per-run IO indexes, ordered by path; empty if no runs exist.

    Raises:
        ValueError: The requested refinement run has no IO index.
    """
    indexes = sorted((session_dir / "refine").glob("*/io.csv"))
    if refine_run_id is not None:
        indexes = [p for p in indexes if p.parent.name == refine_run_id]
        if not indexes:
            msg = f"Unknown refinement run ID: {refine_run_id}"
            raise ValueError(msg)
    return indexes


def refinements_io_as_duckdb_ddl(session_dir: Path, refine_run_id: str | None = None) -> list[DDLStatement]:
    """Build the statements that load refinement input/output mappings.

    Args:
        session_dir: Session directory containing refinement runs.
        refine_run_id: Run to select; when omitted, include all runs.

    Returns:
        SQL statements and bound parameters for creating refinements_io from
        matching run indexes; empty if no indexes exist.

    Raises:
        ValueError: The requested refinement run has no IO index.
    """
    indexes = refinement_run_io_paths(session_dir=session_dir, refine_run_id=refine_run_id)
    if not indexes:
        return []
    return [
        (
            """\
            CREATE TABLE refinements_io AS
            SELECT * FROM read_csv($indexes, all_varchar = true);
            """,
            {"indexes": [str(index) for index in indexes]},
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

    statements.extend(refinements_io_as_duckdb_ddl(session_dir))

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
    fittable_structures_csv = session_dir / "powerfit" / "fittable_structures.csv"
    solutions_pattern = session_dir / "powerfit" / "*" / "*" / "solutions.out"
    if powerfit_run_id:
        solutions_pattern = session_dir / "powerfit" / powerfit_run_id / "*" / "solutions.out"
    has_solutions = any(session_dir.glob(str(solutions_pattern.relative_to(session_dir))))
    if not fittable_structures_csv.exists() or not has_solutions:
        return []
    return [
        (
            "CREATE TABLE solutions AS\n"
            + powerfit_solutions_query("JOIN fittable_structures USING (structure)")
            + ";",
            {"solutions_pattern": str(solutions_pattern)},
        ),
    ]


def capri_as_duckdb_ddl(session_dir: Path) -> list[DDLStatement]:
    """Load final CAPRI results with session-relative refinement run keys.

    Read 7_caprieval only, excluding earlier stages and postprocessed copies
    under analysis/. Like solutions, the keys describe relationships without
    adding database foreign key constraints.
    """
    statements: list[DDLStatement] = []
    for table in ("capri_ss", "capri_clt"):
        pattern = Path("refine") / "*" / "*" / "*" / "*" / "7_caprieval" / f"{table}.tsv"
        files = sorted(str(path) for path in session_dir.glob(str(pattern)))
        if not files:
            continue
        statements.append(
            (
                f"""\
                CREATE TABLE refinements_{table} AS
                SELECT
                    replace(parse_dirpath(parse_dirpath(filename)), $session_dir || '/', '') AS refine_run_dir,
                    * EXCLUDE (filename)
                FROM read_csv(
                    $capri_pattern, delim = '\t', header = true, comment = '#',
                    nullstr = '-', filename = true, normalize_names = true, union_by_name = true
                );
                """,  # noqa: S608 -- table is one of the two hardcoded CAPRI table names.
                {"capri_pattern": files, "session_dir": str(session_dir)},
            )
        )
    return statements


def ddl(session_dir: Path, powerfit_run_id: str | None = None) -> list[DDLStatement]:
    statements: list[DDLStatement] = []
    statements.extend(structure_files_as_duckdb_ddl(session_dir))
    statements.extend(rocrate_as_duckdb_ddl(session_dir))
    statements.extend(stats_csv_as_duckdb_ddl(session_dir))
    statements.extend(solutions_as_duckdb_ddl(session_dir, powerfit_run_id=powerfit_run_id))
    statements.extend(capri_as_duckdb_ddl(session_dir))
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


def create_meta_duckdb(
    session_dir: Annotated[Path, Parameter(validator=validators.Path(file_okay=False, dir_okay=True, exists=True))],
    /,
    *,
    powerfit_run_id: str | None = None,
) -> None:
    """Generate a DuckDB metadata database for a Protein Detective session.

    Args:
        session_dir: Session directory containing the files to include.
        powerfit_run_id: Optional PowerFit run ID used to restrict solutions.
    """
    create_meta_duckdb_file(session_dir, powerfit_run_id=powerfit_run_id)
    duckdb_file = session_dir / "meta.duckdb"
    rprint(
        f"[green]{duckdb_file} has been generated.[/green]\n"
        "See https://www.bonvinlab.org/protein-detective/meta.html for example queries.\n"
        f"Use `duckdb --readonly {duckdb_file}` to query it.",
        soft_wrap=True,
    )
