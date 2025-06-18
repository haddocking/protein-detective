from pathlib import Path

import numpy as np
import pandas as pd
from powerfit_em.structure import Structure
from tqdm import tqdm


def fit_pdb(pdb_file: Path, translation: np.ndarray, rotation: np.ndarray, out_file: Path):
    """Fit a PDB file according to the given translation and rotation.

    Args:
        pdb_file: Path to the input PDB file
        translation: Translation vector (numpy array of shape (3,))
        rotation: Rotation matrix (3x3 numpy array)
        out_file: Path to save the fitted PDB file
    """
    # tried to use atomium to parse KsgA.pdb
    # but it produced <Model (0 chains, 252 ligands)> not as <Model (1 chains, 0 ligands)>
    # so we use powerfit_em.structure instead
    structure = Structure.fromfile(str(pdb_file))
    center = structure.coor.mean(axis=1)
    structure.translate(-center)
    structure.rotate(rotation)
    structure.translate(translation)
    structure.tofile(str(out_file))


def fit_pdbs(solutions: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    """Fit PDB files according to the solutions DataFrame.

    Args:
        solutions: DataFrame with columns "pdb_file", "translation", "rotation", and "powerfit_run_id"
        out_dir: Directory to save the fitted PDB files

    Returns:
        DataFrame with columns "index", "powerfit_run_id", "pdb_file", and "fitted_file"
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    fitted_files = []
    for index, row in tqdm(solutions.iterrows(), desc="Writing fitted PDB files", total=len(solutions)):
        raw_pdb_file = row["pdb_file"]
        if not isinstance(raw_pdb_file, str):
            msg = "raw_pdb_file should be a str"
            raise TypeError(msg)
        pdb_file = Path(raw_pdb_file)

        translation = row["translation"]
        rotation = row["rotation"].reshape(3, 3)

        if not isinstance(index, int):
            msg = "index should be an int"
            raise TypeError(msg)
        powerfit_run_id = row["powerfit_run_id"]
        out_file = out_dir / f"{index + 1}_{powerfit_run_id}_{pdb_file.name}"

        # type: ignore[bad-argument-type]
        fit_pdb(pdb_file, translation, rotation, out_file)

        structure = row["structure"]
        rank = row["rank"]

        fitted_files.append((index, powerfit_run_id, structure, rank, pdb_file, out_file))

    return pd.DataFrame(
        fitted_files,
        # type: ignore[bad-argument-type]
        columns=["index", "powerfit_run_id", "structure", "rank", "pdb_file", "fitted_file"],
    ).set_index("index")
