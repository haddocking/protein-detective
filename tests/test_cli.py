import csv
import json
from pathlib import Path

import pytest

from tests.helpers import assert_crate, cli, fake_run_retrieve, fake_setup_retrieve, read_csv


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

    alphafolds = read_csv(session_dir / "alphafold.csv")
    assert alphafolds[0] == {
        "af_id": "A0A024R1R8",
        "uniprot_accession": "A0A024R1R8",
    }
    assert len(alphafolds) == 50

    pdbes = read_csv(session_dir / "pdbe.csv")
    assert pdbes[0] == {
        "chain": "E",
        "chain_length": "93",
        "method": "X-Ray_Crystallography",
        "pdb_id": "5HHM",
        "resolution": "2.5",
        "uniprot_accession": "A0A075B6N1",
        "uniprot_chains": "E/J=21-113",
    }
    assert len(pdbes) == 8

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
    session_dir, argv = fake_setup_retrieve(tmp_path)
    cli(argv)

    downloads_dir = session_dir / "downloads"
    assert downloads_dir.exists()
    assert sorted(downloads_dir.glob("**/*.cif.gz")) == [
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
    session_dir = fake_run_retrieve(tmp_path)
    pdbe_quality_json = session_dir / "pdbe-quality.json"
    pdbe_quality_json.write_text("{}")

    argv = [
        "filter",
        str(session_dir),
    ]
    cli(argv)

    assert read_csv(session_dir / "combined_stats.csv") == [
        {
            "chain_length": "16",
            "geometry_quality": "",
            "high_confidence_residues_count": "10",
            "input_file": "combined_input/AF-A0A0C5B5G6-F1-model_v6.cif.gz",
            "is_alphafold": "True",
            "method": "Predicted",
            "output_file": "combined_output/AF-A0A0C5B5G6-F1-model_v6.cif.gz",
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
            "input_file": "combined_input/2y29_updated_A2A.cif.gz",
            "is_alphafold": "False",
            "method": "X-ray",
            "output_file": "combined_output/2y29_updated_A2A.cif.gz",
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

    ss_output_dir = session_dir / "secondary_structure"
    assert not ss_output_dir.exists()
    ss_stats_file = session_dir / "secondary_structure_stats.csv"
    assert not ss_stats_file.exists()

    assert read_csv(session_dir / "single_chain_stats.csv") == [
        {
            "chain2keep": "A",
            "discard_reason": "",
            "input_file": "2y29_updated.cif.gz",
            "output_chain": "A",
            "output_file": "2y29_updated_A2A.cif.gz",
            "passed": "True",
        },
    ]

    assert read_csv(session_dir / "uniprots_verified_stats.csv") == [
        {
            "injected": "False",
            "input_file": "downloads/pdbe/2y29_updated.cif.gz",
            "output_file": "with_uniprots/2y29_updated.cif.gz",
            "uniprot_chain_mappings": "",
        },
    ]

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
            "uniprots_verified_stats.csv",
            "single_chain_stats.csv",
        },
        nr_actions=2,
    )
