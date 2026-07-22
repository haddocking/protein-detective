import csv
import gzip
from pathlib import Path
from textwrap import dedent

import gemmi
import pytest
from protein_quest.structure.uniprot import add_uniprot_accessions2structure
from protein_quest.uniprot_chains import UniprotChainMapping, UniprotChainRange

from tests.helpers import cli, fake_run_retrieve


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


def fake_archive_em_structure(pdb_id: str, output: Path, uniprot_accession: str = "P12345"):
    structure = gemmi.Structure()
    structure.name = pdb_id
    structure.info["_entry.id"] = pdb_id
    structure.info["_exptl.method"] = "X-RAY DIFFRACTION"
    structure.resolution = 4.2
    atom = gemmi.Atom()
    atom.name = "CA"
    atom.element = gemmi.Element("C")
    residue = gemmi.Residue()
    residue.name = "ALA"
    residue.label_seq = 1
    residue.seqid = gemmi.SeqId(1, " ")
    residue.add_atom(atom)
    residue.entity_type = gemmi.EntityType.Polymer
    chain = gemmi.Chain("A")
    chain.add_residue(residue)
    model = gemmi.Model(1)
    model.add_chain(chain)
    structure.add_model(model)
    structure.setup_entities()
    structure.assign_subchains()
    structure = add_uniprot_accessions2structure(
        structure,
        {
            pdb_id: {
                UniprotChainMapping(
                    uniprot_accession=uniprot_accession,
                    chain_ranges=(UniprotChainRange(chain_ids=("A",), start=1, end=100),),
                )
            }
        },
    )
    structure.setup_entities()
    doc = structure.make_mmcif_document(gemmi.MmcifOutputGroups(True, chem_comp=False))

    output.write_bytes(gzip.compress(doc.as_string().encode("utf-8")))


def fake_solutions(session_dir: Path, powerfit_run_id: str) -> list[Path]:
    # Create structures
    structures_dir = session_dir / "combined_output"
    structures_dir.mkdir()
    fake_archive_em_structure("1abc", structures_dir / "1abc.cif.gz", uniprot_accession="P67890")
    fake_archive_em_structure("2abc", structures_dir / "2abc.cif.gz", uniprot_accession="P42424")
    fake_archive_em_structure("3abc", structures_dir / "3abc.cif.gz", uniprot_accession="P12345")

    # Write fake solutions
    powerfit_run_dir = session_dir / "powerfit" / powerfit_run_id
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
    trimmed_keys = {"powerfit_run_id", "structure", "rank", "cc", "uniprot_accession", "pdb_id", "template_file"}
    trimmed_solutions = [{k: v for k, v in s.items() if k in trimmed_keys} for s in solutions]
    assert trimmed_solutions == expected


class TestHandlerPowerfitReport:
    def test_defaults(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        session_dir = tmp_path
        template_dir = session_dir / "combined_output"
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
                "template_file": str(template_dir / "3abc.cif.gz"),
                "uniprot_accession": "P12345",
                "pdb_id": "3abc",
            },
            {
                "powerfit_run_id": "run_001",
                "structure": "2abc.cif.gz",
                "rank": "1",
                "cc": "0.442",
                "template_file": str(template_dir / "2abc.cif.gz"),
                "uniprot_accession": "P42424",
                "pdb_id": "2abc",
            },
            {
                "powerfit_run_id": "run_001",
                "structure": "1abc.cif.gz",
                "rank": "1",
                "cc": "0.399",
                "template_file": str(template_dir / "1abc.cif.gz"),
                "uniprot_accession": "P67890",
                "pdb_id": "1abc",
            },
        ]
        assert_solutions(stdout, expected)

    def test_top2(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        session_dir = tmp_path
        template_dir = session_dir / "combined_output"
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
                "template_file": str(template_dir / "3abc.cif.gz"),
                "uniprot_accession": "P12345",
            },
            {
                "cc": "0.487",
                "pdb_id": "3abc",
                "powerfit_run_id": "run_001",
                "rank": "2",
                "structure": "3abc.cif.gz",
                "template_file": str(template_dir / "3abc.cif.gz"),
                "uniprot_accession": "P12345",
            },
            {
                "cc": "0.442",
                "pdb_id": "2abc",
                "powerfit_run_id": "run_001",
                "rank": "1",
                "structure": "2abc.cif.gz",
                "template_file": str(template_dir / "2abc.cif.gz"),
                "uniprot_accession": "P42424",
            },
            {
                "cc": "0.442",
                "pdb_id": "2abc",
                "powerfit_run_id": "run_001",
                "rank": "2",
                "structure": "2abc.cif.gz",
                "template_file": str(template_dir / "2abc.cif.gz"),
                "uniprot_accession": "P42424",
            },
            {
                "cc": "0.399",
                "pdb_id": "1abc",
                "powerfit_run_id": "run_001",
                "rank": "1",
                "structure": "1abc.cif.gz",
                "template_file": str(template_dir / "1abc.cif.gz"),
                "uniprot_accession": "P67890",
            },
            {
                "cc": "0.398",
                "pdb_id": "1abc",
                "powerfit_run_id": "run_001",
                "rank": "2",
                "structure": "1abc.cif.gz",
                "template_file": str(template_dir / "1abc.cif.gz"),
                "uniprot_accession": "P67890",
            },
        ]
        assert_solutions(stdout, expected)

    def test_no_group_by_structure(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        session_dir = tmp_path
        template_dir = session_dir / "combined_output"
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
                "template_file": str(template_dir / "3abc.cif.gz"),
                "uniprot_accession": "P12345",
            },
            {
                "cc": "0.487",
                "pdb_id": "3abc",
                "powerfit_run_id": "run_001",
                "rank": "2",
                "structure": "3abc.cif.gz",
                "template_file": str(template_dir / "3abc.cif.gz"),
                "uniprot_accession": "P12345",
            },
        ]
        assert_solutions(stdout, expected)
