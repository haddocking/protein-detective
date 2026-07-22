"""Helper functions for testing."""

import sys
from pathlib import Path

from vcr import use_cassette

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


def fake_setup_retrieve(tmp_path):
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    alphafold_csv = session_dir / "alphafold.csv"
    alphafold_csv.write_text("af_id\nA0A0C5B5G6\n")

    pdbe_csv = session_dir / "pdbe.csv"
    pdbe_csv.write_text("pdb_id,uniprot_accession,uniprot_chains,chain\n2Y29,P05067,A=687-692,A\n")

    argv = ["retrieve", str(session_dir), "--alphafold-db-version", "6"]
    return session_dir, argv


def fake_run_retrieve(tmp_path):
    session_dir, argv = fake_setup_retrieve(tmp_path)
    repo_root = Path(__file__).resolve().parents[1]
    retrieve_cassette = repo_root / "tests" / "cassettes" / "test_cli" / "test_retrieve.yaml"
    with use_cassette(retrieve_cassette):
        cli(argv)
    return session_dir
