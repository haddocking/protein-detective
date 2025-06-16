from pathlib import Path

import atomium
import numpy as np
import pandas as pd
from tqdm import tqdm


def fit_pdb(pdb_file: Path, translation, rotation, out_file: Path) -> Path:
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
    return out_file


def geometric_center(model: atomium.Model) -> np.ndarray:
    # Code from atomium.structure:AtomStructure.center_of_mass()
    atoms = model.atoms()
    # type: ignore[not-iterable]
    locations = np.array([a._location for a in atoms])
    # type: ignore[no-matching-overload,bad-argument-type]
    return np.mean(locations, axis=0)


def fit_pdbs(solutions: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
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
        fitted_file = fit_pdb(pdb_file, translation, rotation, out_file)
        fitted_files.append((index, powerfit_run_id, pdb_file, fitted_file))
    # type: ignore[bad-argument-type
    return pd.DataFrame(fitted_files, columns=["index", "powerfit_run_id", "pdb_file", "fitted_file"]).set_index(
        "index"
    )
