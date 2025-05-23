from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path

"""
Methods to filter AlphaFoldDB structures on confidence scores.

In AlphaFold PDB files, the b-factor column has the
predicted local distance difference test (pLDDT).

See https://www.ebi.ac.uk/training/online/courses/alphafold/inputs-and-outputs/evaluating-alphafolds-predicted-structures-using-confidence-scores/plddt-understanding-local-confidence/
"""


def find_high_confidence_residues(pdb_file: Path, confidence: float) -> Generator[int]:
    prev_res_index = None
    with pdb_file.open("r") as f:
        for line in f:
            if line.startswith("ATOM"):
                # Extract the b-factor value from the PDB line
                b_factor = float(line[60:66].strip())
                if b_factor > confidence:
                    # Extract the residue index from the PDB line
                    res_index = int(line[22:26].strip())
                    # yield once per residue, not for every atom of the residue
                    if res_index != prev_res_index:
                        yield res_index
                        prev_res_index = res_index


def filter_out_low_confidence_residues(input_pdb_file: Path, allowed_residues: set[int], output_pdb_file: Path):
    # TODO if residue is removed from ATOM lines also remove it
    # elsewhere in the file (SEQRES, TER).
    # TODO do we need to take model/chain into account?
    # now assumes single model and single chain
    with input_pdb_file.open("r") as input_file, output_pdb_file.open("w") as output_file:
        for line in input_file:
            if line.startswith("ATOM"):
                # Extract the residue index from the PDB line
                res_index = int(line[22:26].strip())
                if res_index in allowed_residues:
                    output_file.write(line)
            else:
                output_file.write(line)


@dataclass
class DensityFilterResult:
    pdb_file: str
    count: int
    """The number of residues with a pLDDT above the confidence threshold."""
    density_filtered_file: Path | None = None


def filter_on_density(
    session_dir: Path, confidence: float, min_threshold: int, max_threshold: int
) -> Generator[DensityFilterResult]:
    download_dir = session_dir / "downloads"
    density_filtered_dir = session_dir / "density_filtered"
    density_filtered_dir.mkdir(parents=True, exist_ok=True)

    # TODO get list of files from filesystem or from session db?
    for pdb_file in download_dir.glob("AF-*.pdb"):
        residues = set(find_high_confidence_residues(pdb_file, confidence))
        count = len(residues)
        if count < min_threshold or count > max_threshold:
            yield DensityFilterResult(
                pdb_file=pdb_file.name,
                count=count,
            )
            # Skip structure that is outside the min and max threshold
            continue
        density_filtered_file = density_filtered_dir / pdb_file.name
        filter_out_low_confidence_residues(
            pdb_file,
            residues,
            density_filtered_file,
        )
        yield DensityFilterResult(
            pdb_file=pdb_file.name,
            count=count,
            density_filtered_file=density_filtered_file,
        )
