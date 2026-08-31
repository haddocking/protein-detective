import json
from pathlib import Path

from protein_detective.meta import in_memory_duckdb_connection, solutions_as_duckdb_ddl


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
