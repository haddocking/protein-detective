import csv
import json
import sys
from pathlib import Path

import pytest
from rocrate.metadata import BASENAME
from rocrate.rocrate import ROCrate

from protein_detective.__version__ import __version__
from protein_detective.cli import app


def cli(tokens: list[str]):
    # Replace default print_non_int_sys_exit result action,
    # with action that does not throw SystemExit.
    # Also mock sys.argv to simulate CLI invocation.
    old_argv = sys.argv
    sys.argv = ["protein-detective", *tokens]
    result = app(tokens, result_action="return_value")
    sys.argv = old_argv
    return result


def test_app_help(capsys: pytest.CaptureFixture[str]):
    # Smoke test to ensure the CLI can be invoked and shows help message
    cli(["--help"])

    captured = capsys.readouterr()
    assert "Protein Detective CLI" in captured.out


def test_search_help(capsys: pytest.CaptureFixture[str]):
    # Smoke test to ensure the search command can be invoked
    cli(["search", "--help"])

    captured = capsys.readouterr()
    assert "Search for candidate protein structures" in captured.out


def assert_crate(
    crate_dir: Path,
    *,
    action_id: str | None = None,
    input_ids: set[str] | None = None,
    output_ids: set[str] | None = None,
    nr_actions: int = 1,
) -> tuple[ROCrate, dict]:
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


@pytest.mark.vcr
def test_search(tmp_path: Path):
    session_dir = tmp_path / "session"
    argv = [
        "search",
        str(session_dir),
        "--taxon-id",
        "9606",
        "--reviewed",
        "--limit-uniprot",
        "50",
        "--pdbe.limit",
        "50",
    ]
    cli(argv)

    uniprot_file = session_dir / "uniprot.txt"
    assert uniprot_file.exists()
    lines = uniprot_file.read_text().strip().splitlines()
    assert len(lines) >= 1

    with (session_dir / "alphafold.csv").open() as f:
        reader = csv.DictReader(f)
        af_rows = list(reader)
    assert len(af_rows) >= 1
    assert "uniprot_accession" in af_rows[0]
    assert "af_id" in af_rows[0]

    with (session_dir / "pdbe.csv").open() as f:
        reader = csv.DictReader(f)
        pdbe_rows = list(reader)
    assert len(pdbe_rows) >= 1
    assert "uniprot_accession" in pdbe_rows[0]
    assert "pdb_id" in pdbe_rows[0]

    quality_file = session_dir / "pdbe-quality.json"
    assert quality_file.exists()
    with quality_file.open() as f:
        quality_data = json.load(f)
        assert len(quality_data)

    assert_crate(
        session_dir,
        action_id=f"protein-detective search {session_dir} --taxon-id 9606 --reviewed --limit-uniprot 50 --pdbe.limit 50",
        output_ids={
            "uniprot.txt",
            "alphafold.csv",
            "pdbe.csv",
            "pdbe-quality.json",
        },
    )


def setup_retrieve(tmp_path):
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    alphafold_csv = session_dir / "alphafold.csv"
    alphafold_csv.write_text("af_id\nA0A0C5B5G6\n")

    pdbe_csv = session_dir / "pdbe.csv"
    pdbe_csv.write_text("pdb_id,uniprot_accession,uniprot_chains,chain\n2Y29,P05067,A=687-692,A\n")

    argv = ["retrieve", str(session_dir), "--alphafold-db-version", "6"]
    return session_dir, argv


@pytest.mark.vcr
def test_retrieve(tmp_path: Path):
    session_dir, argv = setup_retrieve(tmp_path)
    cli(argv)

    downloads_dir = session_dir / "downloads"
    assert downloads_dir.exists()
    assert list(downloads_dir.glob("**/*.cif.gz")) == [
        downloads_dir / "alphafold" / "AF-A0A0C5B5G6-F1-model_v6.cif.gz",
        downloads_dir / "pdbe" / "2y29_updated.cif.gz",
    ]

    assert_crate(
        session_dir,
        action_id=f"protein-detective retrieve {session_dir} --alphafold-db-version 6",
        input_ids={
            "alphafold.csv",
            "pdbe.csv",
        },
        output_ids={
            "downloads/alphafold",
            "downloads/pdbe",
        },
    )


def test_filter_help(capsys: pytest.CaptureFixture[str]):
    cli(["filter", "--help"])

    captured = capsys.readouterr()
    assert "Filter structure files based on specified parameters" in captured.out


@pytest.mark.vcr
@pytest.mark.default_cassette("test_retrieve.yaml")
def test_filter(tmp_path: Path):
    session_dir, argv = setup_retrieve(tmp_path)
    pdbe_quality_json = session_dir / "pdbe-quality.json"
    pdbe_quality_json.write_text("{}")

    cli(argv)

    argv = [
        "filter",
        str(session_dir),
    ]
    cli(argv)

    filtered_csv = session_dir / "combined_stats.csv"
    assert filtered_csv.exists()
    with filtered_csv.open() as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    expected_rows = [
        {
            "chain_length": "16",
            "geometry_quality": "",
            "high_confidence_residues_count": "10",
            "input_file": str(session_dir / "combined_input/AF-A0A0C5B5G6-F1-model_v6.cif.gz"),
            "is_alphafold": "True",
            "method": "Predicted",
            "output_file": str(session_dir / "combined_output/AF-A0A0C5B5G6-F1-model_v6.cif.gz"),
            "passed": "True",
            "pdb_id": "AF-A0A0C5B5G6-F1",
            "reason": "",
            "resolution": "0.0",
            "sequence_identity": "1.0",
            "total_residue_count": "16",
            "uniprot_accession": "A0A0C5B5G6",
            "uniprot_end": "16",
            "uniprot_start": "1",
        },
        {
            "chain_length": "8",
            "geometry_quality": "",
            "high_confidence_residues_count": "",
            "input_file": str(session_dir / "combined_input/2y29_updated_A2A.cif.gz"),
            "is_alphafold": "False",
            "method": "X-ray",
            "output_file": str(session_dir / "combined_output/2y29_updated_A2A.cif.gz"),
            "passed": "True",
            "pdb_id": "2Y29",
            "reason": "",
            "resolution": "2.3",
            "sequence_identity": "1.0",
            "total_residue_count": "8",
            "uniprot_accession": "P05067",
            "uniprot_end": "692",
            "uniprot_start": "687",
        },
    ]
    assert rows == expected_rows

    ss_output_dir = session_dir / "secondary_structure"
    assert not ss_output_dir.exists()
    ss_stats_file = session_dir / "secondary_structure_stats.csv"
    assert not ss_stats_file.exists()

    assert_crate(
        session_dir,
        action_id=f"protein-detective filter {session_dir}",
        input_ids={
            "pdbe.csv",
            "downloads/pdbe",
            "downloads/alphafold",
            "pdbe-quality.json",
        },
        output_ids={
            "single_chain",
            "uniprots_verified",
            "combined_input",
            "combined_output",
            "combined_stats.csv",
        },
        nr_actions=2,
    )
