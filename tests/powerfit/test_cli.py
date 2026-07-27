import csv
import json
from pathlib import Path
from textwrap import dedent

import pytest

from tests.helpers import assert_crate, cli, fake_run_retrieve, fake_structure_file, read_csv


def test_commands_help(capsys: pytest.CaptureFixture[str]):
    argv = ["powerfit", "commands", "--help"]
    cli(argv)

    expected = "Generate PowerFit commands for structure files in the session directory."
    captured = capsys.readouterr()
    assert expected in captured.out


def test_commands_defaults(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    # Fake retrieve + filter
    session_dir = fake_run_retrieve(tmp_path)
    combined_filter_output = session_dir / "combined_output"
    combined_filter_output.mkdir()
    (session_dir / "combined_output" / "2y29_updated.cif.gz").symlink_to(
        session_dir / "downloads" / "pdbe" / "2y29_updated.cif.gz"
    )
    (session_dir / "combined_output" / "AF-A0A0C5B5G6-F1-model_v6.cif.gz").symlink_to(
        session_dir / "downloads" / "alphafold" / "AF-A0A0C5B5G6-F1-model_v6.cif.gz"
    )
    # Fake target
    target = tmp_path / "target.mrc"
    target.write_text("fake density map")

    argv = [
        "powerfit",
        "commands",
        str(target),
        "3.0",
        str(session_dir),
        "--cpu",
    ]
    cli(argv)

    stdout = capsys.readouterr().out
    assert "# Run the commands below in your own way" in stdout
    assert (
        f"powerfit {session_dir}/powerfit/run_001/target.mrc 3.0 {session_dir}/combined_output/AF-A0A0C5B5G6-F1-model_v6.cif.gz --resampling-rate 2.0 --num 0 --nproc 1 --directory {session_dir}/powerfit/run_001/AF-A0A0C5B5G6-F1-model_v6.cif.gz --delimiter , --angle 10.0"
        in stdout
    )
    assert (
        f"powerfit {session_dir}/powerfit/run_001/target.mrc 3.0 {session_dir}/combined_output/2y29_updated.cif.gz --resampling-rate 2.0 --num 0 --nproc 1 --directory {session_dir}/powerfit/run_001/2y29_updated.cif.gz --delimiter , --angle 10.0"
        in stdout
    )


def fake_solutions(session_dir: Path, powerfit_run_id: str) -> list[Path]:
    # Create structures
    structures_dir = session_dir / "combined_output"
    structures_dir.mkdir()
    fake_structure_file("1abc", structures_dir / "1abc.cif.gz", uniprot_accession="P67890")
    fake_structure_file("2abc", structures_dir / "2abc.cif.gz", uniprot_accession="P42424")
    fake_structure_file("3abc", structures_dir / "3abc.cif.gz", uniprot_accession="P12345")

    powerfit_run_dir = session_dir / "powerfit" / powerfit_run_id
    # Write fake solutions
    sr1 = powerfit_run_dir / "1abc.cif.gz" / "solutions.out"
    sr1.parent.mkdir(parents=True, exist_ok=True)
    solutions1 = dedent("""\
        rank,cc,Fish-z,rel-z,x,y,z,a11,a12,a13,a21,a22,a23,a31,a32,a33
        1,0.399,0.423,13.661,168.850,199.550,230.250,0.243,0.912,0.331,-0.331,-0.243,0.912,0.912,-0.331,0.243
        2,0.398,0.422,13.638,245.600,162.710,208.760,0.084,0.795,0.601,0.601,0.441,-0.667,-0.795,0.417,-0.441
        3,0.398,0.421,13.627,224.110,168.850,184.200,0.182,0.597,0.781,-0.353,0.781,-0.515,-0.918,-0.182,0.353
        """)
    sr1.write_text(solutions1)

    sr2 = powerfit_run_dir / "2abc.cif.gz" / "solutions.out"
    sr2.parent.mkdir(parents=True, exist_ok=True)
    solutions2 = dedent("""\
        rank,cc,Fish-z,rel-z,x,y,z,a11,a12,a13,a21,a22,a23,a31,a32,a33
        1,0.442,0.475,15.398,227.180,153.500,193.410,-0.517,0.216,0.828,0.557,-0.649,0.517,0.649,0.729,0.216
        2,0.442,0.475,15.392,236.390,159.640,251.740,0.182,0.597,-0.781,0.353,-0.781,-0.515,-0.918,-0.182,-0.353
        3,0.437,0.468,15.176,196.480,217.970,193.410,0.803,0.388,0.452,-0.388,-0.235,0.891,0.452,-0.891,-0.038
        """)
    sr2.write_text(solutions2)

    sr3 = powerfit_run_dir / "3abc.cif.gz" / "solutions.out"
    sr3.parent.mkdir(parents=True, exist_ok=True)
    solutions3 = dedent("""\
        rank,cc,Fish-z,rel-z,x,y,z,a11,a12,a13,a21,a22,a23,a31,a32,a33
        1,0.499,0.548,17.918,224.110,260.950,168.850,0.649,-0.557,-0.517,0.729,0.649,0.216,0.216,-0.517,0.828
        2,0.487,0.532,17.374,141.220,138.150,159.640,0.818,0.568,0.087,-0.568,0.776,0.273,0.087,-0.273,0.958
        3,0.482,0.525,17.166,178.060,199.550,193.410,0.557,-0.517,0.649,-0.517,-0.828,-0.216,0.649,-0.216,-0.729
        """)
    sr3.write_text(solutions3)

    return [sr1, sr2, sr3]


def assert_solutions(output: str, expected: list[dict[str, str]]) -> None:
    solutions = list(csv.DictReader(output.splitlines()))
    trimmed_keys = {"powerfit_run_id", "structure", "rank", "cc", "uniprot_accessions", "pdb_id", "template_file"}
    trimmed_solutions = [{k: v for k, v in s.items() if k in trimmed_keys} for s in solutions]
    assert trimmed_solutions == expected


class TestHandlerPowerfitReport:
    def test_defaults(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        session_dir = tmp_path
        powerfit_run_id = "run_001"
        fake_solutions(session_dir, powerfit_run_id)

        argv = [
            "powerfit",
            "report",
            str(session_dir),
        ]
        cli(argv)

        stdout = capsys.readouterr().out
        expected = [
            {
                "powerfit_run_id": "run_001",
                "structure": "3abc.cif.gz",
                "rank": "1",
                "cc": "0.499",
                "template_file": str(session_dir / "combined_output" / "3abc.cif.gz"),
                "uniprot_accessions": "P12345",
                "pdb_id": "3abc",
            },
            {
                "powerfit_run_id": "run_001",
                "structure": "2abc.cif.gz",
                "rank": "1",
                "cc": "0.442",
                "template_file": str(session_dir / "combined_output" / "2abc.cif.gz"),
                "uniprot_accessions": "P42424",
                "pdb_id": "2abc",
            },
            {
                "powerfit_run_id": "run_001",
                "structure": "1abc.cif.gz",
                "rank": "1",
                "cc": "0.399",
                "template_file": str(session_dir / "combined_output" / "1abc.cif.gz"),
                "uniprot_accessions": "P67890",
                "pdb_id": "1abc",
            },
        ]
        assert_solutions(stdout, expected)

    def test_top2(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        session_dir = tmp_path
        powerfit_run_id = "run_001"
        fake_solutions(session_dir, powerfit_run_id)

        argv = [
            "powerfit",
            "report",
            str(session_dir),
            "--top",
            "2",
        ]
        cli(argv)

        stdout = capsys.readouterr().out
        expected = [
            {
                "cc": "0.499",
                "pdb_id": "3abc",
                "powerfit_run_id": "run_001",
                "rank": "1",
                "structure": "3abc.cif.gz",
                "template_file": str(session_dir / "combined_output" / "3abc.cif.gz"),
                "uniprot_accessions": "P12345",
            },
            {
                "cc": "0.487",
                "pdb_id": "3abc",
                "powerfit_run_id": "run_001",
                "rank": "2",
                "structure": "3abc.cif.gz",
                "template_file": str(session_dir / "combined_output" / "3abc.cif.gz"),
                "uniprot_accessions": "P12345",
            },
            {
                "cc": "0.442",
                "pdb_id": "2abc",
                "powerfit_run_id": "run_001",
                "rank": "1",
                "structure": "2abc.cif.gz",
                "template_file": str(session_dir / "combined_output" / "2abc.cif.gz"),
                "uniprot_accessions": "P42424",
            },
            {
                "cc": "0.442",
                "pdb_id": "2abc",
                "powerfit_run_id": "run_001",
                "rank": "2",
                "structure": "2abc.cif.gz",
                "template_file": str(session_dir / "combined_output" / "2abc.cif.gz"),
                "uniprot_accessions": "P42424",
            },
            {
                "cc": "0.399",
                "pdb_id": "1abc",
                "powerfit_run_id": "run_001",
                "rank": "1",
                "structure": "1abc.cif.gz",
                "template_file": str(session_dir / "combined_output" / "1abc.cif.gz"),
                "uniprot_accessions": "P67890",
            },
            {
                "cc": "0.398",
                "pdb_id": "1abc",
                "powerfit_run_id": "run_001",
                "rank": "2",
                "structure": "1abc.cif.gz",
                "template_file": str(session_dir / "combined_output" / "1abc.cif.gz"),
                "uniprot_accessions": "P67890",
            },
        ]
        assert_solutions(stdout, expected)

    def test_no_group_by_structure(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        session_dir = tmp_path
        powerfit_run_id = "run_001"
        fake_solutions(session_dir, powerfit_run_id)

        argv = [
            "powerfit",
            "report",
            str(session_dir),
            "--no-group-by-structure",
            "--top",
            "2",
        ]
        cli(argv)

        stdout = capsys.readouterr().out
        expected = [
            {
                "cc": "0.499",
                "pdb_id": "3abc",
                "powerfit_run_id": "run_001",
                "rank": "1",
                "structure": "3abc.cif.gz",
                "template_file": str(session_dir / "combined_output" / "3abc.cif.gz"),
                "uniprot_accessions": "P12345",
            },
            {
                "cc": "0.487",
                "pdb_id": "3abc",
                "powerfit_run_id": "run_001",
                "rank": "2",
                "structure": "3abc.cif.gz",
                "template_file": str(session_dir / "combined_output" / "3abc.cif.gz"),
                "uniprot_accessions": "P12345",
            },
        ]
        assert_solutions(stdout, expected)


def test_run(tmp_path: Path, ribosome_map: Path, cif_2y29: Path, capsys: pytest.CaptureFixture[str]):
    session_dir = tmp_path / "session"
    target = ribosome_map
    input_structure = cif_2y29
    imported_structures_dir = session_dir / "imported_structures"
    imported_structures_dir.mkdir(parents=True, exist_ok=True)
    imported_structure = imported_structures_dir / input_structure.name
    imported_structure.symlink_to(input_structure)

    # Using very crude parameters to make test fast and have solutions which are bad, but useful.
    argv = [
        "powerfit",
        "run",
        str(target),
        "50",
        str(session_dir),
        "--cpu",
        "--angle",
        "180",
        # Using sequential so code coverage is tracked and its faster because Dask cluster does not need to be started.
        "--scheduler-address",
        "sequential",
    ]
    cli(argv)

    powerfit_root_dir = session_dir / "powerfit"
    assert powerfit_root_dir.exists()
    powerfit_run_dir = powerfit_root_dir / "run_001"
    fittable_csv = powerfit_root_dir / "fittable_structures.csv"
    solutions_out = powerfit_run_dir / imported_structure.name / "solutions.out"

    assert set(powerfit_root_dir.glob("**")) == {
        powerfit_root_dir,
        fittable_csv,
        powerfit_run_dir,
        powerfit_run_dir / target.name,
        powerfit_run_dir / imported_structure.name,
        solutions_out,
    }

    stderr = capsys.readouterr().err
    assert "PowerFit run completed with ID" in stderr

    assert_solutions(
        solutions_out.read_text(),
        [
            {
                "cc": "1.000",
                "rank": "1",
            },
            {
                "cc": "1.000",
                "rank": "2",
            },
            {
                "cc": "1.000",
                "rank": "3",
            },
            {
                "cc": "1.000",
                "rank": "4",
            },
            {
                "cc": "1.000",
                "rank": "5",
            },
            {
                "cc": "1.000",
                "rank": "6",
            },
            {
                "cc": "1.000",
                "rank": "7",
            },
            {
                "cc": "0.999",
                "rank": "8",
            },
            {
                "cc": "0.750",
                "rank": "9",
            },
        ],
    )

    assert read_csv(fittable_csv) == [
        {
            "pdb_id": "2Y29",
            "structure": "2y29_updated.cif.gz",
            "structure_file": "imported_structures/2y29_updated.cif.gz",
            "uniprot_accessions": "P05067",
        },
    ]

    assert_crate(
        session_dir,
        action_id=f"protein-detective powerfit run {target} 50 {session_dir} --cpu --angle 180 --scheduler-address sequential",
        input_ids={str(target), str(imported_structure)},
        output_ids={str(solutions_out)},
    )


def test_fit_models(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    session_dir = tmp_path / "session"
    session_dir.mkdir(parents=True, exist_ok=True)
    powerfit_run_id = "run_001"
    fake_solutions(session_dir, powerfit_run_id)

    fitted_csv = tmp_path / "fitted_models.csv"

    argv = ["powerfit", "fit-models", str(session_dir), "--output", str(fitted_csv)]
    cli(argv)

    fitted_model1 = session_dir / "powerfit" / powerfit_run_id / "3abc.cif.gz" / "fit_1.pdb"
    assert fitted_model1.exists()
    fitted_model2 = session_dir / "powerfit" / powerfit_run_id / "2abc.cif.gz" / "fit_1.pdb"
    assert fitted_model2.exists()
    fitted_model3 = session_dir / "powerfit" / powerfit_run_id / "1abc.cif.gz" / "fit_1.pdb"
    assert fitted_model3.exists()

    unfitted_models = [
        session_dir / "combined_output" / "3abc.cif.gz",
        session_dir / "combined_output" / "2abc.cif.gz",
        session_dir / "combined_output" / "1abc.cif.gz",
    ]

    assert read_csv(fitted_csv) == [
        {
            "fitted_model_file": str(fitted_model1),
            "powerfit_run_id": "run_001",
            "rank": "1",
            "structure": "3abc.cif.gz",
            "unfitted_model_file": str(unfitted_models[0]),
        },
        {
            "fitted_model_file": str(fitted_model2),
            "powerfit_run_id": "run_001",
            "rank": "1",
            "structure": "2abc.cif.gz",
            "unfitted_model_file": str(unfitted_models[1]),
        },
        {
            "fitted_model_file": str(fitted_model3),
            "powerfit_run_id": "run_001",
            "rank": "1",
            "structure": "1abc.cif.gz",
            "unfitted_model_file": str(unfitted_models[2]),
        },
    ]

    assert_crate(
        session_dir,
        action_id=f"protein-detective powerfit fit-models {session_dir} --output {fitted_csv}",
        input_ids={str(unfitted_models[0]), str(unfitted_models[1]), str(unfitted_models[2])},
        output_ids={str(fitted_model1), str(fitted_model2), str(fitted_model3)},
    )


def test_list_runs(tmp_path: Path):
    session_dir = tmp_path / "session"
    session_dir.mkdir(parents=True, exist_ok=True)
    powerfit_root_dir = session_dir / "powerfit"
    powerfit_root_dir.mkdir(parents=True, exist_ok=True)
    (powerfit_root_dir / "run_001").mkdir()
    (powerfit_root_dir / "run_001" / "targetA.mrc").write_text("fake target")
    (powerfit_root_dir / "run_002").mkdir()
    (powerfit_root_dir / "run_002" / "targetB.mrc").write_text("fake target")
    # Run options are stored in the RO-Crate metadata, so we need to create a fake RO-Crate metadata file for this test.
    (session_dir / "ro-crate-metadata.json").write_text(
        json.dumps(
            {
                "@context": ["https://w3id.org/ro/crate/1.1/context", "https://w3id.org/ro/terms/workflow-run/context"],
                "@graph": [
                    {
                        "@id": "./",
                        "@type": "Dataset",
                        "conformsTo": {"@id": "https://w3id.org/ro/wfrun/process/0.5"},
                        "datePublished": "2026-07-27T07:25:04.654513+00:00",
                        "description": "An RO-Crate recording the files and directories that were used as input or output by protein-detective.",
                        "hasPart": [
                            {"@id": "combined_output/"},
                            {"@id": "powerfit/run_001/ribosome-KsgA.map"},
                            {"@id": "powerfit/run_002/ribosome-KsgA.map"},
                            {"@id": "powerfit/fittable_structures.csv"},
                            {"@id": "powerfit/run_001/"},
                            {"@id": "powerfit/run_002/"},
                        ],
                        "license": "CC-BY-4.0",
                        "name": "Files used by protein-detective",
                    },
                    {
                        "@id": "ro-crate-metadata.json",
                        "@type": "CreativeWork",
                        "about": {"@id": "./"},
                        "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
                    },
                    {
                        "@id": "combined_output/",
                        "@type": "Dataset",
                        "description": "Directory where the combined filtered structure files are written to.",
                        "name": "combined_output",
                    },
                    {
                        "@id": "https://w3id.org/ro/wfrun/process/0.5",
                        "@type": "CreativeWork",
                        "name": "Process Run Crate",
                        "version": "0.5",
                    },
                    {
                        "@id": "protein-detective@0.8.0",
                        "@type": "SoftwareApplication",
                        "description": "Detect proteins in EM density map",
                        "name": "protein-detective",
                        "version": "0.8.0",
                    },
                    {"@id": "verhoes", "@type": "Person", "name": "verhoes"},
                    {
                        "@id": "powerfit/run_001/ribosome-KsgA.map",
                        "@type": "File",
                        "contentSize": 8389632,
                        "description": "Density map used for fitting.",
                        "encodingFormat": "application/octet-stream",
                        "name": "powerfit/run_001/ribosome-KsgA.map",
                    },
                    {
                        "@id": "powerfit/run_002/ribosome-KsgA.map",
                        "@type": "File",
                        "contentSize": 8389632,
                        "description": "Density map used for fitting.",
                        "encodingFormat": "application/octet-stream",
                        "name": "powerfit/run_002/ribosome-KsgA.map",
                    },
                    {
                        "@id": "powerfit/fittable_structures.csv",
                        "@type": "File",
                        "contentSize": 10780,
                        "description": "CSV file containing the fittable structures with PDB IDs and UniProt accessions.",
                        "encodingFormat": "text/csv",
                        "name": "powerfit/fittable_structures.csv",
                    },
                    {
                        "@id": "powerfit/run_001/",
                        "@type": "Dataset",
                        "description": "Directory where the PowerFit results were stored.",
                        "name": "powerfit/run_001",
                    },
                    {
                        "@id": "powerfit/run_002/",
                        "@type": "Dataset",
                        "description": "Directory where the PowerFit results were stored.",
                        "name": "powerfit/run_002",
                    },
                    {
                        "@id": "protein-detective powerfit run --workers-per-gpu 2 --angle 40 --powerfit-run-id run_001 ../powerfit-tutorial/ribosome-KsgA.map 13 ./mysession",
                        "@type": "CreateAction",
                        "agent": {"@id": "verhoes"},
                        "endTime": "2026-07-27T07:25:04.654513+00:00",
                        "instrument": {"@id": "protein-detective@0.8.0"},
                        "name": "protein-detective powerfit run --workers-per-gpu 2 --angle 40 --powerfit-run-id run_001 ../powerfit-tutorial/ribosome-KsgA.map 13 ./mysession",
                        "object": [{"@id": "powerfit/run_001/ribosome-KsgA.map"}, {"@id": "combined_output/"}],
                        "result": [{"@id": "powerfit/fittable_structures.csv"}, {"@id": "powerfit/run_001/"}],
                        "startTime": "2026-07-27T07:24:36.897924+00:00",
                    },
                    {
                        "@id": "protein-detective powerfit run --powerfit-run-id run_002 ../powerfit-tutorial/ribosome-KsgA.map 13 ./mysession",
                        "@type": "CreateAction",
                        "agent": {"@id": "verhoes"},
                        "endTime": "2026-07-27T07:25:04.654513+00:00",
                        "instrument": {"@id": "protein-detective@0.8.0"},
                        "name": "protein-detective powerfit run --powerfit-run-id run_002 ../powerfit-tutorial/ribosome-KsgA.map 13 ./mysession",
                        "object": [{"@id": "powerfit/run_002/ribosome-KsgA.map"}, {"@id": "combined_output/"}],
                        "result": [{"@id": "powerfit/fittable_structures.csv"}, {"@id": "powerfit/run_002/"}],
                        "startTime": "2026-07-27T07:24:36.897924+00:00",
                    },
                ],
            }
        )
    )

    runs_csv = powerfit_root_dir / "runs.csv"
    argv = ["powerfit", "list-runs", str(session_dir), "--output", str(runs_csv)]
    cli(argv)

    assert read_csv(runs_csv) == [
        {
            "density_map": str(powerfit_root_dir / "run_001" / "targetA.mrc"),
            "run_dir": str(powerfit_root_dir / "run_001"),
            "powerfit_run_id": "run_001",
            "options": "--workers-per-gpu 2 --angle 40 --powerfit-run-id run_001 ../powerfit-tutorial/ribosome-KsgA.map 13 ./mysession",
        },
        {
            "density_map": str(powerfit_root_dir / "run_002" / "targetB.mrc"),
            "run_dir": str(powerfit_root_dir / "run_002"),
            "powerfit_run_id": "run_002",
            "options": "--powerfit-run-id run_002 ../powerfit-tutorial/ribosome-KsgA.map 13 ./mysession",
        },
    ]


def test_list_lcc(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    fake_solutions(tmp_path, "run_001")

    argv = ["powerfit", "list-lcc", str(tmp_path), "--output", str(tmp_path / "lcc.csv")]
    cli(argv)

    stderr = capsys.readouterr().err
    assert "No lcc.mrc files found" in stderr

    assert not (tmp_path / "lcc.csv").exists()
