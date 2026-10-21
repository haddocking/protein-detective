from pathlib import Path

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from protein_quest.structure.formats import read_structure, write_structure
from protein_quest.structure.metadata import structure_metadata
from protein_quest.structure.uniprot_extraction import structure2uniprot_accessions

from protein_detective.refine.haddock import RefineOptions
from protein_detective.refine.report import refinement_report
from protein_detective.refine.run import (
    create_refinement_run,
    refine_with_haddock3,
)
from tests.helpers import assert_crate, assert_lines


@pytest.mark.manual
def test_refine_with_haddock3_single_member_clusters(
    tmp_path: Path,
    fitted_structure: Path,
    known_structure: Path,
    single_member_cluster_refinement_results: dict[str, pd.DataFrame],
):
    session_dir = setup_refinement_session(tmp_path, fitted_structure)
    options = RefineOptions(rigidbody_sampling=10, ncores=6, top_clusters=4, top_models=1)

    refine_with_haddock3(session_dir, known_structure, refine_options=options, scheduler_address="sequential")

    assert_refinement_rocrate(session_dir, known_structure)
    assert_refinement_results(session_dir, single_member_cluster_refinement_results)


@pytest.mark.manual
def test_refine_with_haddock3_clustered(
    tmp_path: Path, fitted_structure: Path, known_structure: Path, clustered_refinement_results: dict[str, pd.DataFrame]
):
    session_dir = setup_refinement_session(tmp_path, fitted_structure)
    options = RefineOptions(
        rigidbody_sampling=10, ncores=6, top_clusters=4, top_models=1, water_refinement_sampling_factor=3
    )

    refine_with_haddock3(session_dir, known_structure, refine_options=options, scheduler_address="sequential")

    assert_refinement_rocrate(session_dir, known_structure)
    assert_refinement_results(session_dir, clustered_refinement_results)


def setup_refinement_session(tmp_path: Path, fitted_structure: Path) -> Path:
    session_dir = tmp_path / "session"
    session_dir.mkdir(parents=True)
    powerfit_root_dir = session_dir / "powerfit"
    powerfit_run_dir = powerfit_root_dir / "run_001" / "fakestructure.cif"
    powerfit_run_dir.mkdir(parents=True)
    fitted_model = powerfit_run_dir / "fit_1.pdb"
    # Need pdb format so convert
    write_structure(read_structure(fitted_structure), fitted_model)
    source_file = str(fitted_structure.relative_to(session_dir, walk_up=True))
    metadata = structure_metadata(fitted_structure)
    pd.DataFrame(
        [
            {
                "structure_file": source_file,
                "structure": powerfit_run_dir.name,
                "structure_id": metadata.id,
                "is_alphafold": metadata.is_alphafold,
                "uniprot_accessions": ":".join(sorted(structure2uniprot_accessions(fitted_structure))),
            }
        ]
    ).to_csv(powerfit_root_dir / "fittable_structures.csv", index=False)
    pd.DataFrame(
        [
            {
                "powerfit_run_id": "run_001",
                "structure": powerfit_run_dir.name,
                "rank": 1,
                "fitted_model_file": str(fitted_model.relative_to(session_dir)),
                "unfitted_model_file": source_file,
            }
        ]
    ).to_csv(powerfit_root_dir / "fitted_models.csv", index=False)

    return session_dir


def assert_refinement_results(session_dir: Path, expected_results: dict[str, pd.DataFrame]):
    baseline = session_dir / "refine/refine_run_001/run_001/fakestructure.cif/fit_1.pdb/baseline"
    baseline_scores = pd.read_csv(baseline / "2_caprieval/capri_ss.tsv", sep="\t", comment="#")
    report = refinement_report(session_dir)
    assert report["unrefined_score"].notna().all()
    assert report["unrefined_score"].eq(baseline_scores.iloc[0]["score"]).all()
    assert (baseline / "1_emscoring/emscoring_1.pdb.gz").is_file()
    assert (
        session_dir / "refine/refine_run_001/run_001/fakestructure.cif/fit_1.pdb/refinement/6_mdref/mdref_1.pdb.gz"
    ).exists()
    capri_dir = session_dir / "refine/refine_run_001/run_001/fakestructure.cif/fit_1.pdb/refinement/8_caprieval"
    results = {
        "models": pd.read_csv(capri_dir / "capri_ss.tsv", sep="\t", comment="#"),
        "clusters": pd.read_csv(capri_dir / "capri_clt.tsv", sep="\t", comment="#"),
    }
    # HADDOCK can exchange ranks between identical-score replicas.
    rank_columns = ["caprieval_rank", "model-cluster_ranking"]
    assert_frame_equal(
        results["models"].set_index("model").sort_index().drop(columns=rank_columns),
        expected_results["models"].set_index("model").sort_index().drop(columns=rank_columns),
        check_exact=True,
    )
    assert_frame_equal(
        results["models"].drop(columns="model"),
        expected_results["models"].drop(columns="model"),
        check_exact=True,
    )
    assert_frame_equal(results["clusters"], expected_results["clusters"], check_exact=True)


def assert_refinement_rocrate(session_dir: Path, known_structure: Path):
    expected_io_csv_lines = {
        "refine_run_id,powerfit_run_id,fitted_model,refine_run_dir",
        "refine_run_001,run_001,powerfit/run_001/fakestructure.cif/fit_1.pdb,refine/refine_run_001/run_001/fakestructure.cif/fit_1.pdb",
    }
    crate_input_ids = {
        "refine/refine_run_001/known_structure.pdb",
        "powerfit/run_001/fakestructure.cif/fit_1.pdb",
    }
    crate_output_ids = {
        "refine/refine_run_001/io.csv",
        "refine/refine_run_001/run_001/fakestructure.cif/fit_1.pdb/",
    }

    assert_lines(session_dir / "refine/refine_run_001/io.csv", expected_io_csv_lines)
    crate, actual_action = assert_crate(
        session_dir,
        input_ids=crate_input_ids,
        output_ids=crate_output_ids,
    )
    assert {i["@id"] for i in actual_action["object"]} == crate_input_ids
    assert {o["@id"] for o in actual_action["result"]} == crate_output_ids

    known_item = crate.get("refine/refine_run_001/known_structure.pdb")

    assert known_item is not None
    assert str(known_structure.resolve()) in known_item["description"]


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
    session_dir: Path, known_structure: Path, error: type[Exception], *, powerfit_run_id: str | None = None
):
    with pytest.raises(error):
        refine_with_haddock3(
            session_dir,
            known_structure,
            scheduler_address="sequential",
            powerfit_run_id=powerfit_run_id,
        )

    assert not (session_dir / "refine").exists()


def test_rejects_empty_selection_before_creating_run(session_with_powerfit_results: Path, known_structure_file: Path):
    (session_with_powerfit_results / "powerfit/fitted_models.csv").write_text("powerfit_run_id,fitted_model_file\n")

    assert_refinement_rejected_before_creating_run(session_with_powerfit_results, known_structure_file, ValueError)


def test_rejects_unknown_source_before_creating_run(session_with_powerfit_results: Path, known_structure_file: Path):
    assert_refinement_rejected_before_creating_run(
        session_with_powerfit_results, known_structure_file, ValueError, powerfit_run_id="unknown"
    )
