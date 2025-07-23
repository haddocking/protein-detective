import logging
from pathlib import Path

import gemmi
import pytest

from protein_detective.pdbe.io import filter_and_write_single_chain_pdb_file, first_chain_from_uniprot_chains


@pytest.mark.parametrize(
    "query,expected",
    [
        ("O=1-300", "O"),  #  uniprot:A8MT69 pdb:7R5S
        ("B/D=1-81", "B"),  # uniprot:A8MT69 pdb:4E44
        (
            "B/D/H/L/M/N/U/V/W/X/Z/b/d/h/i/j/o/p/q/r=8-81",  # uniprot:A8MT69 pdb:4NE1
            "B",
        ),
        ("A/B=2-459,A/B=520-610", "A"),  # uniprot/O00255 pdb/3U84
        ("DD/Dd=1-1085", "DD"),  # uniprot/O00268 pdb/7ENA
        ("A=398-459,A=74-386,A=520-584,A=1-53", "A"),  # uniprot/O00255 pdb/7O9T
    ],
)
def test_first_chain_from_uniprot_chains(query, expected):
    result = first_chain_from_uniprot_chains(query)

    assert result == expected


@pytest.fixture
def cif_path() -> Path:
    return Path(__file__).parent / "fixtures" / "2y29.cif"


def test_filter_and_write_single_chain_pdb_file_happypath(cif_path: Path, tmp_path: Path):
    output_file = tmp_path / "test_output.pdb"
    chain2keep = "A"
    min_residues = 3
    max_residues = 10

    success, nr_residues = filter_and_write_single_chain_pdb_file(
        cif_path,
        chain2keep,
        output_file,
        min_residues,
        max_residues,
        out_chain="Z",
    )

    assert nr_residues == 6
    assert success is True
    assert output_file.exists()
    structure = gemmi.read_structure(str(output_file))
    assert len(structure) == 1  # One model
    model = structure[0]
    assert len(model) == 1  # One chain
    chain = model[0]
    assert chain.name == "Z"
    assert len(chain) == 6  # 6 residues in chain Z


def test_filter_and_write_single_chain_pdb_file_unknown_chain(
    cif_path: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    output_file = tmp_path / "test_output.pdb"
    chain2keep = "B"
    min_residues = 3
    max_residues = 10

    success, nr_residues = filter_and_write_single_chain_pdb_file(
        cif_path,
        chain2keep,
        output_file,
        min_residues,
        max_residues,
        out_chain="Z",
    )

    assert not success
    assert nr_residues == 0
    assert "Chain B not found in" in caplog.text


def test_filter_and_write_single_chain_pdb_file_below_min(
    cif_path: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    caplog.set_level(logging.INFO)
    output_file = tmp_path / "test_output.pdb"
    chain2keep = "A"
    min_residues = 100
    max_residues = 200

    success, nr_residues = filter_and_write_single_chain_pdb_file(
        cif_path,
        chain2keep,
        output_file,
        min_residues,
        max_residues,
        out_chain="Z",
    )

    assert not success
    assert nr_residues == 6
    assert "because it has too few residues in chain" in caplog.text


def test_filter_and_write_single_chain_pdb_file_above_max(
    cif_path: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    caplog.set_level(logging.INFO)
    output_file = tmp_path / "test_output.pdb"
    chain2keep = "A"
    min_residues = 1
    max_residues = 5

    success, nr_residues = filter_and_write_single_chain_pdb_file(
        cif_path,
        chain2keep,
        output_file,
        min_residues,
        max_residues,
        out_chain="Z",
    )

    assert not success
    assert nr_residues == 6
    assert "because it has too many residues in chain" in caplog.text
