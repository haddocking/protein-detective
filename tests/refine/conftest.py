from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture
def unclustered_refinement_results():
    """Generated with HADDOCK3 2026.8.0 by test_refine_with_haddock3_unclustered.

    Copied its 8_caprieval/capri_ss.tsv and capri_clt.tsv as is.
    Newer HADDOCK3 versions may change the output and fail these comparisons.
    """
    fixture_dir = Path(__file__).parents[1] / "fixtures/refine"
    return {
        "models": pd.read_csv(fixture_dir / "example-unclustered-refined-capri_ss.tsv", sep="\t", comment="#"),
        "clusters": pd.read_csv(fixture_dir / "example-unclustered-refined-capri_clt.tsv", sep="\t", comment="#"),
    }


@pytest.fixture
def clustered_refinement_results():
    """Generated with HADDOCK3 2026.8.0 by test_refine_with_haddock3_clustered.

    Copied its 8_caprieval/capri_ss.tsv and capri_clt.tsv as is.
    Newer HADDOCK3 versions may change the output and fail these comparisons.
    """
    fixture_dir = Path(__file__).parents[1] / "fixtures/refine"
    return {
        "models": pd.read_csv(fixture_dir / "example-clustered-refined-capri_ss.tsv", sep="\t", comment="#"),
        "clusters": pd.read_csv(fixture_dir / "example-clustered-refined-capri_clt.tsv", sep="\t", comment="#"),
    }


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
