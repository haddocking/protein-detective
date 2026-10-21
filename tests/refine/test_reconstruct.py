import csv
from pathlib import Path

import duckdb
import gemmi
import pytest
from protein_quest.structure.formats import read_structure, write_structure

from protein_detective.meta import execute_ddl_statements, refinements_runs_as_duckdb_ddl
from protein_detective.refine import run
from protein_detective.refine.haddock import prepare_fitted_and_known, prepare_known_structure
from protein_detective.refine.reconstruct import reconstruct_refined_structures


def make_structure(chains: list[str]) -> gemmi.Structure:
    structure = gemmi.Structure()
    structure.add_model(gemmi.Model(1))
    for name in chains:
        chain = gemmi.Chain(name)
        for icode in (" ", "A"):
            residue = gemmi.Residue()
            residue.name = "ALA"
            residue.seqid = gemmi.SeqId(7, icode)
            atom = gemmi.Atom()
            atom.name = "CA"
            atom.element = gemmi.Element("C")
            atom.pos = gemmi.Position(1, 2, 3)
            residue.add_atom(atom)
            chain.add_residue(residue)
        structure[0].add_chain(chain)
    return structure


@pytest.mark.parametrize("input_name", ["original.cif.gz", "original.pdb", "known_structure.pdb"])
def test_refinement_reconstructs_partners(tmp_path: Path, input_name: str):
    session = tmp_path / "session"
    refine_root = session / "refine/refine_run_001"
    refine_root.mkdir(parents=True)
    source = tmp_path / input_name
    write_structure(make_structure(["X", "Y", "Z"]), source)
    fitted = session / "powerfit/run_001/model/fit_1.pdb"
    fitted.parent.mkdir(parents=True)
    write_structure(make_structure(["A"]), fitted)
    refinement = refine_root / "run_001/model/fit_1.pdb/refinement"
    refinement.mkdir(parents=True)
    prepared, saved = prepare_known_structure(source, refine_root, remove_known_chains={"Z"})
    assert saved.read_bytes() == source.read_bytes()
    assert saved.name == source.name
    assert saved != prepared
    run._write_io_csv(
        session_dir=session,
        refine_dir=refine_root,
        refined=[(fitted, refinement.parent)],
        original_known_structure=saved,
        processed_known_structure=prepared,
    )
    complex_path = prepare_fitted_and_known(fitted, prepared, refinement)
    structure = read_structure(complex_path)
    # Model a filtered residue and additional/refined atoms in HADDOCK's output.
    del structure[0]["B"][1]
    for chain in structure[0]:  # zorilla: ignore -- Construct refined coordinates for both partners.
        for residue in chain:
            residue[0].pos = gemmi.Position(4, 5, 6)
            hydrogen = gemmi.Atom()
            hydrogen.name = "H"
            hydrogen.element = gemmi.Element("H")
            residue.add_atom(hydrogen)
    mdref = refinement / "6_mdref"
    mdref.mkdir()
    for number in (1, 2):  # zorilla: ignore -- Verify an index containing multiple output pairs.
        write_structure(structure, mdref / f"mdref_{number}.pdb.gz")
    reconstruct_refined_structures(refinement, saved, remove_known_chains={"Z"})
    output = refinement / "9_reconstruct"
    with (output / "io.tsv").open() as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    assert len(rows) == 2
    for number, row in enumerate(rows, start=1):  # zorilla: ignore -- Check each indexed output pair.
        assert row == {
            "refined_complex": f"6_mdref/mdref_{number}.pdb.gz",
            "fitted_structure": f"9_reconstruct/mdref_{number}_fitted.pdb.gz",
            "known_structure": f"9_reconstruct/mdref_{number}_known.pdb.gz",
        }
        fitted_result = read_structure(refinement / row["fitted_structure"])
        assert [c.name for c in fitted_result[0]] == ["A"]
        known_result = read_structure(refinement / row["known_structure"])
        assert [(c.name, [str(r.seqid) for r in c]) for c in known_result[0]] == [("X", ["7"]), ("Y", ["7", "7A"])]
        for result in (fitted_result, known_result):
            for chain in result[0]:
                for residue in chain:
                    assert residue[0].pos.tolist() == [4, 5, 6]
                    assert [a.name for a in residue] == ["CA", "H"]

    # Runs without recorded provenance are excluded even when their IO indexes exist.
    source.unlink()
    relocated = session.with_name("relocated")
    session.rename(relocated)
    with duckdb.connect() as con:
        execute_ddl_statements(con, refinements_runs_as_duckdb_ddl(relocated))
        assert (
            con.execute("SELECT original_known_structure, processed_known_structure FROM refinements_runs").fetchall()
            == []
        )
