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
) -> tuple[ROCrate, dict]:
    # Assert copied from tests/adapters/test_cyclopts.py in rocrate_action_recorder repo
    crate_path = crate_dir / BASENAME
    assert crate_path.exists()

    crate = ROCrate(crate_dir)
    actions = crate.get_by_type("CreateAction", exact=True)
    assert len(actions) == 1, f"Expected exactly one CreateAction in the crate, found {len(actions)}"
    action = actions[0]

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


@pytest.mark.vcr
def test_retrieve(tmp_path: Path):
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    alphafold_csv = session_dir / "alphafold.csv"
    alphafold_csv.write_text("af_id\nA0A0C5B5G6\n")

    pdbe_csv = session_dir / "pdbe.csv"
    pdbe_csv.write_text("pdb_id\n2Y29\n")

    argv = ["retrieve", str(session_dir), "--alphafold-db-version", "6"]
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
