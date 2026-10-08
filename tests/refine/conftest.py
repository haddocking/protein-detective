from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture
def session_with_powerfit_results(tmp_path: Path) -> Path:
    session_with_powerfit_results = tmp_path / "session"
    models = []
    for run_id in ("run_001", "run_003"):
        model = session_with_powerfit_results / "powerfit" / run_id / "same_structure" / "fit_1.pdb"
        model.parent.mkdir(parents=True)
        model.write_text("MODEL\nENDMDL\n")
        models.append((run_id, str(model.relative_to(session_with_powerfit_results))))
    pd.DataFrame(models + models[:1], columns=["powerfit_run_id", "fitted_model_file"]).to_csv(
        session_with_powerfit_results / "powerfit/fitted_models.csv", index=False
    )
    return session_with_powerfit_results


@pytest.fixture
def fixed_structure_file(tmp_path: Path) -> Path:
    fixed_structure = tmp_path / "fixed.pdb"
    fixed_structure.write_text("MODEL\nENDMDL\n")
    return fixed_structure
