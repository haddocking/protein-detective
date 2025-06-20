from pathlib import Path

import duckdb
import numpy as np
import pytest
from numpy.testing import assert_array_almost_equal
from powerfit_em.structure import Structure

from protein_detective.powerfit.solution import fit_model


@pytest.fixture
def solution() -> dict[str, np.ndarray]:
    fn = Path(__file__).parent / "fixtures" / "solutions.out"
    con = duckdb.connect(database=":memory:")
    # query copied from protein_detective.db:powerfit_solutions()
    result = con.execute(
        """
                         SELECT
                         [x,y,z]::FLOAT[3] AS translation,
                         [a11, a12, a13, a21, a22, a23, a31, a32, a33]::FLOAT[9] AS rotation,
                         FROM read_csv(?, normalize_names=True)
                         """,
        (str(fn),),
    ).df()
    row = result.to_dict(orient="records")[0]
    return {"translation": row["translation"], "rotation": row["rotation"].reshape((3, 3))}


def test_fit_model(solution: dict[str, np.ndarray], tmp_path: Path) -> None:
    unfitted_model_file = Path(__file__).parent / "fixtures" / "KsgA.pdb"
    fitted_model_file = tmp_path / "fit_pd.pdb"

    translation = solution["translation"]
    rotation = solution["rotation"]

    fit_model(unfitted_model_file, translation, rotation, fitted_model_file)

    fitted_model = Structure.fromfile(str(fitted_model_file))
    expected_fitted_model_file = Path(__file__).parent / "fixtures" / "fit_1.pdb"
    expected_model = Structure.fromfile(str(expected_fitted_model_file))

    assert_array_almost_equal(
        # type: ignore[bad-argument-type]
        fitted_model.coor,
        # type: ignore[bad-argument-type]
        expected_model.coor,
        decimal=1,  # TODO check why so low needed
    )
