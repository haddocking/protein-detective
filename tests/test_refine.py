from pathlib import Path

import pytest
from protein_quest.structure.formats import read_structure

from protein_detective import refine
from protein_detective.refine import _prepare_fixed_structure


def test_haddock3_executable_is_in_active_virtual_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # TODO do not test private function
    # TODO do not monkeypatch, see https://github.com/haddocking/protein-quest/pull/160
    bin_dir = tmp_path / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    python_executable = bin_dir / "python"
    haddock3_executable = bin_dir / "haddock3"
    haddock3_executable.touch()
    monkeypatch.setattr(refine.sys, "executable", str(python_executable))

    result = refine._haddock3_executable()

    assert result == Path(haddock3_executable).resolve()


def test_prepare_fixed_structure_renames_all_chains(tmp_path):
    source = tmp_path / "fixed.pdb"
    source.write_text(
        "ATOM      1  CA  GLY A   1       0.000   0.000   0.000  1.00 20.00           C  \n"
        "TER\n"
        "ATOM      2  CA  GLY C   1       1.000   0.000   0.000  1.00 20.00           C  \n"
        "END\n"
    )

    output = _prepare_fixed_structure(source, tmp_path, out_chain="Z")

    structure = read_structure(output)
    chains = [chain for model in structure for chain in model]
    atoms = [atom for chain in chains for residue in chain for atom in residue]
    assert output == tmp_path / "fixed_structure.cif.gz"
    assert {chain.name for chain in chains} == {"Z"}
    assert len(atoms) == 2
