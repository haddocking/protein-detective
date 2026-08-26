from pathlib import Path
from typing import Annotated

from cyclopts import Parameter, validators
from cyclopts.types import PositiveInt


def refine_with_haddock3(
    session_dir: Annotated[Path, Parameter(validator=validators.Path(file_okay=False, dir_okay=True, exists=True))],
    fixed_structure: Annotated[Path, Parameter(validator=validators.Path(file_okay=True, dir_okay=False, exists=True))],
    /, *,
    sampling: PositiveInt = 1000,
    top_clusters: PositiveInt = 5,
    powerfit_run_id: str | None = None,
):
    """Refine a structure with HADDOCK3.

    All fitted models will be refined against the fixed structure
    using HADDOCK3 rigidbody and molecular dynamics refinement.

    Args:
        session_dir: Session directory containing fitted PowerFit results
        fixed_structure: Path to the fixed structure to refine against.
            Can be a PDB or mmCIF file either gzipped or not.
            It will not be translated or rotated.
        sampling: Number of rigidbody samples.
        top_clusters: Number of top clusters to keep.
        powerfit_run_id: ID of the PowerFit run to refine.
            If not provided, all fitted models of all runs will be refined.
    """
    pass
