"""


TODO remove block below
```shell
protein-detective powerfit run --gpu-backend cuda --powerfit-run-id myrun1 \
--angle 20 --scheduler-address sequential \
../powerfit-tutorial/ribosome-KsgA.map 13 ./mysession
```

TODO add foreign constraints so ER diagram can be generated with it
TODO add example queries to meta.ipynb
TODO find better name for meta module, like "trace", "history".
"""

from pathlib import Path
from textwrap import dedent

import duckdb
from rocrate.metadata import BASENAME

DDLStatement = tuple[str, dict[str, str]]


def rocrate_as_duckdb_ddl(session_dir: Path) -> list[DDLStatement]:
    rocrate_path = session_dir / BASENAME
    params = {"rocrate_path": str(rocrate_path)}
    return [
        (
            dedent("""\
            CREATE TABLE rocrate_nodes AS
            SELECT unnest("@graph", max_depth:=2) FROM read_json($rocrate_path);
            """),
            params,
        ),
        (
            # command is name column without absolute path to protein-detective executable
            dedent("""\
            CREATE TABLE rocrate_create_actions AS
            SELECT *, substr(name, strpos(name, 'protein-detective')) AS command
            FROM rocrate_nodes WHERE "@type" = 'CreateAction';
            """),
            {},
        ),
        (
            dedent("""\
            CREATE TABLE rocrate_files AS
            SELECT * FROM rocrate_nodes WHERE "@type" = 'File';
            """),
            {},
        ),
        (
            dedent("""\
            CREATE TABLE rocrate_dirs AS
            SELECT * FROM rocrate_nodes WHERE "@type" = 'Dataset';
            """),
            {},
        ),
        (
            dedent("""\
            CREATE TABLE rocrate_objects AS
            SELECT "@id", unnest("object") FROM rocrate_create_actions;
            """),
            {},
        ),
        (
            dedent("""\
            CREATE TABLE rocrate_results AS
            SELECT "@id", unnest(result) FROM rocrate_create_actions;
            """),
            {},
        ),
    ]


def stats_csv_as_duckdb_ddl(session_dir: Path) -> list[DDLStatement]:
    statements: list[DDLStatement] = []

    uniprot_txt = session_dir / "uniprot.txt"
    if uniprot_txt.exists():
        statements.append(
            (
                dedent("""\
            CREATE TABLE uniprot AS
            SELECT * FROM read_csv($uniprot_txt);
        """),
                {"uniprot_txt": str(uniprot_txt)},
            )
        )
    alphafold_csv = session_dir / "alphafold.csv"
    if alphafold_csv.exists():
        statements.append(
            (
                dedent("""\
            CREATE TABLE alphafold AS
            SELECT * FROM read_csv($alphafold_csv);
        """),
                {"alphafold_csv": str(alphafold_csv)},
            )
        )
    pdbe_csv = session_dir / "pdbe.csv"
    if pdbe_csv.exists():
        statements.append(
            (
                dedent("""\
            CREATE TABLE pdbe AS
            SELECT * FROM read_csv($pdbe_csv);
        """),
                {"pdbe_csv": str(pdbe_csv)},
            )
        )
    uniprots_verified_stats_csv = session_dir / "uniprots_verified_stats.csv"
    if uniprots_verified_stats_csv.exists():
        statements.append(
            (
                dedent("""\
            CREATE TABLE uniprots_verified_stats AS
            SELECT * FROM read_csv($uniprots_verified_stats_csv);
        """),
                {"uniprots_verified_stats_csv": str(uniprots_verified_stats_csv)},
            )
        )
    combined_stats_csv = session_dir / "combined_stats.csv"
    if combined_stats_csv.exists():
        statements.append(
            (
                dedent("""\
            CREATE TABLE combined_stats AS
            SELECT * FROM read_csv($combined_stats_csv);
        """),
                {"combined_stats_csv": str(combined_stats_csv)},
            )
        )
    secondary_structure_stats_csv = session_dir / "secondary_structure_stats.csv"
    if secondary_structure_stats_csv.exists():
        statements.append(
            (
                dedent("""\
            CREATE TABLE secondary_structure_stats AS
            SELECT * FROM read_csv($secondary_structure_stats_csv);
        """),
                {"secondary_structure_stats_csv": str(secondary_structure_stats_csv)},
            )
        )

    fittable_structures_csv = session_dir / "powerfit" / "fittable_structures.csv"
    if fittable_structures_csv.exists():
        statements.append(
            (
                dedent("""\
            CREATE TABLE fittable_structures AS
            SELECT * FROM read_csv($fittable_structures_csv);
        """),
                {"fittable_structures_csv": str(fittable_structures_csv)},
            )
        )

    return statements


def structure_files_as_duckdb_ddl(session_dir: Path) -> list[DDLStatement]:
    cif_pattern = session_dir / "**" / "*.cif.gz"
    pdb_pattern = session_dir / "**" / "*.pdb"
    return [
        (
            dedent("""\
            CREATE TABLE structure_files AS
            SELECT file, parse_dirname(file) AS parent_dir, parse_filename(file) AS filename FROM (
                -- TODO replace only works on unixy systems
                SELECT replace(file, $session_dir || '/', '') AS file FROM glob($cif_pattern)
                UNION ALL
                SELECT replace(file, $session_dir || '/', '') AS file FROM glob($pdb_pattern)
            );
            """),
            {
                "session_dir": str(session_dir),
                "cif_pattern": str(cif_pattern),
                "pdb_pattern": str(pdb_pattern),
            },
        )
    ]


def solutions_as_duckdb_ddl(session_dir: Path, powerfit_run_id: str | None = None) -> list[DDLStatement]:
    # TODO call this in workflow module
    solutions_pattern = session_dir / "powerfit" / "*" / "*" / "solutions.out"
    if powerfit_run_id:
        solutions_pattern = session_dir / "powerfit" / powerfit_run_id / "*" / "solutions.out"
    return [
        (
            dedent("""\
            CREATE TABLE solutions AS
            SELECT
                powerfit_run_id,
                structure,
                rank,
                cc,
                fishz,
                relz,
                translation,
                rotation,
                structure_file AS template_file,
                uniprot_accessions,
                structure_id,
                is_alphafold
            FROM (
                SELECT
                    parse_path(filename)[-3] AS powerfit_run_id,
                    parse_path(filename)[-2] AS structure,
                    rank, cc, fishz, relz,
                    [x,y,z]::FLOAT[3] AS translation,
                    [a11, a12, a13, a21, a22, a23, a31, a32, a33]::FLOAT[9] AS rotation
                FROM
                    read_csv(
                        $solutions_pattern,
                        filename=True, normalize_names=True,
                        columns={
                            'rank': 'INTEGER',
                            'cc': 'FLOAT',
                            'fishz': 'FLOAT',
                            'relz': 'FLOAT',
                            'x': 'FLOAT',
                            'y': 'FLOAT',
                            'z': 'FLOAT',
                            'a11': 'FLOAT',
                            'a12': 'FLOAT',
                            'a13': 'FLOAT',
                            'a21': 'FLOAT',
                            'a22': 'FLOAT',
                            'a23': 'FLOAT',
                            'a31': 'FLOAT',
                            'a32': 'FLOAT',
                            'a33': 'FLOAT',
                        }
                    )
                ) AS solutions
                JOIN fittable_structures USING (structure)
            ORDER BY cc DESC, rank ASC;
            """),
            {"solutions_pattern": str(solutions_pattern)},
        )
    ]


def ddl(session_dir: Path, powerfit_run_id: str | None = None) -> list[DDLStatement]:
    statements: list[DDLStatement] = []
    statements.extend(rocrate_as_duckdb_ddl(session_dir))
    statements.extend(stats_csv_as_duckdb_ddl(session_dir))
    statements.extend(structure_files_as_duckdb_ddl(session_dir))
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
