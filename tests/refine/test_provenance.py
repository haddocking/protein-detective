import shlex
from datetime import UTC, datetime
from pathlib import Path

from rocrate.metadata import BASENAME
from rocrate.rocrate import ROCrate

from protein_detective.refine.haddock import (
    RefineOptions,
    generate_haddock3_config_body,
    generate_unrefined_config_body,
)
from protein_detective.refine.provenance import refine_run_arguments_from_rocrate, write_refinement_ro_crate
from protein_detective.refine.run import create_refinement_run
from tests.helpers import cli_args


def test_recorded_refinement_arguments_and_fixed_structure_origin(session_with_powerfit_results: Path, tmp_path: Path):
    assert refine_run_arguments_from_rocrate(session_with_powerfit_results) == {}

    run_dir = create_refinement_run(session_with_powerfit_results)
    original = tmp_path / "original fixed.pdb"
    original.write_text("END\n")
    fixed_structure = run_dir / "fixed_structure.pdb"
    fixed_structure.write_text("END\n")
    fitted = session_with_powerfit_results / "powerfit/run_001/same_structure/fit_1.pdb"
    refinement_run = run_dir / "run_001/same_structure/fit_1.pdb"
    refinement_run.mkdir(parents=True)
    (refinement_run / "refinement").mkdir()
    baseline = refinement_run / "baseline"
    baseline.mkdir()
    complex_file = baseline / "fitted-and-fixed.pdb"
    complex_file.write_text("END\n")
    (baseline / "workflow.cfg").write_text(generate_unrefined_config_body(baseline, complex_file, 1))
    options = RefineOptions(rigidbody_sampling=10)
    (refinement_run / "refinement/workflow.cfg").write_text(
        generate_haddock3_config_body(
            run_dir=refinement_run / "refinement", fitted_model=fitted, fixed_structure=fixed_structure, options=options
        )
    )
    io_csv = run_dir / "io.csv"
    io_csv.write_text(
        "refine_run_id,powerfit_run_id,fitted_model,refine_run_dir\n"
        f"{run_dir.name},run_001,{fitted.relative_to(session_with_powerfit_results)},{refinement_run.relative_to(session_with_powerfit_results)}\n"
    )

    invocation_options = [
        "--rigidbody-sampling",
        "10",
        "--remove-fixed-chains",
        "A",
        "--powerfit-run-id",
        "run_001",
    ]
    with cli_args(["refine", "run", str(session_with_powerfit_results), str(original), *invocation_options]):
        write_refinement_ro_crate(
            session_dir=session_with_powerfit_results,
            start_time=datetime.now(tz=UTC),
            session_fixed_structure=fixed_structure,
            fixed_structure=original,
            refined=[(fitted, refinement_run)],
            io_csv=io_csv,
            options=options,
            remove_fixed_chains={"A"},
            powerfit_run_id="run_001",
        )

    crate_bytes = (session_with_powerfit_results / BASENAME).read_bytes()

    arguments = refine_run_arguments_from_rocrate(session_with_powerfit_results)

    assert list(arguments) == [run_dir.name]

    source, option_text = arguments[run_dir.name]

    assert source == str(original)

    tokens = shlex.split(option_text)

    assert tokens == invocation_options
    assert (session_with_powerfit_results / BASENAME).read_bytes() == crate_bytes

    fixed_item = ROCrate(session_with_powerfit_results).get(
        str(fixed_structure.relative_to(session_with_powerfit_results))
    )

    assert fixed_item is not None
    assert str(original) in fixed_item["description"]
    crate = ROCrate(session_with_powerfit_results)
    assert crate.get(f"{refinement_run.relative_to(session_with_powerfit_results)}/") is not None
    assert crate.get(str(complex_file.relative_to(session_with_powerfit_results))) is None
    assert crate.get(str((baseline / "workflow.cfg").relative_to(session_with_powerfit_results))) is None
