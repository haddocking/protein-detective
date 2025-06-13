from dataclasses import dataclass


@dataclass
class PowerfitSolution:
    rank: int
    cc: float
    fish_z: float
    rel_z: float
    x: float
    y: float
    z: float
    a11: float
    a12: float
    a13: float
    a21: float
    a22: float
    a23: float
    a31: float
    a32: float
    a33: float
    powerfit_run_id: int | None
    density_filter_id: int | None
    af_id: str | None
    uniprot_acc: str | None
    pdb_id: str | None
