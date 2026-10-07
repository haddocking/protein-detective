import json
import shutil
from pathlib import Path

import duckdb
import pytest

from protein_detective.meta import (
    capri_as_duckdb_ddl,
    ddl,
    in_memory_duckdb_connection,
    refinements_io_as_duckdb_ddl,
    solutions_as_duckdb_ddl,
)


def test_solutions_ddl_requires_fittable_structures_and_solutions(tmp_path: Path):
    session_dir = tmp_path / "session"
    powerfit_dir = session_dir / "powerfit"
    solutions_dir = powerfit_dir / "run_001" / "structure"
    solutions_dir.mkdir(parents=True)

    assert solutions_as_duckdb_ddl(session_dir) == []

    fittable_structures_csv = powerfit_dir / "fittable_structures.csv"
    fittable_structures_csv.write_text("structure,structure_file\n")
    assert solutions_as_duckdb_ddl(session_dir) == []

    solutions_out = solutions_dir / "solutions.out"
    solutions_out.write_text("rank,cc\n")
    assert len(solutions_as_duckdb_ddl(session_dir)) == 1

    fittable_structures_csv.unlink()
    assert solutions_as_duckdb_ddl(session_dir) == []


def test_rocrate_columns_are_normalized(tmp_path: Path):
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    powerfit_dir = session_dir / "powerfit" / "run_001" / "structure"
    powerfit_dir.mkdir(parents=True)
    (powerfit_dir / "solutions.out").write_text(
        "rank,cc,fishz,relz,x,y,z,a11,a12,a13,a21,a22,a23,a31,a32,a33\n"
        "1,0.5,0.6,0.7,0.0,0.0,0.0,1.0,0.0,0.0,0.0,1.0,0.0,0.0,0.0,1.0\n"
    )
    (session_dir / "powerfit" / "fittable_structures.csv").write_text(
        "structure,structure_file,structure_id,uniprot_accessions,is_alphafold\n"
        "structure,structure.pdb,struct_1,UP00000001,true\n"
    )
    (session_dir / "structure.pdb").write_text("MODEL\nENDMDL\n")
    (session_dir / "ro-crate-metadata.json").write_text(
        json.dumps(
            {
                "@context": ["https://w3id.org/ro/crate/1.1/context"],
                "@graph": [
                    {
                        "@id": "./",
                        "@type": "Dataset",
                        "description": "An RO-Crate session directory.",
                        "name": "session",
                    },
                    {
                        "@id": "structure",
                        "@type": "File",
                        "description": "Input structure file.",
                        "name": "structure",
                    },
                    {
                        "@id": "run",
                        "@type": "CreateAction",
                        "name": "run",
                        "agent": {"@id": "verhoes"},
                        "description": "Run the analysis.",
                        "endTime": "2026-08-17T09:09:00.000000+00:00",
                        "instrument": {"@id": "protein-detective@0.8.6"},
                        "object": [{"@id": "structure"}],
                        "result": [{"@id": "structure"}],
                        "startTime": "2026-08-17T09:08:00.000000+00:00",
                    },
                ],
            }
        )
    )

    con = in_memory_duckdb_connection(session_dir)
    columns = [row[0] for row in con.execute("DESCRIBE rocrate_nodes").fetchall()]

    assert "id" in columns
    assert "type" in columns
    assert "@id" not in columns
    assert "@type" not in columns

    rows = con.execute("SELECT id, type FROM rocrate_nodes WHERE type = 'CreateAction'").fetchall()
    assert rows == [("run", "CreateAction")]

    object_rows = con.execute("SELECT action_id, object_id FROM rocrate_objects").fetchall()
    assert object_rows == [("run", "structure")]

    result_rows = con.execute("SELECT action_id, result_id FROM rocrate_results").fetchall()
    assert result_rows == [("run", "structure")]


def test_solutions_is_created_as_select(tmp_path: Path):
    session_dir = tmp_path / "session"
    session_dir.mkdir()

    powerfit_dir = session_dir / "powerfit" / "run_001" / "structure"
    powerfit_dir.mkdir(parents=True)
    (powerfit_dir / "solutions.out").write_text(
        "rank,cc,fishz,relz,x,y,z,a11,a12,a13,a21,a22,a23,a31,a32,a33\n"
        "1,0.5,0.6,0.7,0.0,0.0,0.0,1.0,0.0,0.0,0.0,1.0,0.0,0.0,0.0,1.0\n"
    )

    (session_dir / "powerfit" / "fittable_structures.csv").write_text(
        "structure,structure_file,structure_id,uniprot_accessions,is_alphafold\n"
        "structure,structure.pdb,struct_1,UP00000001,true\n"
    )
    (session_dir / "structure.pdb").write_text("MODEL\nENDMDL\n")

    (session_dir / "ro-crate-metadata.json").write_text(
        json.dumps(
            {
                "@context": ["https://w3id.org/ro/crate/1.1/context"],
                "@graph": [
                    {
                        "@id": "./",
                        "@type": "Dataset",
                        "description": "An RO-Crate session directory.",
                        "name": "session",
                    },
                    {
                        "@id": "structure",
                        "@type": "File",
                        "description": "Input structure file.",
                        "name": "structure",
                    },
                    {
                        "@id": "run",
                        "@type": "CreateAction",
                        "name": "run",
                        "agent": {"@id": "verhoes"},
                        "description": "Run the analysis.",
                        "endTime": "2026-08-17T09:09:00.000000+00:00",
                        "instrument": {"@id": "protein-detective@0.8.6"},
                        "object": [{"@id": "structure"}],
                        "result": [{"@id": "structure"}],
                        "startTime": "2026-08-17T09:08:00.000000+00:00",
                    },
                ],
            }
        )
    )

    con = in_memory_duckdb_connection(session_dir)
    rows = con.execute("SELECT structure, template_file, rank, cc FROM solutions").fetchall()

    assert rows == [("structure", "structure.pdb", 1, 0.5)]


def test_merge_structure_files_is_loaded_with_ctas(tmp_path: Path):
    session_dir = tmp_path / "session"
    session_dir.mkdir()

    (session_dir / "merge_structure_files.csv").write_text(
        "source,target\n"
        "downloads/alphafold/AF-P12345-F1-model_v4.cif.gz,combined_input/AF-P12345-F1-model_v4.cif.gz\n"
        "single_chain/structure.pdb,combined_input/structure.pdb\n"
    )
    (session_dir / "downloads" / "alphafold").mkdir(parents=True)
    (session_dir / "downloads" / "alphafold" / "AF-P12345-F1-model_v4.cif.gz").write_text("")
    (session_dir / "single_chain").mkdir(parents=True)
    (session_dir / "single_chain" / "structure.pdb").write_text("")
    (session_dir / "combined_input").mkdir(parents=True)
    (session_dir / "combined_input" / "AF-P12345-F1-model_v4.cif.gz").write_text("")
    (session_dir / "combined_input" / "structure.pdb").write_text("")
    (session_dir / "structure.pdb").write_text("MODEL\nENDMDL\n")

    powerfit_dir = session_dir / "powerfit" / "run_001" / "structure"
    powerfit_dir.mkdir(parents=True)
    (powerfit_dir / "solutions.out").write_text(
        "rank,cc,fishz,relz,x,y,z,a11,a12,a13,a21,a22,a23,a31,a32,a33\n"
        "1,0.5,0.6,0.7,0.0,0.0,0.0,1.0,0.0,0.0,0.0,1.0,0.0,0.0,0.0,1.0\n"
    )
    (session_dir / "powerfit" / "fittable_structures.csv").write_text(
        "structure,structure_file,structure_id,uniprot_accessions,is_alphafold\n"
        "structure,structure.pdb,struct_1,UP00000001,true\n"
    )
    (session_dir / "ro-crate-metadata.json").write_text(
        json.dumps(
            {
                "@context": ["https://w3id.org/ro/crate/1.1/context"],
                "@graph": [
                    {
                        "@id": "./",
                        "@type": "Dataset",
                        "description": "An RO-Crate session directory.",
                        "name": "session",
                    },
                    {
                        "@id": "structure",
                        "@type": "File",
                        "description": "Input structure file.",
                        "name": "structure",
                    },
                    {
                        "@id": "run",
                        "@type": "CreateAction",
                        "name": "run",
                        "agent": {"@id": "verhoes"},
                        "description": "Run the analysis.",
                        "endTime": "2026-08-17T09:09:00.000000+00:00",
                        "instrument": {"@id": "protein-detective@0.8.6"},
                        "object": [{"@id": "structure"}],
                        "result": [{"@id": "structure"}],
                        "startTime": "2026-08-17T09:09:00.000000+00:00",
                    },
                ],
            }
        )
    )

    con = in_memory_duckdb_connection(session_dir)
    rows = con.execute("SELECT source, target FROM merge_structure_files ORDER BY source").fetchall()

    assert rows == [
        (
            "downloads/alphafold/AF-P12345-F1-model_v4.cif.gz",
            "combined_input/AF-P12345-F1-model_v4.cif.gz",
        ),
        ("single_chain/structure.pdb", "combined_input/structure.pdb"),
    ]


def test_combined_stats_is_loaded_with_ctas(tmp_path: Path):
    session_dir = tmp_path / "session"
    session_dir.mkdir()

    (session_dir / "uniprot.txt").write_text("P12345\n")
    (session_dir / "combined_stats.csv").write_text(
        "input_file,structure_id,uniprot_accession,resolution,high_confidence_residues_count,total_residue_count,method,is_alphafold,uniprot_start,uniprot_end,sequence_identity,chain_length,geometry_quality,passed,output_file,reason\n"
        "structure.pdb,struct_1,P12345,2.0,10,100,crystal,false,1,100,0.5,100,0.8,true,structure.pdb,ok\n"
    )
    powerfit_dir = session_dir / "powerfit" / "run_001" / "structure"
    powerfit_dir.mkdir(parents=True)
    (powerfit_dir / "solutions.out").write_text(
        "rank,cc,fishz,relz,x,y,z,a11,a12,a13,a21,a22,a23,a31,a32,a33\n"
        "1,0.5,0.6,0.7,0.0,0.0,0.0,1.0,0.0,0.0,0.0,1.0,0.0,0.0,0.0,1.0\n"
    )
    (session_dir / "powerfit" / "fittable_structures.csv").write_text(
        "structure,structure_file,structure_id,uniprot_accessions,is_alphafold\n"
        "structure,structure.pdb,struct_1,UP00000001,true\n"
    )
    (session_dir / "structure.pdb").write_text("MODEL\nENDMDL\n")
    (session_dir / "ro-crate-metadata.json").write_text(
        json.dumps(
            {
                "@context": ["https://w3id.org/ro/crate/1.1/context"],
                "@graph": [
                    {
                        "@id": "./",
                        "@type": "Dataset",
                        "description": "An RO-Crate session directory.",
                        "name": "session",
                    },
                    {
                        "@id": "structure",
                        "@type": "File",
                        "description": "Input structure file.",
                        "name": "structure",
                    },
                    {
                        "@id": "run",
                        "@type": "CreateAction",
                        "name": "run",
                        "agent": {"@id": "verhoes"},
                        "description": "Run the analysis.",
                        "endTime": "2026-08-17T09:09:00.000000+00:00",
                        "instrument": {"@id": "protein-detective@0.8.6"},
                        "object": [{"@id": "structure"}],
                        "result": [{"@id": "structure"}],
                        "startTime": "2026-08-17T09:08:00.000000+00:00",
                    },
                ],
            }
        )
    )

    con = in_memory_duckdb_connection(session_dir)
    rows = con.execute("SELECT uniprot_accession FROM combined_stats").fetchall()

    assert rows == [("P12345",)]


def test_fitted_models_is_loaded_with_ctas(tmp_path: Path):
    session_dir = tmp_path / "session"
    session_dir.mkdir()

    powerfit_dir = session_dir / "powerfit" / "run_001" / "structure"
    powerfit_dir.mkdir(parents=True)
    (powerfit_dir / "solutions.out").write_text(
        "rank,cc,fishz,relz,x,y,z,a11,a12,a13,a21,a22,a23,a31,a32,a33\n"
        "1,0.5,0.6,0.7,0.0,0.0,0.0,1.0,0.0,0.0,0.0,1.0,0.0,0.0,0.0,1.0\n"
    )
    (powerfit_dir / "fit_1.pdb").write_text("MODEL\nENDMDL\n")
    (session_dir / "powerfit" / "fittable_structures.csv").write_text(
        "structure,structure_file,structure_id,uniprot_accessions,is_alphafold\n"
        "structure,structure.pdb,struct_1,UP00000001,true\n"
    )
    (session_dir / "powerfit" / "fitted_models.csv").write_text(
        "powerfit_run_id,structure,rank,fitted_model_file,unfitted_model_file\n"
        "run_001,structure,1,powerfit/run_001/structure/fit_1.pdb,structure.pdb\n"
    )
    (session_dir / "structure.pdb").write_text("MODEL\nENDMDL\n")
    (session_dir / "ro-crate-metadata.json").write_text(
        json.dumps(
            {
                "@context": ["https://w3id.org/ro/crate/1.1/context"],
                "@graph": [
                    {
                        "@id": "./",
                        "@type": "Dataset",
                        "description": "An RO-Crate session directory.",
                        "name": "session",
                    },
                    {
                        "@id": "structure",
                        "@type": "File",
                        "description": "Input structure file.",
                        "name": "structure",
                    },
                    {
                        "@id": "run",
                        "@type": "CreateAction",
                        "name": "run",
                        "agent": {"@id": "verhoes"},
                        "description": "Run the analysis.",
                        "endTime": "2026-08-17T09:09:00.000000+00:00",
                        "instrument": {"@id": "protein-detective@0.8.6"},
                        "object": [{"@id": "structure"}],
                        "result": [{"@id": "structure"}],
                        "startTime": "2026-08-17T09:08:00.000000+00:00",
                    },
                ],
            }
        )
    )

    con = in_memory_duckdb_connection(session_dir)
    rows = con.execute(
        "SELECT powerfit_run_id, structure, rank, fitted_model_file, unfitted_model_file FROM fitted_models"
    ).fetchall()

    assert rows == [
        (
            "run_001",
            "structure",
            1,
            "powerfit/run_001/structure/fit_1.pdb",
            "structure.pdb",
        )
    ]

    joined = con.execute(
        "SELECT fm.fitted_model_file FROM fitted_models fm "
        "JOIN solutions s ON fm.powerfit_run_id = s.powerfit_run_id "
        "AND fm.structure = s.structure AND fm.rank = s.rank"
    ).fetchall()
    assert joined == [("powerfit/run_001/structure/fit_1.pdb",)]


def test_fitted_models_table_is_absent_without_csv(tmp_path: Path):
    session_dir = tmp_path / "session"
    session_dir.mkdir()

    powerfit_dir = session_dir / "powerfit" / "run_001" / "structure"
    powerfit_dir.mkdir(parents=True)
    (powerfit_dir / "solutions.out").write_text(
        "rank,cc,fishz,relz,x,y,z,a11,a12,a13,a21,a22,a23,a31,a32,a33\n"
        "1,0.5,0.6,0.7,0.0,0.0,0.0,1.0,0.0,0.0,0.0,1.0,0.0,0.0,0.0,1.0\n"
    )
    (session_dir / "powerfit" / "fittable_structures.csv").write_text(
        "structure,structure_file,structure_id,uniprot_accessions,is_alphafold\n"
        "structure,structure.pdb,struct_1,UP00000001,true\n"
    )
    (session_dir / "structure.pdb").write_text("MODEL\nENDMDL\n")
    (session_dir / "ro-crate-metadata.json").write_text(
        json.dumps(
            {
                "@context": ["https://w3id.org/ro/crate/1.1/context"],
                "@graph": [
                    {
                        "@id": "./",
                        "@type": "Dataset",
                        "description": "An RO-Crate session directory.",
                        "name": "session",
                    },
                    {
                        "@id": "run",
                        "@type": "CreateAction",
                        "name": "run",
                        "agent": {"@id": "verhoes"},
                        "description": "Run the analysis.",
                        "endTime": "2026-08-17T09:09:00.000000+00:00",
                        "instrument": {"@id": "protein-detective@0.8.6"},
                        "object": [{"@id": "structure"}],
                        "result": [{"@id": "structure"}],
                        "startTime": "2026-08-17T09:08:00.000000+00:00",
                    },
                ],
            }
        )
    )

    con = in_memory_duckdb_connection(session_dir)
    tables = [row[0] for row in con.execute("SHOW TABLES").fetchall()]

    assert "fitted_models" not in tables


def test_refine_io_is_loaded_with_ctas(tmp_path: Path):
    session_dir = tmp_path / "session"
    refine_dir = session_dir / "refine/refine_run_001"
    refine_dir.mkdir(parents=True)
    (refine_dir / "io.csv").write_text(
        "refine_run_id,powerfit_run_id,fitted_model,refine_run_dir\n"
        "refine_run_001,run_001,powerfit/run_001/structure/model.pdb,refine/refine_run_001/run_001/structure/model.pdb\n"
    )

    statements = ddl(session_dir)
    io_statement = next(statement for statement in statements if "CREATE TABLE refinements_io" in statement[0])
    con = duckdb.connect(database=":memory:")
    con.execute(*io_statement)

    rows = con.execute("SELECT fitted_model, refine_run_dir FROM refinements_io").fetchall()

    assert rows == [
        (
            "powerfit/run_001/structure/model.pdb",
            "refine/refine_run_001/run_001/structure/model.pdb",
        )
    ]


@pytest.mark.parametrize("table", ["capri_ss", "capri_clt"])
def test_capri_tables_join_refinement_runs_and_only_load_final_stage(tmp_path: Path, table: str):
    session_dir = tmp_path / "session with spaces"
    refine_dir = session_dir / "refine"
    refine_dir.mkdir(parents=True)
    run_dirs = [f"refine/refine_run_00{i}/run_001/structure.cif/fit_1.pdb" for i in (1, 2)]
    for i, run_dir in enumerate(run_dirs, 1):
        index = refine_dir / f"refine_run_00{i}" / "io.csv"
        index.parent.mkdir()
        index.write_text(
            "refine_run_id,powerfit_run_id,fitted_model,refine_run_dir\n"
            f"refine_run_00{i},run_001,powerfit/run_001/structure.cif/fit_1.pdb,{run_dir}\n"
        )
    fixture = Path(__file__).parent / "fixtures" / "refine" / f"{table}.tsv"
    for run_dir in run_dirs:
        for step in ("2_caprieval", "7_caprieval"):
            stage_dir = session_dir / run_dir / step
            stage_dir.mkdir(parents=True)
            shutil.copyfile(fixture, stage_dir / f"{table}.tsv")
        # Postprocessed copies must not duplicate the stage results.
        analysis_dir = session_dir / run_dir / "analysis" / "7_caprieval_analysis"
        analysis_dir.mkdir(parents=True)
        shutil.copyfile(fixture, analysis_dir / f"{table}.tsv")

    # Include results from runs not recorded in refinements_io.
    orphan_dir = refine_dir / "refine_run_003" / "run_001" / "structure.cif" / "fit_1.pdb" / "7_caprieval"
    orphan_dir.mkdir(parents=True)
    shutil.copyfile(fixture, orphan_dir / f"{table}.tsv")

    with duckdb.connect(database=":memory:") as con:
        for statement, params in ddl(session_dir):
            if "CREATE TABLE refinements_io" in statement or f"CREATE TABLE refinements_{table}" in statement:
                con.execute(statement, params)
        columns = [row[0] for row in con.execute(f"DESCRIBE refinements_{table}").fetchall()]
        if table == "capri_ss":
            expected_columns = [
                "refine_run_dir",
                "model",
                "md5",
                "caprieval_rank",
                "score",
                "irmsd",
                "fnat",
                "lrmsd",
                "ilrmsd",
                "dockq",
                "rmsd",
                "cluster_id",
                "cluster_ranking",
                "modelcluster_ranking",
                "air",
                "angles",
                "bonds",
                "bsa",
                "cdih",
                "coup",
                "dani",
                "desolv",
                "dihe",
                "elec",
                "improper",
                "rdcs",
                "rg",
                "sym",
                "total",
                "vdw",
                "vean",
                "xpcs",
            ]
            rows = con.execute(
                "SELECT refine_run_dir, model, md5, caprieval_rank, score, dockq, bsa, elec, "
                "cluster_id, cluster_ranking, modelcluster_ranking FROM refinements_capri_ss "
                "JOIN refinements_io USING (refine_run_dir) WHERE caprieval_rank = 1 ORDER BY refine_run_dir"
            ).fetchall()
            expected_rows = [
                (run_dir, "../6_mdref/mdref_9.pdb", None, 1, -99.224, 1.0, 1765.330, -491.102, None, None, None)
                for run_dir in run_dirs
            ]
            expected_count = 30
        else:
            expected_columns = [
                "refine_run_dir",
                "cluster_rank",
                "cluster_id",
                "n",
                "under_eval",
                "score",
                "score_std",
                "irmsd",
                "irmsd_std",
                "fnat",
                "fnat_std",
                "lrmsd",
                "lrmsd_std",
                "dockq",
                "dockq_std",
                "ilrmsd",
                "ilrmsd_std",
                "rmsd",
                "rmsd_std",
                "air",
                "air_std",
                "bsa",
                "bsa_std",
                "desolv",
                "desolv_std",
                "elec",
                "elec_std",
                "total",
                "total_std",
                "vdw",
                "vdw_std",
                "caprieval_rank",
            ]
            rows = con.execute(
                "SELECT refine_run_dir, cluster_rank, cluster_id, n, under_eval, score, score_std, dockq, "
                "dockq_std, caprieval_rank FROM refinements_capri_clt "
                "JOIN refinements_io USING (refine_run_dir) ORDER BY refine_run_dir"
            ).fetchall()
            expected_rows = [(run_dir, None, None, 10, None, -84.827, 13.884, 0.265, 0.424, 1) for run_dir in run_dirs]
            expected_count = 3
        assert columns == expected_columns
        assert rows == expected_rows
        assert con.table(f"refinements_{table}").count("*").fetchone() == (expected_count,)


def test_capri_ddl_loads_without_refinement_io_and_skips_missing_tables(tmp_path: Path):
    assert capri_as_duckdb_ddl(tmp_path) == []
    stage_dir = tmp_path / "refine" / "refine_run_001" / "run_001" / "structure" / "fit_1.pdb" / "7_caprieval"
    stage_dir.mkdir(parents=True)
    results = stage_dir / "capri_ss.tsv"
    shutil.copyfile(Path(__file__).parent / "fixtures/refine/capri_ss.tsv", results)
    statements = capri_as_duckdb_ddl(tmp_path)
    assert len(statements) == 1
    assert "CREATE TABLE refinements_capri_ss" in statements[0][0]
    with duckdb.connect(database=":memory:") as con:
        con.execute(*statements[0])
        assert con.table("refinements_capri_ss").count("*").fetchone() == (10,)
    results.unlink()
    assert capri_as_duckdb_ddl(tmp_path) == []


def test_multiple_refinement_indexes_load_together(tmp_path: Path):
    for run_id in ("refine_run_001", "refine_run_003"):
        model_run = f"refine/{run_id}/run_001/same_structure/fit_1.pdb"
        index = tmp_path / "refine" / run_id / "io.csv"
        index.parent.mkdir(parents=True)
        index.write_text(
            "refine_run_id,powerfit_run_id,fitted_model,refine_run_dir\n"
            f"{run_id},run_001,powerfit/run_001/same_structure/fit_1.pdb,{model_run}\n"
        )
        stage = tmp_path / model_run / "7_caprieval"
        stage.mkdir(parents=True)
        (stage / "capri_ss.tsv").write_text("model\tscore\tcaprieval_rank\tcluster_id\nx.pdb\t-10\t1\t-\n")
    with duckdb.connect() as con:
        for statement, params in refinements_io_as_duckdb_ddl(tmp_path) + capri_as_duckdb_ddl(tmp_path):
            con.execute(statement, params)
        assert con.execute(
            "SELECT count(*) FROM refinements_io JOIN refinements_capri_ss USING (refine_run_dir)"
        ).fetchone() == (2,)
        assert con.execute("SELECT DISTINCT refine_run_id FROM refinements_io ORDER BY 1").fetchall() == [
            ("refine_run_001",),
            ("refine_run_003",),
        ]
