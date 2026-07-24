import json
from pathlib import Path

import pytest

from tests.helpers import (
    assert_crate,
    assert_lines,
    cli,
    fake_run_retrieve,
    fake_setup_retrieve,
    fake_structure_file,
    read_csv,
)


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
def test_search_with_interaction_partners(tmp_path: Path):
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
        "--interaction.seed",
        "Q05471",
    ]
    cli(argv)

    assert_lines(session_dir / "interaction_partner_seeds.txt", {"Q05471"})
    complexes = read_csv(session_dir / "complexes.csv")
    assert complexes == [
        {
            "complex_id": "CPX-2122",
            "complex_title": "Swr1 chromatin remodelling complex",
            "complex_url": "https://www.ebi.ac.uk/complexportal/complex/CPX-2122",
            "members": "P31376;P35817;P38326;P53201;P53930;P60010;P80428;Q03388;Q03433;Q03940;Q05471;Q06707;Q12464;Q12509",
            "query_protein": "Q05471",
        }
    ]
    assert_lines(
        session_dir / "uniprot_with_interaction_partners.txt",
        {
            "A0A024R1R8",
            "A0A024RBG1",
            "A0A075B6H7",
            "A0A075B6H8",
            "A0A075B6H9",
            "A0A075B6I0",
            "A0A075B6I1",
            "A0A075B6I3",
            "A0A075B6I4",
            "A0A075B6I6",
            "A0A075B6I7",
            "A0A075B6I9",
            "A0A075B6J1",
            "A0A075B6J2",
            "A0A075B6J6",
            "A0A075B6J9",
            "A0A075B6K0",
            "A0A075B6K2",
            "A0A075B6K4",
            "A0A075B6K5",
            "A0A075B6K6",
            "A0A075B6L2",
            "A0A075B6L6",
            "A0A075B6N1",
            "A0A075B6N2",
            "A0A075B6N3",
            "A0A075B6N4",
            "A0A075B6P5",
            "A0A075B6Q5",
            "A0A075B6R0",
            "A0A075B6R2",
            "A0A075B6R9",
            "A0A075B6S0",
            "A0A075B6S2",
            "A0A075B6S4",
            "A0A075B6S5",
            "A0A075B6S6",
            "A0A075B6S9",
            "A0A075B6T6",
            "A0A075B6T7",
            "A0A075B6T8",
            "A0A075B6U4",
            "A0A075B6V5",
            "A0A075B6W5",
            "A0A075B6X5",
            "A0A075B6Y3",
            "A0A075B6Y9",
            "A0A075B700",
            "A0A075B706",
            "A0A075B734",
            # Below are the interaction partners
            "P31376",
            "P35817",
            "P38326",
            "P53201",
            "P53930",
            "P60010",
            "P80428",
            "Q03388",
            "Q03433",
            "Q03940",
            "Q06707",
            "Q12464",
            "Q12509",
        },
    )

    assert_crate(
        session_dir,
        action_id=f"protein-detective search {session_dir} --taxon-id 9606 --reviewed --limit-uniprot 50 --pdbe.limit 50 --interaction.seed Q05471",
        output_ids={
            "uniprot.txt",
            "alphafold.csv",
            "pdbe.csv",
            "pdbe-quality.json",
            "interaction_partner_seeds.txt",
            "complexes.csv",
            "uniprot_with_interaction_partners.txt",
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
def test_filter_defaults(tmp_path: Path):
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


@pytest.mark.vcr
@pytest.mark.default_cassette("test_retrieve.yaml")
def test_filter_with_secondary_structure(tmp_path: Path):
    session_dir = fake_run_retrieve(tmp_path)
    pdbe_quality_json = session_dir / "pdbe-quality.json"
    pdbe_quality_json.write_text("{}")

    argv = ["filter", str(session_dir), "--secondary.abs-min-helix-residues", "5"]
    cli(argv)

    assert read_csv(session_dir / "secondary_structure_stats.csv") == [
        {
            "helix_ratio": "0.0",
            "input_file": "combined_output/2y29_updated_A2A.cif.gz",
            "nr_helix_residues": "0",
            "nr_residues": "8",
            "nr_sheet_residues": "0",
            "output_file": "",
            "passed": "False",
            "sheet_ratio": "0.0",
        },
        {
            "helix_ratio": "0.0",
            "input_file": "combined_output/AF-A0A0C5B5G6-F1-model_v6.cif.gz",
            "nr_helix_residues": "0",
            "nr_residues": "10",
            "nr_sheet_residues": "0",
            "output_file": "",
            "passed": "False",
            "sheet_ratio": "0.0",
        },
    ]

    ss_stats_file = session_dir / "secondary_structure_stats.csv"
    assert ss_stats_file.exists()
    assert read_csv(ss_stats_file) == [
        {
            "helix_ratio": "0.0",
            "input_file": "combined_output/2y29_updated_A2A.cif.gz",
            "nr_helix_residues": "0",
            "nr_residues": "8",
            "nr_sheet_residues": "0",
            "output_file": "",
            "passed": "False",
            "sheet_ratio": "0.0",
        },
        {
            "helix_ratio": "0.0",
            "input_file": "combined_output/AF-A0A0C5B5G6-F1-model_v6.cif.gz",
            "nr_helix_residues": "0",
            "nr_residues": "10",
            "nr_sheet_residues": "0",
            "output_file": "",
            "passed": "False",
            "sheet_ratio": "0.0",
        },
    ]

    ss_dir = session_dir / "secondary_structure"
    assert ss_dir.exists()
    assert len(list(ss_dir.iterdir())) == 0

    assert_crate(
        session_dir,
        action_id=f"protein-detective filter {session_dir} --secondary.abs-min-helix-residues 5",
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
            "secondary_structure_stats.csv",
            "secondary_structure",
        },
        nr_actions=2,
    )


class TestImportStructures:
    def test_defaults_happy(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        session_dir = tmp_path / "session"
        session_dir.mkdir()
        input_dir = session_dir / "input"
        input_dir.mkdir()
        fake_structure_file("1abc", input_dir / "1abc.cif.gz", uniprot_accession="P67890")

        argv = [
            "import-structures",
            str(input_dir),
            str(session_dir),
        ]
        cli(argv)

        assert (session_dir / "imported_structures" / "1abc.cif.gz").exists()

        stderr = capsys.readouterr().err
        assert "Imported 1 structure files." in stderr

        assert_crate(
            session_dir,
            action_id=f"protein-detective import-structures {input_dir} {session_dir}",
            output_ids={
                "imported_structures/1abc.cif.gz",
            },
        )

    def test_loose_bad_structure(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        session_dir = tmp_path / "session"
        session_dir.mkdir()
        input_dir = session_dir / "input"
        input_dir.mkdir()
        fake_structure_file("1abc", input_dir / "1abc.cif.gz", uniprot_accession=None, chain_id="A")
        fake_structure_file("2def", input_dir / "2def.cif.gz", uniprot_accession="P67890", chain_id="B")

        argv = [
            "import-structures",
            str(input_dir),
            str(session_dir),
        ]
        cli(argv)

        assert not (session_dir / "imported_structures" / "1abc.cif.gz").exists()
        assert (session_dir / "imported_structures" / "2def.cif.gz").exists()

        stderr = capsys.readouterr().err
        assert "Imported 1 structure files." in stderr

        assert "UniProt accessions, expected 1" in stderr

    def test_strict_bad_structure(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        session_dir = tmp_path / "session"
        session_dir.mkdir()
        input_dir = session_dir / "input"
        input_dir.mkdir()
        fake_structure_file("2def", input_dir / "2def.cif.gz", uniprot_accession=None, chain_id="B")

        argv = [
            "import-structures",
            str(input_dir),
            str(session_dir),
            "--strict",
        ]
        with pytest.raises(ValueError, match="UniProt accessions, expected 1"):
            cli(argv)
