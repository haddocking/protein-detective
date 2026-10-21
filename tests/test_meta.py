import json
import shlex
import shutil
from pathlib import Path

import duckdb
import pytest
from rocrate.model.contextentity import ContextEntity
from rocrate.rocrate import ROCrate

from protein_detective.meta import (
    ddl,
    execute_ddl_statements,
    in_memory_duckdb_connection,
    powerfit_runs_as_duckdb_ddl,
    refinement_tables,
    refinements_capri_clt_as_duckdb_ddl,
    refinements_capri_ss_as_duckdb_ddl,
    refinements_io_as_duckdb_ddl,
    refinements_runs_as_duckdb_ddl,
    solutions_as_duckdb_ddl,
    stats_csv_as_duckdb_ddl,
    structure_files_as_duckdb_ddl,
)
from tests.helpers import write_reconstruction_index


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
                        "@id": "ro-crate-metadata.json",
                        "@type": "CreativeWork",
                        "about": {"@id": "./"},
                        "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
                    },
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
                        "@id": "ro-crate-metadata.json",
                        "@type": "CreativeWork",
                        "about": {"@id": "./"},
                        "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
                    },
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
                        "@id": "ro-crate-metadata.json",
                        "@type": "CreativeWork",
                        "about": {"@id": "./"},
                        "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
                    },
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
                        "@id": "ro-crate-metadata.json",
                        "@type": "CreativeWork",
                        "about": {"@id": "./"},
                        "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
                    },
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
                        "@id": "ro-crate-metadata.json",
                        "@type": "CreativeWork",
                        "about": {"@id": "./"},
                        "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
                    },
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
                        "@id": "ro-crate-metadata.json",
                        "@type": "CreativeWork",
                        "about": {"@id": "./"},
                        "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
                    },
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


def copy_capri_tables(directory: Path, fixtures: dict[str, Path]):
    directory.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(fixtures["models"], directory / "capri_ss.tsv")
    shutil.copyfile(fixtures["clusters"], directory / "capri_clt.tsv")


@pytest.fixture
def capri_tables(tmp_path: Path, clustered_refinement_results_paths: dict[str, Path]):
    session_dir = tmp_path / "session with spaces"
    refine_dir = session_dir / "refine"
    refine_dir.mkdir(parents=True, exist_ok=True)
    run_dirs = [f"refine/refine_run_00{i}/run_001/structure.cif/fit_1.pdb" for i in (1, 2)]
    for i, run_dir in enumerate(run_dirs, 1):
        index = refine_dir / f"refine_run_00{i}" / "io.csv"
        index.parent.mkdir()
        index.write_text(
            "refine_run_id,powerfit_run_id,fitted_model,refine_run_dir\n"
            f"refine_run_00{i},run_001,powerfit/run_001/structure.cif/fit_1.pdb,{run_dir}\n"
        )
    for run_dir in run_dirs:
        refinement = session_dir / run_dir / "refinement"
        copy_capri_tables(refinement / "2_caprieval", clustered_refinement_results_paths)
        copy_capri_tables(refinement / "8_caprieval", clustered_refinement_results_paths)
        write_reconstruction_index(refinement)
        # Postprocessed copies must not duplicate the stage results.
        copy_capri_tables(refinement / "analysis/8_caprieval_analysis", clustered_refinement_results_paths)

    # Include results from runs not recorded in refinements_io.
    orphan_dir = refine_dir / "refine_run_003/run_001/structure.cif/fit_1.pdb/refinement/8_caprieval"
    copy_capri_tables(orphan_dir, clustered_refinement_results_paths)
    write_reconstruction_index(orphan_dir.parent)

    with duckdb.connect(database=":memory:") as con:
        execute_ddl_statements(con, refinements_io_as_duckdb_ddl(session_dir))
        execute_ddl_statements(con, refinements_capri_ss_as_duckdb_ddl(session_dir))
        execute_ddl_statements(con, refinements_capri_clt_as_duckdb_ddl(session_dir))
        yield con, run_dirs


def test_capri_ss_joins_refinement_runs_and_only_loads_final_stage(
    capri_tables: tuple[duckdb.DuckDBPyConnection, list[str]],
):
    con, run_dirs = capri_tables
    columns = [row[0] for row in con.execute("DESCRIBE refinements_capri_ss").fetchall()]
    expected_columns = [
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
        (run_dir, "../6_mdref/mdref_8.pdb", None, 1, -123.367, 1.0, 1367.51, -638.662, 2, 1, 1) for run_dir in run_dirs
    ]
    expected_count = 36
    expected_columns += [
        "filename",
        "refine_run_dir",
        "unrefined_complex",
        "unfitted_structure",
        "powerfit_run_id",
        "refine_run_id",
    ]
    expected_columns += ["refined_complex", "refined_fitted_structure", "refined_known_structure"]
    assert columns == expected_columns
    assert rows == expected_rows
    assert con.table("refinements_capri_ss").count("*").fetchone() == (expected_count,)


def test_capri_clt_joins_refinement_runs_and_only_loads_final_stage(
    capri_tables: tuple[duckdb.DuckDBPyConnection, list[str]],
):
    con, run_dirs = capri_tables
    columns = [row[0] for row in con.execute("DESCRIBE refinements_capri_clt").fetchall()]
    expected_columns = [
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
        "JOIN refinements_io USING (refine_run_dir) ORDER BY refine_run_dir, cluster_rank"
    ).fetchall()
    expected_rows = [
        (run_dir, rank, cluster_id, 3, True, score, score_std, dockq, dockq_std, rank)
        for run_dir in run_dirs
        for rank, cluster_id, score, score_std, dockq, dockq_std in (
            (1, 2, -122.586, 0.989, 0.924, 0.057),
            (2, 1, -73.422, 2.078, 0.017, 0.0),
            (3, 3, -63.730, 4.865, 0.004, 0.0),
            (4, 4, -53.309, 9.861, 0.025, 0.0),
        )
    ]
    expected_count = 12
    expected_columns += [
        "refine_run_dir",
        "unrefined_complex",
        "unfitted_structure",
        "powerfit_run_id",
        "refine_run_id",
    ]
    assert columns == expected_columns
    assert rows == expected_rows
    assert con.table("refinements_capri_clt").count("*").fetchone() == (expected_count,)


def test_capri_ddl_loads_without_refinement_io_and_skips_missing_tables(
    tmp_path: Path, clustered_refinement_results_paths: dict[str, Path]
):
    assert refinements_capri_ss_as_duckdb_ddl(tmp_path) == []
    stage_dir = (
        tmp_path / "refine" / "refine_run_001" / "run_001" / "structure" / "fit_1.pdb" / "refinement" / "8_caprieval"
    )
    stage_dir.mkdir(parents=True)
    results = stage_dir / "capri_ss.tsv"
    shutil.copyfile(clustered_refinement_results_paths["models"], results)
    write_reconstruction_index(stage_dir.parent)
    statements = refinements_capri_ss_as_duckdb_ddl(tmp_path)
    assert len(statements) == 1
    assert "CREATE TABLE refinements_capri_ss" in statements[0][0]
    with duckdb.connect(database=":memory:") as con:
        con.execute(*statements[0])
        assert con.table("refinements_capri_ss").count("*").fetchone() == (12,)
    results.unlink()
    assert refinements_capri_ss_as_duckdb_ddl(tmp_path) == []


@pytest.fixture
def multiple_refinement_indexes(tmp_path: Path):
    for run_id in ("refine_run_001", "refine_run_003"):
        refinement_run = f"refine/{run_id}/run_001/same_structure/fit_1.pdb"
        index = tmp_path / "refine" / run_id / "io.csv"
        index.parent.mkdir(parents=True)
        index.write_text(
            "refine_run_id,powerfit_run_id,fitted_model,refine_run_dir\n"
            f"{run_id},run_001,powerfit/run_001/same_structure/fit_1.pdb,{refinement_run}\n"
        )
        stage = tmp_path / refinement_run / "refinement" / "8_caprieval"
        stage.mkdir(parents=True)
        (stage / "capri_ss.tsv").write_text("model\tscore\tcaprieval_rank\tcluster_id\nx.pdb\t-10\t1\t-\n")
        write_reconstruction_index(stage.parent)
    with duckdb.connect() as con:
        for statement, params in refinements_io_as_duckdb_ddl(tmp_path) + refinements_capri_ss_as_duckdb_ddl(tmp_path):
            con.execute(statement, params)
        yield con


def test_multiple_refinement_indexes_load_together(multiple_refinement_indexes: duckdb.DuckDBPyConnection):
    con = multiple_refinement_indexes
    assert con.execute(
        "SELECT count(*) FROM refinements_io JOIN refinements_capri_ss USING (refine_run_dir)"
    ).fetchone() == (2,)
    assert con.execute("SELECT DISTINCT refine_run_id FROM refinements_io ORDER BY 1").fetchall() == [
        ("refine_run_001",),
        ("refine_run_003",),
    ]


@pytest.mark.parametrize("session_argument", ["absolute", "relative", "current"])
def test_generated_path_columns_are_session_relative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, session_argument: str
):
    # A repeated session path inside the artifact path must not be removed.
    session = tmp_path / "session with spaces"
    repeated_directory = Path(*session.parts[1:])
    run_dir = Path("refine/refine_run_001/run_001/structure/fit_1.pdb")
    stage = session / run_dir / "refinement/8_caprieval"
    stage.mkdir(parents=True)
    (stage / "capri_ss.tsv").write_text("model\tscore\n../6_mdref/mdref_1.pdb\t-10\n")
    baseline = session / run_dir / "baseline/2_caprieval"
    baseline.mkdir(parents=True)
    (baseline / "capri_ss.tsv").write_text("model\tscore\n../1_emscoring/emscoring_1.pdb\t-5\n")
    (stage / "capri_clt.tsv").write_text("cluster_id\tscore\n1\t-10\n")
    write_reconstruction_index(stage.parent)
    artifact = repeated_directory / "test.pdb"
    (session / artifact).parent.mkdir(parents=True)
    (session / artifact).write_text("END\n")

    monkeypatch.chdir(tmp_path if session_argument != "current" else session)
    session_dir = {"absolute": session, "relative": Path(session.name), "current": Path()}[session_argument]

    with duckdb.connect() as con:
        execute_ddl_statements(con, structure_files_as_duckdb_ddl(session_dir) + refinement_tables(session_dir))
        assert con.execute("SELECT file, parent_dir, filename FROM structure_files").fetchall() == [
            (str(artifact), str(artifact.parent), artifact.name)
        ]
        assert con.execute(
            "SELECT filename, refine_run_dir, refined_complex, model FROM refinements_capri_ss"
        ).fetchall() == [
            (
                str(run_dir / "refinement/8_caprieval/capri_ss.tsv"),
                str(run_dir),
                str(run_dir / "refinement/6_mdref/mdref_1.pdb.gz"),
                "../6_mdref/mdref_1.pdb",
            )
        ]
        assert con.execute("SELECT refine_run_dir FROM refinements_capri_clt").fetchall() == [(str(run_dir),)]
        assert con.execute("SELECT refine_run_dir, model FROM refinements_baseline").fetchall() == [
            (str(run_dir), "../1_emscoring/emscoring_1.pdb")
        ]


@pytest.mark.parametrize("options_first", [False, True])
def test_refinement_partners_come_from_io_and_options_from_crate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, options_first: bool
):
    session = tmp_path / "session with spaces"
    run_dir = session / "refine/example"
    run_dir.mkdir(parents=True)
    index = run_dir / "io.csv"
    index.write_text(
        "refine_run_id,original_known_structure,processed_known_structure\n"
        "example,refine/example/known partner.cif.gz,refine/example/known_structure.pdb\n"
    )
    options = "--refine-run-id example"
    positionals = "'session with spaces' 'missing external partner.pdb'"
    arguments = f"{options} {positionals}" if options_first else f"{positionals} {options}"
    crate = ROCrate()
    result = crate.add_file(index, dest_path="refine/example/io.csv")
    crate.add(
        ContextEntity(
            crate,
            f"protein-detective refine run {arguments}",
            properties={"@type": "CreateAction", "result": [result]},
        )
    )
    crate.write(session)
    crate_bytes = (session / "ro-crate-metadata.json").read_bytes()
    monkeypatch.chdir(session)
    with duckdb.connect() as con:
        execute_ddl_statements(con, refinements_runs_as_duckdb_ddl(Path()))
        assert con.execute(
            "SELECT original_known_structure, processed_known_structure, options FROM refinements_runs"
        ).fetchall() == [("refine/example/known partner.cif.gz", "refine/example/known_structure.pdb", options)]
    assert (session / "ro-crate-metadata.json").read_bytes() == crate_bytes


def test_refinement_without_io_has_no_run_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    session = tmp_path / "session"
    session.mkdir()
    external = tmp_path / "external.pdb"
    external.write_text("END\n")
    crate = ROCrate()
    result = crate.add_file(external, dest_path="refine/example/known_structure.pdb")
    crate.add(
        ContextEntity(
            crate,
            "protein-detective refine run ../session ../external.pdb --refine-run-id example",
            properties={"@type": "CreateAction", "result": [result]},
        )
    )
    crate.write(session)
    monkeypatch.chdir(session)
    assert refinements_runs_as_duckdb_ddl(Path()) == []


def test_single_chain_stats_is_loaded_with_paths_and_rejected_rows(tmp_path: Path):
    (tmp_path / "single_chain_stats.csv").write_text(
        "input_file,chain2keep,output_chain,passed,discard_reason,output_file\n"
        "uniprots_verified/input.cif.gz,C,A,True,,single_chain/renamed.cif.gz\n"
        "uniprots_verified/input.cif.gz,D,A,False,Missing chain,\n"
    )
    with duckdb.connect() as con:
        execute_ddl_statements(con, stats_csv_as_duckdb_ddl(tmp_path))
        assert con.execute("SELECT * FROM single_chain_stats ORDER BY chain2keep").fetchall() == [
            ("uniprots_verified/input.cif.gz", "C", "A", True, None, "single_chain/renamed.cif.gz"),
            ("uniprots_verified/input.cif.gz", "D", "A", False, "Missing chain", None),
        ]


def test_missing_single_chain_stats_is_optional(tmp_path: Path):
    assert stats_csv_as_duckdb_ddl(tmp_path) == []


@pytest.mark.parametrize("executable", ["protein-detective", "'/old path/bin/protein-detective'"])
@pytest.mark.parametrize("target_count", [0, 1, 2])
@pytest.mark.parametrize(
    "arguments",
    [
        "../target.mrc 3.7 . --angle 10",
        "--angle=10 ../target.mrc --no-resampling 3.7 .",
        "--unknown ../target.mrc 3.7 .",
        "'../target with spaces.mrc' 3.7 . --angle 10",
    ],
)
def test_powerfit_runs_use_explicit_target_provenance_without_solutions(
    tmp_path: Path, target_count: int, arguments: str, executable: str
):
    session = tmp_path / "session"
    run_dir = session / "powerfit/example"
    run_dir.mkdir(parents=True)
    (session / "powerfit/interrupted").mkdir()
    target = tmp_path / "target.mrc"
    target.write_text("density")
    crate = ROCrate()
    result = crate.add_dataset(run_dir, dest_path="powerfit/example")
    objects = [
        crate.add_file(
            target,
            dest_path=f"powerfit/example/target{i}.mrc",
            properties={
                "description": f"Density map used for fitting. Copied from {target.resolve()}."
                if i == 0
                else "Density map used for fitting."
            },
        )
        for i in range(target_count)
    ]
    objects.append(
        crate.add_file(
            target, dest_path="powerfit/example/lcc.mrc", properties={"description": "Local cross correlation."}
        )
    )
    command = executable + " powerfit run " + arguments
    crate.add(
        ContextEntity(crate, command, properties={"@type": "CreateAction", "object": objects, "result": [result]})
    )
    crate.write(session)
    with duckdb.connect() as con:
        execute_ddl_statements(con, powerfit_runs_as_duckdb_ddl(session))
        assert con.execute("SELECT * FROM powerfit_runs ORDER BY powerfit_run_id").fetchall() == [
            (
                "example",
                "powerfit/example",
                "powerfit/example/target0.mrc" if target_count == 1 else None,
                shlex.join(shlex.split(arguments)),
                command,
            ),
            ("interrupted", "powerfit/interrupted", None, None, None),
        ]


def test_powerfit_runs_absent_stage_and_unrecorded_directory(tmp_path: Path):
    assert powerfit_runs_as_duckdb_ddl(tmp_path) == []
    (tmp_path / "powerfit/incomplete").mkdir(parents=True)
    with duckdb.connect() as con:
        execute_ddl_statements(con, powerfit_runs_as_duckdb_ddl(tmp_path))
        assert con.execute("SELECT * FROM powerfit_runs").fetchall() == [
            ("incomplete", "powerfit/incomplete", None, None, None)
        ]
