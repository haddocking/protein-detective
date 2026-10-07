from pathlib import Path

import pytest
from cyclopts import ValidationError
from rocrate.metadata import BASENAME
from rocrate.model.contextentity import ContextEntity
from rocrate.rocrate import ROCrate

from protein_detective.cli import app
from tests.helpers import cli, read_csv


@pytest.mark.parametrize("ncores", [-2, -1, 0])
def test_refine_cli_rejects_nonpositive_ncores(tmp_path: Path, fixed_structure_file: Path, ncores: int):
    with pytest.raises(ValidationError, match="Must be > 0"):
        app.parse_args(
            ["refine", "run", str(tmp_path), str(fixed_structure_file), "--ncores", str(ncores)],
            exit_on_error=False,
            print_error=False,
        )


@pytest.mark.parametrize("chains", [["A", "C"], ["A", "C", "A"]])
def test_refine_cli_accepts_fixed_chain_removal(tmp_path: Path, fixed_structure_file: Path, chains: list[str]):
    _, bound, _ = app.parse_args(
        ["refine", "run", str(tmp_path), str(fixed_structure_file)]
        + [token for chain in chains for token in ("--remove-fixed-chains", chain)],
        exit_on_error=False,
        print_error=False,
    )

    assert bound.arguments["remove_fixed_chains"] == {"A", "C"}


def test_run_accepts_independent_run_ids(session_with_powerfit_results: Path, fixed_structure_file: Path):
    _, bound, _ = app.parse_args(
        [
            "refine",
            "run",
            str(session_with_powerfit_results),
            str(fixed_structure_file),
            "--powerfit-run-id",
            "run_003",
            "--refine-run-id",
            "experiment",
            "--scheduler-address",
            "sequential",
        ],
        exit_on_error=False,
        print_error=False,
    )

    assert bound.arguments["powerfit_run_id"] == "run_003"
    assert bound.arguments["refine_run_id"] == "experiment"
    assert bound.arguments["scheduler_address"] == "sequential"


@pytest.fixture
def refinement_run(session_with_powerfit_results: Path) -> Path:
    run_dir = session_with_powerfit_results / "refine" / "experiment"
    run_dir.mkdir(parents=True)
    model_run = "refine/experiment/run_003/same_structure/fit_1.pdb"
    (run_dir / "io.csv").write_text(
        "refine_run_id,powerfit_run_id,fitted_model,refine_run_dir\n"
        f"experiment,run_003,powerfit/run_003/same_structure/fit_1.pdb,{model_run}\n"
    )
    return run_dir


def test_list_runs_options_and_read_only_crate(
    session_with_powerfit_results: Path, tmp_path: Path, refinement_run: Path
):
    options = "--refine-run-id experiment --rigidbody-sampling 10"
    fixed_structure = "fixed partner.pdb"
    crate = ROCrate()
    result = crate.add_file(refinement_run / "io.csv", dest_path="refine/experiment/io.csv")
    crate.add(
        ContextEntity(
            crate,
            f"protein-detective refine run 'session with spaces' '{fixed_structure}' {options}",
            properties={"@type": "CreateAction", "result": [result]},
        )
    )
    crate.add(
        ContextEntity(
            crate,
            "protein-detective meta session",
            properties={"@type": "CreateAction", "result": [result]},
        )
    )
    crate.write(session_with_powerfit_results)
    listing = tmp_path / "runs.csv"
    crate_bytes = (session_with_powerfit_results / BASENAME).read_bytes()

    cli(["refine", "list-runs", str(session_with_powerfit_results), "--output", str(listing)])

    assert (session_with_powerfit_results / BASENAME).read_bytes() == crate_bytes
    assert read_csv(listing) == [
        {
            "refine_run_id": "experiment",
            "run_dir": str(refinement_run),
            "fixed_structure": fixed_structure,
            "options": options,
        }
    ]


def test_list_runs_without_crate(session_with_powerfit_results: Path, tmp_path: Path, refinement_run: Path):
    listing = tmp_path / "runs.csv"

    cli(["refine", "list-runs", str(session_with_powerfit_results), "--output", str(listing)])

    assert not (session_with_powerfit_results / BASENAME).exists()
    assert read_csv(listing) == [
        {
            "refine_run_id": "experiment",
            "run_dir": str(refinement_run),
            "fixed_structure": "",
            "options": "",
        }
    ]
