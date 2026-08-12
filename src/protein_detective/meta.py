"""


TODO remove block below
Fit crudly
```shell
protein-detective powerfit run --gpu-backend cuda --powerfit-run-id myrun1 \
--angle 20 --scheduler-address sequential \
../powerfit-tutorial/ribosome-KsgA.map 13 ./mysession
```

"""

from pathlib import Path
from textwrap import dedent

from rocrate.metadata import BASENAME


def rocrate_as_duckdb_ddl(session_dir: Path) -> tuple[str, dict[str,str]]:
    rocrate_path = session_dir / BASENAME
    ddl = dedent("""\
        CREATE TABLE rocrate_nodes AS
        SELECT unnest("@graph", max_depth:=2) FROM read_json(":rocrate_path");

        CREATE TABLE rocrate_create_actions AS
        SELECT * FROM rocrate_nodes WHERE "@type" = 'CreateAction';

        CREATE TABLE rocrate_files AS
        SELECT * FROM rocrate_nodes WHERE "@type" = 'File';

        CREATE TABLE rocrate_dirs AS
        SELECT * FROM rocrate_nodes WHERE "@type" = 'Dataset';

        CREATE TABLE rocrate_objects AS
        SELECT "@id", unnest("object")  FROM rocrate_create_actions;

        CREATE TABLE rocrate_results AS
        SELECT "@id", unnest(result)  FROM rocrate_create_actions;
    """)
    return (ddl, {"rocrate_path": str(rocrate_path)})

def stats_csv_as_duckdb_ddl(session_dir: Path) -> tuple[str, dict[str,str]]:
    ddl: list[str] = []
    parameters: dict[str,str] = {}

    uniprot_txt = session_dir / "uniprot.txt"
    if uniprot_txt.exists():
        ddl.append(dedent("""\
            CREATE TABLE uniprot AS
            SELECT * FROM read_csv(":uniprot_txt");
        """))
        parameters["uniprot_txt"] = str(uniprot_txt)
    alphafold_csv = session_dir / "alphafold.csv"
    if alphafold_csv.exists():
        ddl.append(dedent("""\
            CREATE TABLE alphafold AS
            SELECT * FROM read_csv(":alphafold_csv");
        """))
        parameters["alphafold_csv"] = str(alphafold_csv)
    pdbe_csv = session_dir / "pdbe.csv"
    if pdbe_csv.exists():
        ddl.append(dedent("""\
            CREATE TABLE pdbe AS
            SELECT * FROM read_csv(":pdbe_csv");
        """))
        parameters["pdbe_csv"] = str(pdbe_csv)
    uniprots_verified_stats_csv = session_dir / "uniprots_verified_stats.csv"
    if uniprots_verified_stats_csv.exists():
        ddl.append(dedent("""\
            CREATE TABLE uniprots_verified_stats AS
            SELECT * FROM read_csv(":uniprots_verified_stats_csv");
        """))
        parameters["uniprots_verified_stats_csv"] = str(uniprots_verified_stats_csv)
    combined_stats_csv = session_dir / "combined_stats.csv"
    if combined_stats_csv.exists():
        ddl.append(dedent("""\
            CREATE TABLE combined_stats AS
            SELECT * FROM read_csv(":combined_stats_csv");
        """))
        parameters["combined_stats_csv"] = str(combined_stats_csv)
    secondary_structure_stats_csv = session_dir / "secondary_structure_stats.csv"
    if secondary_structure_stats_csv.exists():
        ddl.append(dedent("""\
            CREATE TABLE secondary_structure_stats AS
            SELECT * FROM read_csv(":secondary_structure_stats_csv");
        """))
        parameters["secondary_structure_stats_csv"] = str(secondary_structure_stats_csv)

    return ("\n".join(ddl), parameters,)

def 