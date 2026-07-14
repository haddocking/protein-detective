from pathlib import Path

from protein_quest.filters.chain import ChainFilterStatistics
from protein_quest.filters.combined import CombinedFilterResult
from protein_quest.filters.ss import (
    SecondaryStructureFilterResult,
    SecondaryStructureStats,
)

from protein_detective.filter import FilteredStructure


def _secondary_structure_result(*, passed: bool) -> SecondaryStructureFilterResult:
    return SecondaryStructureFilterResult(
        stats=SecondaryStructureStats(
            nr_residues=10,
            nr_helix_residues=2,
            nr_sheet_residues=3,
            helix_ratio=0.2,
            sheet_ratio=0.3,
        ),
        passed=passed,
    )


def test_filtered_structure_prefers_secondary_structure_output(tmp_path: Path):
    combined_output = tmp_path / "combined" / "input.cif"
    final_output = tmp_path / "final" / "input.cif"
    structure = FilteredStructure(
        uniprot_accession="P12345",
        combined=CombinedFilterResult(
            input_file=tmp_path / "raw" / "input.cif",
            pdb_id="1abc",
            passed=True,
            output_file=combined_output,
        ),
        secondary_structure=(combined_output, _secondary_structure_result(passed=True), final_output),
    )

    assert structure.passed is True
    assert structure.output_file == final_output


def test_filtered_structure_chain_failure_overrides_combined_pass(tmp_path: Path):
    structure = FilteredStructure(
        uniprot_accession="P12345",
        chain=ChainFilterStatistics(input_file=tmp_path / "raw" / "input.cif", chain_id="B", passed=False),
        combined=CombinedFilterResult(
            input_file=tmp_path / "chain" / "input.cif",
            pdb_id="1abc",
            passed=True,
            output_file=tmp_path / "combined" / "input.cif",
        ),
    )

    assert structure.passed is False
    assert structure.output_file is None


def test_filtered_structure_make_relative_to_rewrites_nested_paths(tmp_path: Path):
    session_dir = tmp_path / "session"
    raw_file = session_dir / "raw" / "input.cif"
    chain_file = session_dir / "chain" / "input.cif"
    combined_file = session_dir / "combined" / "input.cif"
    ss_file = session_dir / "final" / "input.cif"

    structure = FilteredStructure(
        uniprot_accession="P12345",
        chain=ChainFilterStatistics(input_file=raw_file, chain_id="A", passed=True, output_file=chain_file),
        combined=CombinedFilterResult(
            input_file=chain_file,
            pdb_id="1abc",
            passed=True,
            output_file=combined_file,
        ),
        secondary_structure=(combined_file, _secondary_structure_result(passed=True), ss_file),
    )

    relative = structure.make_relative_to(session_dir)

    assert relative.chain is not None
    assert relative.chain.output_file == Path("chain/input.cif")
    assert relative.combined is not None
    assert relative.combined.input_file == Path("chain/input.cif")
    assert relative.combined.output_file == Path("combined/input.cif")
    assert relative.secondary_structure is not None
    assert relative.secondary_structure == (
        Path("combined/input.cif"),
        relative.secondary_structure[1],
        Path("final/input.cif"),
    )
