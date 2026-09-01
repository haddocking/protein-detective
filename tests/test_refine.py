from pathlib import Path

import pytest
from protein_quest.structure.formats import read_structure, write_structure

from protein_detective.refine import RefineOptions, refine_with_haddock3


@pytest.mark.manual
def test_refine_with_haddock3(tmp_path: Path, cif_9a2g: Path, cif_1gru_groes: Path):
    fixed_structure = cif_1gru_groes
    session_dir = tmp_path / "session"
    session_dir.mkdir(parents=True)
    powerfit_root_dir = session_dir / "powerfit"
    powerfit_run_dir = powerfit_root_dir / "run_001" / "fakestructure.cif"
    powerfit_run_dir.mkdir(parents=True)
    fitted_model = powerfit_run_dir / "fit_1.pdb"
    # Need pdb format so convert
    write_structure(read_structure(cif_9a2g), fitted_model)
    # fake fitted_models.csv
    fitted_models_csv = powerfit_root_dir / "fitted_models.csv"
    fitted_models_csv.write_text("fitted_model_file\npowerfit/run_001/fakestructure.cif/fit_1.pdb\n")

    refine_with_haddock3(
        session_dir,
        fixed_structure,
        options=RefineOptions(
            rigidbody_sampling=10,
        ),
        scheduler_address="sequential",
    )
