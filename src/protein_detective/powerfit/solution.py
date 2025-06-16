from pathlib import Path

import atomium
import numpy as np
import pandas as pd
from tqdm import tqdm


def fit_pdb(pdb_file: Path, translation: np.ndarray, rotation: np.ndarray, out_file: Path):
    """Translate and rotate a PDB file and save the result to a new PDB file.

    Args:
        pdb_file: path to the PDB file to fit
        translation: x, y, z translation vector
        rotation: 3x3 rotation matrix
        out_file: path to the output PDB file

    """
    # Reimplementation of powerfit_em.helper:write_fits_to_pdb()
    # using atomium
    file = atomium.open(str(pdb_file))
    # type: ignore[missing-attribute]
    model: atomium.Model = file.model

    # TODO verify atomium and powerfit give same resulting PDB file
    center = geometric_center(model)
    ncenter = -center
    model.translate(ncenter[0], ncenter[1], ncenter[2])

    model.transform(rotation)
    model.translate(translation[0], translation[1], translation[2])

    model.save(str(out_file))


def geometric_center(model: atomium.Model) -> np.ndarray:
    """Calculate the geometric center of the model.

    Args:
        model: The atomium model to calculate the center of.

    Returns:
        The geometric center of the model.
    """
    # Code from atomium.structure:AtomStructure.center_of_mass()
    atoms = model.atoms()
    # type: ignore[not-iterable]
    locations = np.array([a._location for a in atoms])
    # type: ignore[no-matching-overload,bad-argument-type]
    return np.mean(locations, axis=0)


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
        fitted_files.append((index, powerfit_run_id, pdb_file, out_file))
    # type: ignore[bad-argument-type
    return pd.DataFrame(fitted_files, columns=["index", "powerfit_run_id", "pdb_file", "fitted_file"]).set_index(
        "index"
    )
