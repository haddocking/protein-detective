from pathlib import Path

import duckdb
import numpy as np
import pytest

from protein_detective.powerfit.solution import fit_pdb


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


def test_fit_pdb(solution: dict[str, np.ndarray], tmp_path: Path) -> None:
    input_pdb_file = Path(__file__).parent / "fixtures" / "KsgA.pdb"
    # TODO atomium parses KsgA.pdb as <Model (0 chains, 252 ligands)> not as <Model (1 chains, 0 ligands)>
    # maybe switch from atomium to powerfit implementation?
    result_pdb_file = tmp_path / "fit_pd.pdb"

    translation = solution["translation"]
    rotation = solution["rotation"]

    fit_pdb(input_pdb_file, translation, rotation, result_pdb_file)

    expected_pdb_file = Path(__file__).parent / "fixtures" / "fit_1.pdb"
    with result_pdb_file.open() as rfh, expected_pdb_file.open() as efh:
        result = rfh.readlines()
        expected = efh.readlines()
        # TODO assert whole file, not just one line
        assert result[42] == expected[42]
