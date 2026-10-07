import shlex
from datetime import UTC, datetime
from pathlib import Path

from rocrate.metadata import BASENAME
from rocrate.rocrate import ROCrate

from protein_detective.refine.haddock import RefineOptions, generate_haddock3_config_body
from protein_detective.refine.provenance import refine_run_arguments_from_rocrate, write_refinement_ro_crate
from protein_detective.refine.run import create_refinement_run


def test_recorded_refinement_arguments_and_fixed_structure_origin(session_with_powerfit_results: Path, tmp_path: Path):
    assert refine_run_arguments_from_rocrate(session_with_powerfit_results) == {}

    run_dir = create_refinement_run(session_with_powerfit_results)
    original = tmp_path / "original fixed.pdb"
    original.write_text("END\n")
    fixed_structure = run_dir / "fixed_structure.pdb"
    fixed_structure.write_text("END\n")
    fitted = session_with_powerfit_results / "powerfit/run_001/same_structure/fit_1.pdb"
    model_run = run_dir / "run_001/same_structure/fit_1.pdb"
    model_run.mkdir(parents=True)
    options = RefineOptions(rigidbody_sampling=10)
    model_run.with_name("fit_1.pdb.cfg").write_text(
        generate_haddock3_config_body(
            run_dir=model_run, fitted_model=fitted, fixed_structure=fixed_structure, options=options
        )
    )
    io_csv = run_dir / "io.csv"
    io_csv.write_text(
        "refine_run_id,powerfit_run_id,fitted_model,refine_run_dir\n"
        f"{run_dir.name},run_001,{fitted.relative_to(session_with_powerfit_results)},{model_run.relative_to(session_with_powerfit_results)}\n"
    )

    write_refinement_ro_crate(
        session_dir=session_with_powerfit_results,
        start_time=datetime.now(tz=UTC),
        session_fixed_structure=fixed_structure,
        fixed_structure=original,
        refined=[(fitted, model_run)],
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

    assert tokens[:2] == ["--refine-run-id", run_dir.name]
    assert tokens[tokens.index("--rigidbody-sampling") + 1] == "10"
    assert tokens[tokens.index("--remove-fixed-chains") + 1] == "A"
    assert tokens[tokens.index("--powerfit-run-id") + 1] == "run_001"
    assert str(session_with_powerfit_results) not in tokens
    assert (session_with_powerfit_results / BASENAME).read_bytes() == crate_bytes

    fixed_item = ROCrate(session_with_powerfit_results).get(
        str(fixed_structure.relative_to(session_with_powerfit_results))
    )

    assert fixed_item is not None
    assert str(original) in fixed_item["description"]
