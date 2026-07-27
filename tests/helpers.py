"""Helper functions for testing."""

import csv
import gzip
import sys
from pathlib import Path
from typing import Any

import gemmi
from protein_quest.structure.uniprot import add_uniprot_accessions2structure
from protein_quest.uniprot_chains import UniprotChainMapping, UniprotChainRange
from rocrate.metadata import BASENAME
from rocrate.rocrate import ROCrate
from vcr import use_cassette

from protein_detective.__version__ import __version__
from protein_detective.cli import app


def cli(tokens: list[str]):
    """Invoke the CLI with the given tokens.

    Replace default print_non_int_sys_exit result action,
    with action that does not throw SystemExit.
    Also mock sys.argv to simulate CLI invocation.

    Args:
        tokens: List of command line tokens to pass to the CLI.
    """
    old_argv = sys.argv
    sys.argv = ["protein-detective", *tokens]
    try:
        return app(tokens, result_action="return_value")
    finally:
        sys.argv = old_argv


def fake_setup_retrieve(tmp_path: Path):
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    alphafold_csv = session_dir / "alphafold.csv"
    alphafold_csv.write_text("af_id\nA0A0C5B5G6\n")

    pdbe_csv = session_dir / "pdbe.csv"
    pdbe_csv.write_text("pdb_id,uniprot_accession,uniprot_chains,chain\n2Y29,P05067,A=687-692,A\n")

    argv = ["retrieve", str(session_dir), "--alphafold-db-version", "6"]
    return session_dir, argv


def fake_run_retrieve(tmp_path: Path):
    session_dir, argv = fake_setup_retrieve(tmp_path)
    repo_root = Path(__file__).resolve().parents[1]
    retrieve_cassette = repo_root / "tests" / "cassettes" / "test_cli" / "test_retrieve.yaml"
    with use_cassette(retrieve_cassette):
        cli(argv)
    return session_dir


def assert_crate(
    crate_dir: Path,
    *,
    action_id: str | None = None,
    input_ids: set[str] | None = None,
    output_ids: set[str] | None = None,
    nr_actions: int = 1,
) -> tuple[ROCrate, dict[str, Any]]:
    # Assert copied from tests/adapters/test_cyclopts.py in rocrate_action_recorder repo
    crate_path = crate_dir / BASENAME
    assert crate_path.exists()

    crate = ROCrate(crate_dir)
    actions = crate.get_by_type("CreateAction", exact=True)
    assert len(actions) == nr_actions, (
        f"Expected exactly {nr_actions} CreateAction(s) in the crate, found {len(actions)}"
    )
    action = actions[-1]

    if action_id is not None:
        assert action["@id"] == action_id
        assert action["name"] == action_id

    assert action["instrument"]["@id"] == f"protein-detective@{__version__}"

    input_ids = {i["@id"] for i in action.get("object", [])}
    if input_ids is not None:
        assert input_ids <= input_ids

    output_ids = {o["@id"] for o in action.get("result", [])}
    if output_ids is not None:
        assert output_ids <= output_ids

    return crate, action


def read_csv(file: Path) -> list[dict[str, str]]:
    with file.open() as f:
        return list(csv.DictReader(f))


def fake_structure_file(pdb_id: str, output: Path, uniprot_accession: str | None, chain_id: str = "A"):
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
    chain = gemmi.Chain(chain_id)
    chain.add_residue(residue)
    model = gemmi.Model(1)
    model.add_chain(chain)
    structure.add_model(model)
    structure.setup_entities()
    structure.assign_subchains()
    if uniprot_accession:
        structure, _injected, _uniprot_chains = add_uniprot_accessions2structure(
            structure,
            {
                pdb_id: {
                    UniprotChainMapping(
                        uniprot_accession=uniprot_accession,
                        chain_ranges=(UniprotChainRange(chain_ids=(chain_id,), start=1, end=100),),
                    )
                }
            },
        )
        structure.setup_entities()
    doc = structure.make_mmcif_document(gemmi.MmcifOutputGroups(True, chem_comp=False))

    output.write_bytes(gzip.compress(doc.as_string().encode("utf-8")))


def assert_lines(file: Path, expected_lines: set[str]):
    """Assert that the lines in the file match the expected lines."""
    with file.open() as f:
        actual_lines = {line.strip() for line in f.readlines()}
    assert actual_lines == expected_lines, f"Expected lines {expected_lines} but got {actual_lines} in file {file}"
