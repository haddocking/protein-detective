from pathlib import Path

import pytest
from protein_quest.structure.formats import read_structure, write_structure

from protein_detective.refine.haddock import RefineOptions
from protein_detective.refine.run import (
    create_refinement_run,
    refine_with_haddock3,
)
from tests.helpers import assert_crate, assert_lines

# TODO use 6J5W instead of 9A2G and friends, use auth chain A as fitted and B as fixed


@pytest.mark.manual
def test_refine_with_haddock3_unclustered(tmp_path: Path, cif_9a2g: Path, cif_1gru_groes: Path):
    assert_refine_with_haddock3(tmp_path, cif_9a2g, cif_1gru_groes, RefineOptions(rigidbody_sampling=40, ncores=6))

# TODO assert clustered results aka no - as cluster_id and top
@pytest.mark.manual
def test_refine_with_haddock3_clustered(tmp_path: Path, cif_9a2g: Path, cif_1gru_groes: Path):
    assert_refine_with_haddock3(
        tmp_path,
        cif_9a2g,
        cif_1gru_groes,
        RefineOptions(rigidbody_sampling=80, ncores=14, fcc_clust_cutoff=0.2, top_clusters=80, top_models=80),
    )


def assert_refine_with_haddock3(tmp_path: Path, cif_9a2g: Path, cif_1gru_groes: Path, options: RefineOptions):
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

    expected_io_csv_lines = {
        "refine_run_id,powerfit_run_id,fitted_model,refine_run_dir",
        "refine_run_001,run_001,powerfit/run_001/fakestructure.cif/fit_1.pdb,refine/refine_run_001/run_001/fakestructure.cif/fit_1.pdb",
    }
    crate_input_ids = {
        "refine/refine_run_001/fixed_structure.pdb",
        "powerfit/run_001/fakestructure.cif/fit_1.pdb",
    }
    crate_output_ids = {
        "refine/refine_run_001/io.csv",
        "refine/refine_run_001/run_001/fakestructure.cif/fit_1.pdb/",
        "refine/refine_run_001/run_001/fakestructure.cif/fit_1.pdb.cfg",
    }

    refine_with_haddock3(
        session_dir,
        fixed_structure,
        refine_options=options,
        scheduler_address="sequential",
    )

    assert (session_dir / "refine/refine_run_001/run_001/fakestructure.cif/fit_1.pdb/6_mdref/mdref_1.pdb.gz").exists()
    assert (
        session_dir / "refine/refine_run_001/run_001/fakestructure.cif/fit_1.pdb/7_caprieval/capri_ss.tsv"
    ).is_file()
    assert_lines(session_dir / "refine/refine_run_001/io.csv", expected_io_csv_lines)
    config_file = session_dir / "refine/refine_run_001/run_001/fakestructure.cif/fit_1.pdb.cfg"
    assert f"clust_cutoff = {options.fcc_clust_cutoff}" in config_file.read_text()
    crate, actual_action = assert_crate(
        session_dir,
        input_ids=crate_input_ids,
        output_ids=crate_output_ids,
    )
    assert {i["@id"] for i in actual_action["object"]} == crate_input_ids
    assert {o["@id"] for o in actual_action["result"]} == crate_output_ids

    fixed_item = crate.get("refine/refine_run_001/fixed_structure.pdb")

    assert fixed_item is not None
    assert str(fixed_structure.resolve()) in fixed_item["description"]


def test_deleted_ids_and_exclusive_creation(session_with_powerfit_results: Path):
    (session_with_powerfit_results / "refine/refine_run_001").mkdir(parents=True)
    (session_with_powerfit_results / "refine/refine_run_003").mkdir()

    automatic_run = create_refinement_run(session_with_powerfit_results)
    custom_run = create_refinement_run(session_with_powerfit_results, "custom")

    assert automatic_run.name == "refine_run_004"
    assert custom_run.name == "custom"

    with pytest.raises(FileExistsError):
        create_refinement_run(session_with_powerfit_results, "custom")


@pytest.mark.parametrize("run_id", ["", ".", "..", "../escape", "/absolute", "a/b", "a\\b"])
def test_rejects_unsafe_ids_before_creating_directory(session_with_powerfit_results: Path, run_id: str):
    with pytest.raises(ValueError, match="Invalid refinement run ID"):
        create_refinement_run(session_with_powerfit_results, run_id)

    assert not (session_with_powerfit_results / "refine").exists()


def assert_refinement_rejected_before_creating_run(
    session_dir: Path, fixed_structure: Path, error: type[Exception], *, powerfit_run_id: str | None = None
):
    with pytest.raises(error):
        refine_with_haddock3(
            session_dir,
            fixed_structure,
            scheduler_address="sequential",
            powerfit_run_id=powerfit_run_id,
        )

    assert not (session_dir / "refine").exists()


def test_rejects_empty_selection_before_creating_run(session_with_powerfit_results: Path, fixed_structure_file: Path):
    (session_with_powerfit_results / "powerfit/fitted_models.csv").write_text("powerfit_run_id,fitted_model_file\n")

    assert_refinement_rejected_before_creating_run(session_with_powerfit_results, fixed_structure_file, ValueError)


def test_rejects_missing_input_before_creating_run(session_with_powerfit_results: Path, fixed_structure_file: Path):
    (session_with_powerfit_results / "powerfit/run_003/same_structure/fit_1.pdb").unlink()

    assert_refinement_rejected_before_creating_run(
        session_with_powerfit_results, fixed_structure_file, FileNotFoundError
    )


def test_rejects_unknown_source_before_creating_run(session_with_powerfit_results: Path, fixed_structure_file: Path):
    assert_refinement_rejected_before_creating_run(
        session_with_powerfit_results, fixed_structure_file, ValueError, powerfit_run_id="unknown"
    )
