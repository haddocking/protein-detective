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

from protein_detective.powerfit.workflow import powerfit_solutions_query

DDLStatement = tuple[str, dict[str, str]]
"""SQL DDL statement and named parameters (use $ prefix in SQL) to be passed to DuckDB connection.execute()"""


def rocrate_as_duckdb_ddl(session_dir: Path) -> list[DDLStatement]:
    rocrate_path = session_dir / BASENAME
    params = {"rocrate_path": str(rocrate_path)}
    return [
        (
            dedent("""\
            CREATE TABLE rocrate_nodes AS
            SELECT "@id" AS id, "@type" AS type, * EXCLUDE("@id", "@type")
            FROM (
                SELECT unnest("@graph", max_depth:=2) FROM read_json($rocrate_path)
            );
            """),
            params,
        ),
        (
            dedent("""\
            ALTER TABLE rocrate_nodes
            ADD PRIMARY KEY (id);
            """),
            {},
        ),
        (
            # command is name column without absolute path to protein-detective executable
            dedent("""\
            CREATE TABLE rocrate_create_actions (
                id VARCHAR PRIMARY KEY,
                type VARCHAR,
                name VARCHAR,
                agent STRUCT("@id" VARCHAR),
                endTime VARCHAR,
                instrument STRUCT("@id" VARCHAR),
                object STRUCT("@id" VARCHAR)[],
                result STRUCT("@id" VARCHAR)[],
                startTime VARCHAR,
                command VARCHAR,
                FOREIGN KEY (id) REFERENCES rocrate_nodes(id)
            );
            """),
            {},
        ),
        (
            dedent("""\
            INSERT INTO rocrate_create_actions
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
            """),
            {},
        ),
        (
            dedent("""\
            CREATE TABLE rocrate_inodes (
                id VARCHAR PRIMARY KEY,
                type VARCHAR,
                description VARCHAR,
                name VARCHAR,
                FOREIGN KEY (id) REFERENCES rocrate_nodes(id)
            );
            """),
            {},
        ),
        (
            dedent("""\
            INSERT INTO rocrate_inodes
            SELECT id, type, description, name
            FROM rocrate_nodes
            WHERE type = 'File' OR type = 'Dataset';
            """),
            {},
        ),
        (
            dedent("""\
            CREATE TABLE rocrate_objects (
                action_id VARCHAR,
                object_id VARCHAR,
                FOREIGN KEY (action_id) REFERENCES rocrate_create_actions(id),
                FOREIGN KEY (object_id) REFERENCES rocrate_inodes(id)
            );
            """),
            {},
        ),
        (
            dedent("""\
            INSERT INTO rocrate_objects
            SELECT id AS action_id, json_extract_string(unnest(object), '@id') AS object_id
            FROM rocrate_create_actions;
            """),
            {},
        ),
        (
            dedent("""\
            CREATE TABLE rocrate_results (
                action_id VARCHAR,
                result_id VARCHAR,
                FOREIGN KEY (action_id) REFERENCES rocrate_create_actions(id),
                FOREIGN KEY (result_id) REFERENCES rocrate_inodes(id)
            );
            """),
            {},
        ),
        (
            dedent("""\
            INSERT INTO rocrate_results
            SELECT id AS action_id, json_extract_string(unnest(result), '@id') AS result_id
            FROM rocrate_create_actions;
            """),
            {},
        ),
    ]


def _uniprot_stats_csv_as_duckdb_ddl(uniprot_txt: Path) -> list[DDLStatement]:
    return [
        (
            dedent("""\
            CREATE TABLE uniprot (
                uniprot_accession VARCHAR PRIMARY KEY
            );
            """),
            {},
        ),
        (
            dedent("""\
            INSERT INTO uniprot
            SELECT DISTINCT uniprot_accession
            FROM read_csv($uniprot_txt, header = false, columns={'uniprot_accession': 'VARCHAR'})
            WHERE uniprot_accession IS NOT NULL;
            """),
            {"uniprot_txt": str(uniprot_txt)},
        ),
    ]


def _alphafold_stats_csv_as_duckdb_ddl(alphafold_csv: Path, has_uniprot: bool) -> list[DDLStatement]:
    if has_uniprot:
        return [
            (
                dedent("""\
                CREATE TABLE alphafold (
                    uniprot_accession VARCHAR,
                    af_id VARCHAR,
                    FOREIGN KEY (uniprot_accession) REFERENCES uniprot(uniprot_accession)
                );
                """),
                {},
            ),
            (
                dedent("""\
                INSERT INTO alphafold
                SELECT
                    uniprot_accession::VARCHAR,
                    af_id::VARCHAR
                FROM read_csv($alphafold_csv);
                """),
                {"alphafold_csv": str(alphafold_csv)},
            ),
        ]
    return [
        (
            dedent("""\
            CREATE TABLE alphafold AS
            SELECT * FROM read_csv($alphafold_csv);
            """),
            {"alphafold_csv": str(alphafold_csv)},
        )
    ]


def _pdbe_stats_csv_as_duckdb_ddl(pdbe_csv: Path, has_uniprot: bool) -> list[DDLStatement]:
    if has_uniprot:
        return [
            (
                dedent("""\
                CREATE TABLE pdbe (
                    uniprot_accession VARCHAR,
                    pdb_id VARCHAR,
                    method VARCHAR,
                    resolution DOUBLE,
                    uniprot_chains VARCHAR,
                    chain VARCHAR,
                    chain_length INTEGER,
                    FOREIGN KEY (uniprot_accession) REFERENCES uniprot(uniprot_accession)
                );
                """),
                {},
            ),
            (
                dedent("""\
                INSERT INTO pdbe
                SELECT
                    uniprot_accession::VARCHAR,
                    pdb_id::VARCHAR,
                    method::VARCHAR,
                    resolution::DOUBLE,
                    uniprot_chains::VARCHAR,
                    chain::VARCHAR,
                    chain_length::INTEGER
                FROM read_csv($pdbe_csv);
                """),
                {"pdbe_csv": str(pdbe_csv)},
            ),
        ]
    return [
        (
            dedent("""\
            CREATE TABLE pdbe AS
            SELECT * FROM read_csv($pdbe_csv);
            """),
            {"pdbe_csv": str(pdbe_csv)},
        )
    ]


def _uniprots_verified_stats_csv_as_duckdb_ddl(
    uniprots_verified_stats_csv: Path,
) -> list[DDLStatement]:
    return [
        (
            dedent("""\
            CREATE TABLE uniprots_verified_stats (
                input_file VARCHAR,
                output_file VARCHAR,
                injected BOOLEAN,
                uniprot_chain_mappings VARCHAR,
                FOREIGN KEY (input_file) REFERENCES structure_files(file),
                FOREIGN KEY (output_file) REFERENCES structure_files(file)
            );
            """),
            {},
        ),
        (
            dedent("""\
            INSERT INTO uniprots_verified_stats
            SELECT
                input_file::VARCHAR,
                output_file::VARCHAR,
                injected::BOOLEAN,
                uniprot_chain_mappings::VARCHAR
            FROM read_csv($uniprots_verified_stats_csv);
            """),
            {"uniprots_verified_stats_csv": str(uniprots_verified_stats_csv)},
        ),
    ]


def _combined_stats_csv_as_duckdb_ddl(combined_stats_csv: Path) -> list[DDLStatement]:
    return [
        (
            (
                dedent("""\
                CREATE TABLE combined_stats (
                    input_file VARCHAR,
                    structure_id VARCHAR,
                    uniprot_accession VARCHAR,
                    resolution DOUBLE,
                    high_confidence_residues_count INTEGER,
                    total_residue_count INTEGER,
                    method VARCHAR,
                    is_alphafold BOOLEAN,
                    uniprot_start INTEGER,
                    uniprot_end INTEGER,
                    sequence_identity DOUBLE,
                    chain_length INTEGER,
                    geometry_quality DOUBLE,
                    passed BOOLEAN,
                    output_file VARCHAR,
                    reason VARCHAR,
                    FOREIGN KEY (input_file) REFERENCES structure_files(file),
                    -- disabled foreign key as uniprot.txt and best uniprot in structure files may differ
                    -- FOREIGN KEY (uniprot_accession) REFERENCES uniprot(uniprot_accession)
                    FOREIGN KEY (output_file) REFERENCES structure_files(file)
                );
                """)
            ),
            {},
        ),
        (
            dedent("""\
            INSERT INTO combined_stats
            SELECT
                input_file::VARCHAR,
                structure_id::VARCHAR,
                uniprot_accession::VARCHAR,
                resolution::DOUBLE,
                high_confidence_residues_count::INTEGER,
                total_residue_count::INTEGER,
                method::VARCHAR,
                is_alphafold::BOOLEAN,
                uniprot_start::INTEGER,
                uniprot_end::INTEGER,
                sequence_identity::DOUBLE,
                chain_length::INTEGER,
                geometry_quality::DOUBLE,
                passed::BOOLEAN,
                output_file::VARCHAR,
                reason::VARCHAR
            FROM read_csv($combined_stats_csv);
            """),
            {"combined_stats_csv": str(combined_stats_csv)},
        ),
    ]


def _secondary_structure_stats_csv_as_duckdb_ddl(
    secondary_structure_stats_csv: Path,
) -> list[DDLStatement]:
    return [
        (
            dedent("""\
            CREATE TABLE secondary_structure_stats AS
            SELECT * FROM read_csv($secondary_structure_stats_csv);
            """),
            {"secondary_structure_stats_csv": str(secondary_structure_stats_csv)},
        )
    ]


def _fittable_structures_csv_as_duckdb_ddl(fittable_structures_csv: Path) -> list[DDLStatement]:
    return [
        (
            dedent("""\
            CREATE TABLE fittable_structures (
                structure_file VARCHAR,
                structure VARCHAR,
                structure_id VARCHAR,
                is_alphafold BOOLEAN,
                uniprot_accessions VARCHAR,
                FOREIGN KEY (structure_file) REFERENCES structure_files(file)
            );
            """),
            {},
        ),
        (
            dedent("""\
            INSERT INTO fittable_structures
            SELECT
                structure_file::VARCHAR,
                structure::VARCHAR,
                structure_id::VARCHAR,
                is_alphafold::BOOLEAN,
                uniprot_accessions::VARCHAR
            FROM read_csv($fittable_structures_csv);
            """),
            {"fittable_structures_csv": str(fittable_structures_csv)},
        ),
    ]


def stats_csv_as_duckdb_ddl(session_dir: Path) -> list[DDLStatement]:
    statements: list[DDLStatement] = []

    uniprot_txt = session_dir / "uniprot.txt"
    has_uniprot = uniprot_txt.exists()
    if has_uniprot:
        statements.extend(_uniprot_stats_csv_as_duckdb_ddl(uniprot_txt))

    alphafold_csv = session_dir / "alphafold.csv"
    if alphafold_csv.exists():
        statements.extend(_alphafold_stats_csv_as_duckdb_ddl(alphafold_csv, has_uniprot))

    pdbe_csv = session_dir / "pdbe.csv"
    if pdbe_csv.exists():
        statements.extend(_pdbe_stats_csv_as_duckdb_ddl(pdbe_csv, has_uniprot))

    uniprots_verified_stats_csv = session_dir / "uniprots_verified_stats.csv"
    if uniprots_verified_stats_csv.exists():
        statements.extend(_uniprots_verified_stats_csv_as_duckdb_ddl(uniprots_verified_stats_csv))

    combined_stats_csv = session_dir / "combined_stats.csv"
    if combined_stats_csv.exists():
        statements.extend(_combined_stats_csv_as_duckdb_ddl(combined_stats_csv))

    secondary_structure_stats_csv = session_dir / "secondary_structure_stats.csv"
    if secondary_structure_stats_csv.exists():
        statements.extend(_secondary_structure_stats_csv_as_duckdb_ddl(secondary_structure_stats_csv))

    fittable_structures_csv = session_dir / "powerfit" / "fittable_structures.csv"
    if fittable_structures_csv.exists():
        statements.extend(_fittable_structures_csv_as_duckdb_ddl(fittable_structures_csv))

    return statements


def structure_files_as_duckdb_ddl(session_dir: Path) -> list[DDLStatement]:
    cif_pattern = session_dir / "**" / "*.cif.gz"
    pdb_pattern = session_dir / "**" / "*.pdb"
    return [
        (
            dedent("""\
            CREATE TABLE structure_files (
                file VARCHAR PRIMARY KEY,
                parent_dir VARCHAR,
                filename VARCHAR
            );
            """),
            {},
        ),
        (
            dedent("""\
            INSERT INTO structure_files
            SELECT file, parse_dirpath(file) AS parent_dir, parse_filename(file) AS filename FROM (
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
        ),
    ]


def solutions_as_duckdb_ddl(session_dir: Path, powerfit_run_id: str | None = None) -> list[DDLStatement]:
    solutions_pattern = session_dir / "powerfit" / "*" / "*" / "solutions.out"
    if powerfit_run_id:
        solutions_pattern = session_dir / "powerfit" / powerfit_run_id / "*" / "solutions.out"
    return [
        (
            dedent("""\
            CREATE TABLE solutions (
                powerfit_run_id VARCHAR,
                structure VARCHAR,
                rank INTEGER,
                cc FLOAT,
                fishz FLOAT,
                relz FLOAT,
                translation FLOAT[3],
                rotation FLOAT[9],
                template_file VARCHAR,
                uniprot_accessions VARCHAR,
                structure_id VARCHAR,
                is_alphafold BOOLEAN,
                FOREIGN KEY (template_file) REFERENCES structure_files(file)
            );
            """),
            {},
        ),
        (
            "INSERT INTO solutions\n" + powerfit_solutions_query("JOIN fittable_structures USING (structure)") + ";",
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
