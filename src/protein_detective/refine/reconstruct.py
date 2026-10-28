"""Split refined complexes and restore the known partner's original residue IDs."""

import csv
from pathlib import Path

import gemmi
from protein_quest.structure.formats import read_structure, write_structure


def reconstruct_refined_structures(
    refinement_dir: Path, original_known_structure: Path, *, remove_known_chains: set[str] | None = None
) -> Path:
    """Write fitted/known PDB pairs and an index with paths relative to refinement_dir.

    Restore chain and residue identifiers using the sequential numbering assigned
    by prepare_known_structure. Retain HADDOCK's atoms and refined coordinates.

    Args:
        refinement_dir: Completed HADDOCK3 refinement workflow directory.
        original_known_structure: Saved, unmodified known input.
        remove_known_chains: Original chains omitted when preparing the partner.

    Returns:
        Path to 9_reconstruct/io.csv.
    """
    original = read_structure(original_known_structure)
    if len(original) != 1:
        msg = "Reconstruction requires a single-model known structure."
        raise ValueError(msg)
    residues = [
        (chain.name, residue.seqid)
        for chain in original[0]
        if chain.name not in (remove_known_chains or set())
        for residue in chain
    ]
    complexes = sorted((refinement_dir / "6_mdref").glob("*.pdb*"))
    if not complexes:
        msg = f"No refined PDB files found in {refinement_dir / '6_mdref'}"
        raise FileNotFoundError(msg)
    output_dir = refinement_dir / "9_reconstruct"
    output_dir.mkdir()
    index = output_dir / "io.csv"
    with index.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["model", "refined_complex", "refined_fitted_structure", "refined_known_structure"])
        for complex_path in complexes:
            complex_structure = read_structure(complex_path)
            if len(complex_structure) != 1 or not {"A", "B"} <= {c.name for c in complex_structure[0]}:
                msg = f"Expected a single model with fitted chain A and known chain B: {complex_path}"
                raise ValueError(msg)
            known = gemmi.Structure()
            known.add_model(gemmi.Model(1))
            for residue in complex_structure[0]["B"]:
                number = residue.seqid.num
                if number is None or not 1 <= number <= len(residues):
                    msg = f"Unknown prepared residue {residue.seqid} in {complex_path}"
                    raise ValueError(msg)
                chain_name, seqid = residues[number - 1]
                if known[0].find_chain(chain_name) is None:
                    known[0].add_chain(gemmi.Chain(chain_name))
                restored = residue.clone()
                restored.seqid = seqid
                restored.segment = chain_name
                known[0][chain_name].add_residue(restored)
            for chain in list(complex_structure[0]):
                if chain.name != "A":
                    complex_structure[0].remove_chain(chain.name)
            name = complex_path.name.removesuffix(".gz").removesuffix(".pdb")
            fitted_path = output_dir / f"{name}_fitted.pdb.gz"
            known_path = output_dir / f"{name}_known.pdb.gz"
            write_structure(complex_structure, fitted_path)
            write_structure(known, known_path)
            writer.writerow(
                [
                    str(complex_path.relative_to(output_dir, walk_up=True)).removesuffix(".gz"),
                    *(str(path.relative_to(refinement_dir)) for path in (complex_path, fitted_path, known_path)),
                ]
            )
    return index
