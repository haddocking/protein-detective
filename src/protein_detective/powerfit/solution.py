from pathlib import Path

import numpy as np
import pandas as pd
from powerfit_em.structure import Structure
from tqdm import tqdm


def fit_model(unfitted_model_file: Path, translation: np.ndarray, rotation: np.ndarray, fitted_model_file: Path):
    """Fit a model PDB file according to the given translation and rotation.

    Args:
        unfitted_model_file: Path to the input PDB file
        translation: Translation vector (numpy array of shape (3,))
        rotation: Rotation matrix (3x3 numpy array)
        fitted_model_file: Path to save the fitted model PDB file
    """
    # tried to use atomium to parse KsgA.pdb
    # but it produced <Model (0 chains, 252 ligands)> not as <Model (1 chains, 0 ligands)>
    # so we use powerfit_em.structure instead
    structure = Structure.fromfile(str(unfitted_model_file))
    center = structure.coor.mean(axis=1)
    structure.translate(-center)
    structure.rotate(rotation)
    structure.translate(translation)
    structure.tofile(str(fitted_model_file))


def fit_models(solutions: pd.DataFrame, powerfit_root_run_dir: Path) -> pd.DataFrame:
    """Fit model PDB files according to the translation and rotation in solutions DataFrame.

    Args:
        solutions: DataFrame with columns "pdb_file", "translation", "rotation", and "powerfit_run_id"
        powerfit_root_run_dir: Directory to save the fitted model PDB files.
            Should be directory where powerfit runs are stored.

    Returns:
        DataFrame with columns "powerfit_run_id", "structure", "rank", "fitted_model_file", and "unfitted_model_file"
    """
    fitted_files = []
    for index, row in tqdm(solutions.iterrows(), desc="Writing fitted model PDB files", total=len(solutions)):
        if not isinstance(index, int):
            msg = "index should be an int"
            raise TypeError(msg)

        pdb_file = row["pdb_file"]
        if not isinstance(pdb_file, str):
            msg = "pdb_file should be a str"
            raise TypeError(msg)
        unfitted_model_file = Path(pdb_file)

        translation = row["translation"]
        rotation = row["rotation"].reshape(3, 3)
        structure = row["structure"]
        rank = row["rank"]

        powerfit_run_id = row["powerfit_run_id"]
        fitted_model_file = powerfit_root_run_dir / powerfit_run_id / unfitted_model_file.stem / f"fit_{rank}.pdb"
        if not fitted_model_file.parent.exists():
            msg = f"Directory {fitted_model_file.parent} does not exist. Unable to save fitted model file."
            raise FileNotFoundError(msg)

        # type: ignore[bad-argument-type]
        fit_model(unfitted_model_file, translation, rotation, fitted_model_file)

        fitted_files.append(
            {
                "index": index,
                "powerfit_run_id": powerfit_run_id,
                "structure": structure,
                "rank": rank,
                "fitted_model_file": fitted_model_file,
                "unfitted_model_file": unfitted_model_file,
            }
        )

    return pd.DataFrame(
        fitted_files,
    ).set_index("index")
