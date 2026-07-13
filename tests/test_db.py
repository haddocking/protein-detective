from pathlib import Path
from typing import TYPE_CHECKING

from protein_quest.filters.combined import CombinedFilterQuery, CombinedFilterResult
from protein_quest.filters.ss import SecondaryStructureFilterQuery
from protein_quest.pdbe.result import PdbResult
from protein_quest.pdbe.ws import Scores

from protein_detective.db import (
    connect,
    load_filtered_structure_files,
    load_pdbs,
    save_filter,
    save_filtered_structures,
    save_pdb_quality_scores,
    save_pdbs,
    save_uniprot_details,
)
from protein_detective.filter import FilteredStructure, FilterOptions

if TYPE_CHECKING:
    from protein_quest.uniprot import UniprotDetails


def test_save_uniprot_details(tmp_path: Path):
    details: list[UniprotDetails] = [
        {
            "uniprot_accession": "P12345",
            "uniprot_id": "PROT_HUMAN",
            "sequence_length": 350,
            "reviewed": True,
            "protein_name": "Example Protein",
            "taxon_id": 9606,
            "taxon_name": "Homo sapiens",
        }
    ]
    with connect(tmp_path) as con:
        save_uniprot_details(details, con)

        rows = con.execute("SELECT * FROM proteins").fetchall()
        expected = [("P12345", "PROT_HUMAN", 350, True, "Example Protein", 9606, "Homo sapiens")]
        assert rows == expected


def test_save_filter_reuses_same_combined_options(tmp_path: Path):
    options = FilterOptions(
        secondary_structure=SecondaryStructureFilterQuery(),
        combined=CombinedFilterQuery(
            min_confidence=82.0,
            min_residues=10,
            max_residues=20,
            min_geometry_quality=55.0,
            top_uniprot_cluster=3,
        ),
    )

    with connect(tmp_path) as con:
        filter_id = save_filter(options, con)
        same_filter_id = save_filter(options, con)

        rows = con.execute("SELECT filter_id, filter_options FROM filters").fetchall()

    assert filter_id == same_filter_id
    assert len(rows) == 1
    assert rows[0][0] == filter_id
    assert '"min_confidence":82.0' in rows[0][1]
    assert '"min_geometry_quality":55.0' in rows[0][1]


def test_save_filtered_structures_persists_output_files(tmp_path: Path):
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    filtered_file = session_dir / "filtered" / "input.cif"
    filtered_file.parent.mkdir()
    filtered_file.touch()

    result = FilteredStructure(
        uniprot_accession="P12345",
        pdb_id="1abc",
        combined=CombinedFilterResult(
            input_file=session_dir / "chain" / "input.cif",
            pdb_id="1abc",
            passed=True,
            output_file=filtered_file,
        ),
    ).make_relative_to(session_dir)
    options = FilterOptions(secondary_structure=SecondaryStructureFilterQuery())

    with connect(session_dir) as con:
        filter_id = save_filter(options, con)
        nr_saved = save_filtered_structures([result], filter_id, con)
        rows = con.execute(
            "SELECT uniprot_acc, pdb_id, passed, output_file, filter_stats FROM filtered_structures"
        ).fetchall()
        files = load_filtered_structure_files(con)

    assert nr_saved == 1
    assert rows[0][0:4] == ("P12345", "1abc", True, "filtered/input.cif")
    assert '"combined"' in rows[0][4]
    assert files == [filtered_file]


def test_save_pdb_quality_scores_persists_geometry_quality(tmp_path: Path):
    pdbs = {
        "P12345": {
            PdbResult(id="1ABC", method="X-ray diffraction", uniprot_chains="A=1-42", resolution="2.0")
        }
    }
    scores = {
        "1abc": Scores(
            geometry_quality=77.5,
            data_quality=None,
            overall_quality=None,
            experiment_data_available=False,
        )
    }

    with connect(tmp_path) as con:
        save_pdbs(pdbs, con)
        save_pdb_quality_scores(scores, con)
        rows = load_pdbs(con)
        raw_scores = con.execute("SELECT pdb_id, geometry_quality FROM pdbs").fetchall()

    assert raw_scores == [("1ABC", 77.5)]
    assert rows[0].geometry_quality == 77.5
