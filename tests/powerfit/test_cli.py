import csv
import gzip
from argparse import Namespace
from collections.abc import Generator
from io import StringIO
from pathlib import Path
from textwrap import dedent

import gemmi
import pytest
from protein_quest.structure.uniprot import add_uniprot_accessions2structure

from protein_detective.cli import handle_import_structures
from protein_detective.powerfit.cli import (
    handle_powerfit_commands,
    handler_powerfit_fit_models,
    handler_powerfit_report,
)


def fake_archive_em_structure(pdb_id: str, output: Path):
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
    residue.add_atom(atom)
    residue.entity_type = gemmi.EntityType.Polymer
    chain = gemmi.Chain("A")
    chain.add_residue(residue)
    model = gemmi.Model(1)
    model.add_chain(chain)
    structure.add_model(model)
    structure.setup_entities()
    structure.assign_subchains()
    structure = add_uniprot_accessions2structure(structure, {pdb_id: {("A", "P12345")}})
    doc = structure.make_mmcif_document(gemmi.MmcifOutputGroups(True, chem_comp=False))

    output.write_bytes(gzip.compress(doc.as_string().encode("utf-8")))


@pytest.fixture
def powerfitted_session(tmp_path) -> Generator[Path]:

    # Create structures
    structures_dir = tmp_path / "structures"
    structures_dir.mkdir()
    fake_archive_em_structure("1abc", structures_dir / "1abc.cif.gz")
    fake_archive_em_structure("2abc", structures_dir / "2abc.cif.gz")
    fake_archive_em_structure("3abc", structures_dir / "3abc.cif.gz")

    # Import structures
    session_dir = tmp_path / "session"
    import_ns = Namespace(
        session_dir=session_dir,
        structures_dir=structures_dir,
        copy_method="hardlink",
        strict=True,
    )
    handle_import_structures(import_ns)

    # Fake a powerfit run
    powerfit_run_id = "fakerun1"
    target = tmp_path / "fake_map.mrc"
    target.write_bytes(b"FAKE MRC DATA")
    commands_output = StringIO()
    commands_ns = Namespace(
        session_dir=session_dir,
        powerfit_run_id=powerfit_run_id,
        resolution=4.2,
        target=target,
        angle=42.0,
        no_laplace=False,
        no_core_weighted=False,
        no_resampling=True,
        resampling_rate=2.0,
        no_trimming=False,
        trimming_cutoff=13,
        nproc=1,
        batch_size=100,
        gpu=0,
        gpu_backend="opencl",
        output=commands_output,
    )
    handle_powerfit_commands(commands_ns)

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

    yield session_dir


def assert_solutions(output: StringIO, expected: list[dict[str, str]]) -> None:
    solutions = list(csv.DictReader(output.getvalue().splitlines()))
    trimmed_keys = {"powerfit_run_id", "structure", "rank", "cc"}
    trimmed_solutions = [{k: v for k, v in s.items() if k in trimmed_keys} for s in solutions]
    assert trimmed_solutions == expected


class TestHandlerPowerfitReport:
    def test_defaults(self, powerfitted_session: Path):
        session_dir = powerfitted_session
        powerfit_run_id = "fakerun1"
        output = StringIO()
        report_ns = Namespace(
            session_dir=session_dir,
            powerfit_run_id=powerfit_run_id,
            no_group_by_structure=False,
            top=1,
            output=output,
        )
        handler_powerfit_report(report_ns)

        expected = [
            {"powerfit_run_id": "fakerun1", "structure": "3abc.cif.gz", "rank": "1", "cc": "0.499"},
            {"powerfit_run_id": "fakerun1", "structure": "2abc.cif.gz", "rank": "1", "cc": "0.442"},
            {"powerfit_run_id": "fakerun1", "structure": "1abc.cif.gz", "rank": "1", "cc": "0.399"},
        ]
        assert_solutions(output, expected)

    def test_top2(self, powerfitted_session: Path) -> None:
        session_dir = powerfitted_session
        powerfit_run_id = "fakerun1"
        output = StringIO()
        report_ns = Namespace(
            session_dir=session_dir,
            powerfit_run_id=powerfit_run_id,
            no_group_by_structure=False,
            top=2,
            output=output,
        )
        handler_powerfit_report(report_ns)

        expected = [
            {"powerfit_run_id": "fakerun1", "structure": "3abc.cif.gz", "rank": "1", "cc": "0.499"},
            {"powerfit_run_id": "fakerun1", "structure": "3abc.cif.gz", "rank": "2", "cc": "0.487"},
            {"powerfit_run_id": "fakerun1", "structure": "2abc.cif.gz", "rank": "1", "cc": "0.442"},
            {"powerfit_run_id": "fakerun1", "structure": "2abc.cif.gz", "rank": "2", "cc": "0.442"},
            {"powerfit_run_id": "fakerun1", "structure": "1abc.cif.gz", "rank": "1", "cc": "0.399"},
            {"powerfit_run_id": "fakerun1", "structure": "1abc.cif.gz", "rank": "2", "cc": "0.398"},
        ]
        assert_solutions(output, expected)

    def test_no_group_by_structure(self, powerfitted_session: Path) -> None:
        session_dir = powerfitted_session
        powerfit_run_id = "fakerun1"
        output = StringIO()
        report_ns = Namespace(
            session_dir=session_dir,
            powerfit_run_id=powerfit_run_id,
            no_group_by_structure=True,
            top=2,
            output=output,
        )
        handler_powerfit_report(report_ns)

        expected = [
            {
                "cc": "0.499",
                "powerfit_run_id": "fakerun1",
                "rank": "1",
                "structure": "3abc.cif.gz",
            },
            {
                "cc": "0.487",
                "powerfit_run_id": "fakerun1",
                "rank": "2",
                "structure": "3abc.cif.gz",
            },
        ]
        assert_solutions(output, expected)


class TestHandlerPowerfitFitModels:
    def test_defaults(self, powerfitted_session: Path):
        session_dir = powerfitted_session
        powerfit_run_id = "fakerun1"
        output = StringIO()
        report_ns = Namespace(
            session_dir=session_dir,
            powerfit_run_id=powerfit_run_id,
            no_group_by_structure=False,
            top=1,
            output=output,
        )
        handler_powerfit_fit_models(report_ns)

        actual = list(csv.DictReader(output.getvalue().splitlines()))
        expected = []
        assert actual == expected
