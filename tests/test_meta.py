import json
from pathlib import Path

import pytest

from protein_detective.meta import in_memory_duckdb_connection


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


def test_solutions_template_file_has_foreign_key_constraint(tmp_path: Path):
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

    with pytest.raises(Exception, match="Violates foreign key constraint"):
        con.execute("INSERT INTO solutions (template_file) VALUES ('missing.pdb')")


def test_merge_structure_files_sql_with_foreign_key_is_valid(tmp_path: Path):
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

    with pytest.raises(Exception, match="Violates foreign key constraint"):
        con.execute("INSERT INTO merge_structure_files (source, target) VALUES ('missing.cif.gz', 'other.cif.gz')")


def test_combined_stats_sql_with_uniprot_foreign_key_is_valid(tmp_path: Path):
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
