"""Create a DuckDB database from the session directory, including all CSV files and the RO-Crate metadata."""
# Whenever changes occur in this file,
# the mermaid er diagram in docs/meta.ipynb should be updated to reflect the changes.

from pathlib import Path
from typing import Annotated

import duckdb
from cyclopts import Parameter, validators
from rocrate.metadata import BASENAME

from protein_detective.common_cli import rprint
from protein_detective.powerfit.provenance import powerfit_run_arguments_from_rocrate
from protein_detective.powerfit.workflow import powerfit_solutions_query
from protein_detective.refine import LAST_CAPRIEVAL_MODULE
from protein_detective.refine.provenance import refine_run_arguments_from_rocrate

type DDLParameters = dict[str, str | list[str] | None]
"""Named DuckDB parameters; None binds as SQL NULL."""

DDLStatement = tuple[str, DDLParameters]
"""SQL DDL statement and named parameters (use $ prefix in SQL) to be passed to DuckDB connection.execute()"""


# Temporary macros keep each generated statement executable on a fresh connection
# without persisting session-specific helpers in the metadata database.
_PATH_MACROS = """\
CREATE OR REPLACE TEMP MACRO session_relative_path(path, session_root) AS
    substring(path, length(session_root) + 2);
CREATE OR REPLACE TEMP MACRO refinement_run_directory(path, session_root) AS
    session_relative_path(parse_dirpath(parse_dirpath(parse_dirpath(path))), session_root);
"""


def rocrate_as_duckdb_ddl(session_dir: Path) -> list[DDLStatement]:
    rocrate_path = session_dir / BASENAME
    params: DDLParameters = {"rocrate_path": str(rocrate_path)}
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


def _single_chain_stats_csv_as_duckdb_ddl(single_chain_stats_csv: Path) -> list[DDLStatement]:
    return [
        (
            """\
            CREATE TABLE single_chain_stats AS
            SELECT * FROM read_csv($single_chain_stats_csv);
            """,
            {"single_chain_stats_csv": str(single_chain_stats_csv)},
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

    """
    indexes = sorted((session_dir / "refine").glob("*/io.csv"))
    if refine_run_id is not None:
        indexes = [p for p in indexes if p.parent.name == refine_run_id]
        if not indexes:
            msg = f"Unknown refinement run ID: {refine_run_id}"
            raise ValueError(msg)
    return indexes


def refinements_io_as_duckdb_ddl(session_dir: Path) -> list[DDLStatement]:
    """Build the statements that load refinement input/output mappings.

    Args:
        session_dir: Session directory containing refinement runs.

    Returns:
        SQL statements and bound parameters for creating refinements_io from
        matching run indexes; empty if no indexes exist.

    """
    io_pattern = session_dir / "refine" / "*" / "io.csv"
    has_io = any((session_dir / "refine").glob("*/io.csv"))
    if not has_io:
        return []
    return [
        (
            """\
            CREATE TABLE refinements_io AS
            SELECT
            *
            FROM read_csv($indexes, all_varchar = true);
            """,
            {"indexes": str(io_pattern)},
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

    single_chain_stats_csv = session_dir / "single_chain_stats.csv"
    if single_chain_stats_csv.exists():
        statements.extend(_single_chain_stats_csv_as_duckdb_ddl(single_chain_stats_csv))

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

    statements.extend(powerfit_metadata_as_duckdb_ddl(session_dir))
    statements.extend(powerfit_runs_as_duckdb_ddl(session_dir))

    return statements


def powerfit_metadata_as_duckdb_ddl(session_dir: Path) -> list[DDLStatement]:
    """Load existing fitting indexes for metadata joins and refinement reporting."""
    statements: list[DDLStatement] = []
    fittable_structures_csv = session_dir / "powerfit" / "fittable_structures.csv"
    if fittable_structures_csv.exists():
        statements.extend(_fittable_structures_csv_as_duckdb_ddl(fittable_structures_csv))

    fitted_models_csv = session_dir / "powerfit" / "fitted_models.csv"
    if fitted_models_csv.exists():
        statements.extend(_fitted_models_csv_as_duckdb_ddl(fitted_models_csv))

    return statements


def powerfit_runs_as_duckdb_ddl(session_dir: Path) -> list[DDLStatement]:
    """Load fitting run identities, explicit provenance targets and options.

    Args:
        session_dir: Session directory containing workflow files and provenance.

    Returns:
        Statements creating and populating ``powerfit_runs`` from recorded runs
        and existing run directories. Unrecorded directories have null provenance
        fields. Returns an empty list when neither recorded runs nor run
        directories exist.
    """
    runs = powerfit_run_arguments_from_rocrate(session_dir)
    for path in (session_dir / "powerfit").glob("*"):
        if path.is_dir():
            runs.setdefault(path.name, {"used_target": None, "options": None, "action_id": None})
    if not runs:
        return []
    statements: list[DDLStatement] = [
        (
            """
        CREATE TABLE powerfit_runs (
            powerfit_run_id VARCHAR PRIMARY KEY,
            powerfit_run_dir VARCHAR,
            used_target VARCHAR,
            options VARCHAR,
            action_id VARCHAR
        )
        """,
            {},
        )
    ]
    for run_id, record in sorted(runs.items()):
        fields: DDLParameters = {
            "powerfit_run_id": run_id,
            "powerfit_run_dir": str(Path("powerfit") / run_id),
            "used_target": record["used_target"],
            "options": record["options"],
            "action_id": record["action_id"],
        }
        statements.append(
            (
                """
            INSERT INTO powerfit_runs VALUES (
                $powerfit_run_id, $powerfit_run_dir, $used_target, $options, $action_id
            )
            """,
                fields,
            )
        )
    return statements


def structure_files_as_duckdb_ddl(session_dir: Path) -> list[DDLStatement]:
    session_dir = session_dir.absolute()
    cif_pattern = session_dir / "**" / "*.cif.gz"
    pdb_pattern = session_dir / "**" / "*.pdb"
    pdbgz_pattern = session_dir / "**" / "*.pdb.gz"
    return [
        (
            _PATH_MACROS  # noqa: S608 - concatenating only constant SQL
            + """\
            CREATE TABLE structure_files AS
            SELECT file, parse_dirpath(file) AS parent_dir, parse_filename(file) AS filename FROM (
                SELECT session_relative_path(file, $session_dir) AS file FROM glob($cif_pattern)
                UNION ALL
                SELECT session_relative_path(file, $session_dir) AS file FROM glob($pdb_pattern)
                UNION ALL
                SELECT session_relative_path(file, $session_dir) AS file FROM glob($pdbgz_pattern)
            );
            """,
            {
                "session_dir": str(session_dir),
                "cif_pattern": str(cif_pattern),
                "pdb_pattern": str(pdb_pattern),
                "pdbgz_pattern": str(pdbgz_pattern),
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


def refinements_capri_ss_as_duckdb_ddl(session_dir: Path) -> list[DDLStatement]:
    session_dir = session_dir.absolute()
    #  */*/*/* == refine_run_id / powerfit_run_id / unfitted structure / fitted structure
    refine_dirs = session_dir / "refine" / "*" / "*" / "*" / "*"
    capri_ss_pattern = refine_dirs / "refinement" / LAST_CAPRIEVAL_MODULE / "capri_ss.tsv"
    has_ss = any(session_dir.glob(str(capri_ss_pattern.relative_to(session_dir))))
    if not has_ss:
        return []
    # the clean = True in haddock3 config, causes pdb files to be gzipped,
    # but tsv files are still pointing to the original filenames (model column)
    # also path is relative to tsv make it relative to session_dir
    # so ../6_mdref/mdref_3.pdb + filename -> refine_run_dir / 6_mdref/mdref_3.pdb.gz
    # to make refined_structure_path
    # Normalize names so `model-cluster_ranking` becomes `modelcluster_ranking`.
    return [
        (
            _PATH_MACROS
            + """\
            CREATE TABLE refinements_capri_ss AS
            SELECT
            * REPLACE (session_relative_path(filename, $session_dir) AS filename)
            ,session_relative_path(
                parse_dirpath(parse_dirpath(filename)) || '/' || substring(model, 4) || '.gz', $session_dir
            ) AS refined_structure_path
            ,refinement_run_directory(filename, $session_dir) AS refine_run_dir
            ,parse_path(filename)[-4] AS fitted_structure
            ,parse_path(filename)[-5] AS unfitted_structure
            ,parse_path(filename)[-6] AS powerfit_run_id
            ,parse_path(filename)[-7] AS refine_run_id
            FROM
            read_csv(
                $capri_ss_pattern, delim = '\t', header = true, nullstr = '-',
                normalize_names = true, comment = '#', filename = true
            )
            """,
            {
                "session_dir": str(session_dir),
                "capri_ss_pattern": str(capri_ss_pattern),
            },
        ),
    ]


def refinements_capri_clt_as_duckdb_ddl(session_dir: Path) -> list[DDLStatement]:
    session_dir = session_dir.absolute()
    #  */*/*/* == refine_run_id / powerfit_run_id / unfitted structure / fitted structure
    refine_dirs = session_dir / "refine" / "*" / "*" / "*" / "*"
    capri_clt_pattern = refine_dirs / "refinement" / LAST_CAPRIEVAL_MODULE / "capri_clt.tsv"
    has_clt = any(session_dir.glob(str(capri_clt_pattern.relative_to(session_dir))))
    if not has_clt:
        return []
    return [
        (
            _PATH_MACROS
            + """\
            CREATE TABLE refinements_capri_clt AS
            SELECT
            *
            ,refinement_run_directory(filename, $session_dir) AS refine_run_dir
            ,parse_path(filename)[-4] AS fitted_structure
            ,parse_path(filename)[-5] AS unfitted_structure
            ,parse_path(filename)[-6] AS powerfit_run_id
            ,parse_path(filename)[-7] AS refine_run_id
            FROM
            read_csv($capri_clt_pattern, delim = '\t', header = true, nullstr = '-', comment = '#')
            """,
            {
                "session_dir": str(session_dir),
                "capri_clt_pattern": str(capri_clt_pattern),
            },
        ),
    ]


def refinements_baseline(session_dir: Path) -> list[DDLStatement]:
    session_dir = session_dir.absolute()
    #  */*/*/* == refine_run_id / powerfit_run_id / unfitted structure / fitted structure
    refine_dirs = session_dir / "refine" / "*" / "*" / "*" / "*"
    baseline_pattern = refine_dirs / "baseline" / "2_caprieval" / "capri_ss.tsv"
    has_baseline = any(session_dir.glob(str(baseline_pattern.relative_to(session_dir))))
    if not has_baseline:
        return []
    return [
        (
            _PATH_MACROS
            + """\
            CREATE TABLE refinements_baseline AS
            SELECT
            *
            ,refinement_run_directory(filename, $session_dir) AS refine_run_dir
            ,parse_path(filename)[-4] AS fitted_structure
            ,parse_path(filename)[-5] AS unfitted_structure
            ,parse_path(filename)[-6] AS powerfit_run_id
            ,parse_path(filename)[-7] AS refine_run_id
            FROM
            read_csv($baseline_pattern, delim = '\t', header = true, nullstr = '-', comment = '#')
            """,
            {
                "session_dir": str(session_dir),
                "baseline_pattern": str(baseline_pattern),
            },
        ),
    ]


def refinements_runs_as_duckdb_ddl(session_dir: Path) -> list[DDLStatement]:
    # parsing known structure from rocrate action id is too hard in duckdb,
    # so we use Python shlex instead and use classical `CREATE TABLE` and `INSERT` statements.
    runs = refine_run_arguments_from_rocrate(session_dir, session_relative=True)
    if not runs:
        return []
    statements: list[DDLStatement] = [
        (
            """\
        CREATE TABLE refinements_runs (
            refine_run_id TEXT,
            run_dir TEXT,
            known_structure TEXT,
            processed_known_structure TEXT,
            options TEXT
        )
        """,
            {},
        ),
    ]
    for refinement_run_id, (known_structure, options) in runs.items():
        run_dir = Path("refine") / refinement_run_id
        processed_known_structure = run_dir / "known_structure.pdb"
        statements.append(
            (
                """\
                INSERT INTO refinements_runs (
                    refine_run_id, run_dir, known_structure, processed_known_structure, options
                ) VALUES (
                    $refine_run_id, $run_dir, $known_structure, $processed_known_structure, $options
                )
                """,
                {
                    "refine_run_id": refinement_run_id,
                    "run_dir": str(run_dir),
                    "known_structure": known_structure,
                    "processed_known_structure": str(processed_known_structure),
                    "options": options,
                },
            )
        )
    return statements


def refinement_tables(session_dir: Path) -> list[DDLStatement]:
    statements: list[DDLStatement] = []
    statements.extend(refinements_capri_ss_as_duckdb_ddl(session_dir))
    statements.extend(refinements_capri_clt_as_duckdb_ddl(session_dir))
    statements.extend(refinements_baseline(session_dir))
    statements.extend(refinements_io_as_duckdb_ddl(session_dir))
    statements.extend(refinements_runs_as_duckdb_ddl(session_dir))
    return statements


def ddl(session_dir: Path) -> list[DDLStatement]:
    statements: list[DDLStatement] = []
    statements.extend(structure_files_as_duckdb_ddl(session_dir))
    statements.extend(rocrate_as_duckdb_ddl(session_dir))
    statements.extend(stats_csv_as_duckdb_ddl(session_dir))
    statements.extend(solutions_as_duckdb_ddl(session_dir))
    statements.extend(refinement_tables(session_dir))
    return statements


class ExecuteError(Exception):
    def __init__(self, statement_and_params: DDLStatement):
        self.statement, self.params = statement_and_params
        super().__init__(f"Error executing statement: `{self.statement}`\nWith params: {self.params}")


def execute_ddl_statements(con: duckdb.DuckDBPyConnection, statements: list[DDLStatement]) -> None:
    """Execute parameterized DDL statements in order.

    Args:
        con: DuckDB connection on which to execute the statements.
        statements: SQL statements paired with their named parameters.

    Raises:
        ExecuteError: A statement fails; includes its SQL and parameters.
    """
    for statement, params in statements:
        try:
            con.execute(statement, params)
        except duckdb.Error as e:
            raise ExecuteError((statement, params)) from e


def in_memory_duckdb_connection(
    session_dir: Path,
):
    statements = ddl(session_dir)
    con = duckdb.connect(database=":memory:")
    execute_ddl_statements(con, statements)
    return con


def create_meta_duckdb_file(
    session_dir: Path,
    duckdb_file: Path | None = None,
):
    statements = ddl(session_dir)
    if duckdb_file is None:
        duckdb_file = session_dir / "meta.duckdb"
    con = duckdb.connect(database=str(duckdb_file))
    execute_ddl_statements(con, statements)
    con.close()


def create_meta_duckdb(
    session_dir: Annotated[Path, Parameter(validator=validators.Path(file_okay=False, dir_okay=True, exists=True))],
) -> None:
    """Generate a DuckDB metadata database for a Protein Detective session.

    Filesystem paths are relative to the session directory. Raw CAPRI ``model``
    values retain their source meaning; use ``refined_structure_path`` instead.
    Recorded commands and other provenance text retain their original values.

    Args:
        session_dir: Session directory containing the files to include.
    """
    create_meta_duckdb_file(session_dir)
    duckdb_file = session_dir / "meta.duckdb"
    rprint(
        f"[green]{duckdb_file} has been generated.[/green]\n"
        "See https://www.bonvinlab.org/protein-detective/meta.html for example queries.\n"
        f"Use `duckdb --readonly {duckdb_file}` to query it.",
        soft_wrap=True,
    )
