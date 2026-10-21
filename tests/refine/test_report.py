import csv
import json
import shutil
from contextlib import chdir
from pathlib import Path

import duckdb
import pytest
from cyclopts.exceptions import ValidationError
from rocrate.model.contextentity import ContextEntity
from rocrate.rocrate import ROCrate

from protein_detective.cli import app
from protein_detective.meta import (
    execute_ddl_statements,
    refinements_baseline,
    refinements_capri_ss_as_duckdb_ddl,
    refinements_io_as_duckdb_ddl,
)
from protein_detective.refine.report import refinement_report
from tests.helpers import cli


def add_run(session: Path, clustered_refinement_results_paths: dict[str, Path], run_id: str = "experiment") -> Path:
    run = session / "refine" / run_id / "run_001" / "protein" / "fit_1.pdb"
    run.mkdir(parents=True)
    (run.parents[2] / "io.csv").write_text(
        "refine_run_id,powerfit_run_id,fitted_model,refine_run_dir\n"
        f"{run_id},run_001,powerfit/run_001/protein/fit_1.pdb,{run.relative_to(session)}\n"
    )
    stage = run / "refinement/8_caprieval"
    stage.mkdir(parents=True)
    for key, table in (("models", "ss"), ("clusters", "clt")):
        shutil.copyfile(clustered_refinement_results_paths[key], stage / f"capri_{table}.tsv")
    baseline = run / "baseline/2_caprieval"
    baseline.mkdir(parents=True)
    (baseline / "capri_ss.tsv").write_text("model\tscore\nfirst.pdb\t-10\n")
    crate = ROCrate(session) if (session / "ro-crate-metadata.json").exists() else ROCrate()
    result = crate.add(ContextEntity(crate, f"refine/{run_id}/", properties={"@type": "Dataset"}))
    crate.root_dataset.append_to("hasPart", result)
    crate.add_action(
        instrument={"@id": "protein-detective"},
        identifier=f"protein-detective refine run session known.pdb --refine-run-id {run_id}",
        result=[result],
    )
    crate.write(session)
    return run


def add_metadata(session: Path):
    powerfit = session / "powerfit"
    powerfit.mkdir()
    (powerfit / "fitted_models.csv").write_text(
        "powerfit_run_id,structure,rank,fitted_model_file\nrun_001,protein,1,powerfit/run_001/protein/fit_1.pdb\n"
    )
    (powerfit / "fittable_structures.csv").write_text(
        "structure,structure_id,uniprot_accessions,is_alphafold\nprotein,1abc,P12345:Q67890,false\n"
    )


@pytest.fixture
def session_with_baseline(clustered_refinement_results_paths: dict[str, Path], tmp_path: Path):
    add_metadata(tmp_path)
    run = add_run(tmp_path, clustered_refinement_results_paths, "first")
    add_run(tmp_path, clustered_refinement_results_paths, "second")
    baseline = run / "baseline/2_caprieval"
    scores = "# comment\nmodel\tscore\nfirst.pdb\t-42.5\n"
    (baseline / "capri_ss.tsv").write_text(scores)
    for stage in (run / "refinement/2_caprieval", baseline.parent / "analysis/2_caprieval"):
        stage.mkdir(parents=True)
        (stage / "capri_ss.tsv").write_text(scores.replace("-42.5", "-999"))
    return tmp_path


def test_unrefined_score_and_workflow_separation(session_with_baseline: Path):
    tmp_path = session_with_baseline
    run = tmp_path / "refine/first/run_001/protein/fit_1.pdb"
    results = refinement_report(tmp_path, top=2)
    assert results.loc[results["refine_run_id"] == "first", "unrefined_score"].tolist() == [-42.5] * 8
    assert results.loc[results["refine_run_id"] == "second", "unrefined_score"].tolist() == [-10.0] * 8
    assert (
        results["refined_score"].tolist()
        == [-123.367, -123.200, -75.926, -73.504, -70.407, -61.827, -63.228, -56.840] * 2
    )
    with duckdb.connect() as con:
        execute_ddl_statements(con, refinements_baseline(tmp_path))
        assert con.execute(
            "SELECT refine_run_dir, score FROM refinements_baseline ORDER BY refine_run_dir"
        ).fetchall() == [
            (str(run.relative_to(tmp_path)), -42.5),
            ("refine/second/run_001/protein/fit_1.pdb", -10.0),
        ]


def test_cluster_members_metadata_and_compressed_paths(
    clustered_refinement_results_paths: dict[str, Path], tmp_path: Path
):
    run = add_run(tmp_path, clustered_refinement_results_paths)
    add_metadata(tmp_path)
    model = run / "refinement/6_mdref/mdref_8.pdb.gz"
    model.parent.mkdir()
    model.write_bytes(b"")
    results = refinement_report(tmp_path, top=2)
    assert len(results) == 8
    assert results["uniprot_accessions"].tolist() == ["P12345:Q67890"] * 8
    assert results["fitted_rank"].tolist() == [1] * 8
    assert results["cluster_id"].tolist() == [2, 2, 1, 1, 3, 3, 4, 4]
    assert results["population"].tolist() == [3] * 8
    assert results["cluster_score"].tolist() == [-122.586] * 2 + [-73.422] * 2 + [-63.730] * 2 + [-53.309] * 2
    assert results["cluster_score_std"].tolist() == [0.989] * 2 + [2.078] * 2 + [4.865] * 2 + [9.861] * 2
    assert results["refined_score"].tolist() == [
        -123.367,
        -123.200,
        -75.926,
        -73.504,
        -70.407,
        -61.827,
        -63.228,
        -56.840,
    ]
    assert results["modelcluster_ranking"].tolist() == [1, 2] * 4
    assert results.iloc[0]["refined_structure_path"] == str(model)


@pytest.mark.parametrize("top,expected", [(1, 5), (2, 10), (3, 15), (4, 15)])
def test_top_members_of_every_cluster(
    clustered_refinement_results_paths: dict[str, Path], tmp_path: Path, top: int, expected: int
):
    add_metadata(tmp_path)
    run = add_run(tmp_path, clustered_refinement_results_paths)
    stage = run / "refinement/8_caprieval"
    (stage / "capri_ss.tsv").write_text(
        "model\tcaprieval_rank\tscore\tcluster_id\tmodel-cluster_ranking\n"
        + "".join(
            f"../6_mdref/model_{cluster}_{rank}.pdb\t{rank}\t{-100 + rank}\t{cluster}\t{rank}\n"
            for cluster in range(1, 6)
            for rank in (3, 1, 2)
        )
    )
    (stage / "capri_clt.tsv").write_text(
        "cluster_id\tcluster_rank\tn\tunder_eval\tscore\tscore_std\n"
        + "".join(f"{cluster}\t{cluster}\t3\tyes\t-98\t1\n" for cluster in range(1, 6))
    )
    results = refinement_report(tmp_path, top=top)
    assert len(results) == expected
    assert (
        results.groupby("cluster_id")["modelcluster_ranking"].apply(list).tolist()
        == [list(range(1, min(top, 3) + 1))] * 5
    )
    assert results["uniprot_accessions"].tolist() == ["P12345:Q67890"] * expected


def test_capri_member_ranks(clustered_refinement_results_paths: dict[str, Path], tmp_path: Path):
    add_metadata(tmp_path)
    run = add_run(tmp_path, clustered_refinement_results_paths)
    (run / "refinement/8_caprieval/capri_ss.tsv").write_text(
        "model\tcaprieval_rank\tscore\tcluster_id\tmodel-cluster_ranking\n"
        "../6_mdref/z.pdb\t1\t-9\t1\t1\n../6_mdref/a.pdb\t2\t-100\t1\t3\n../6_mdref/c.pdb\t3\t-100\t1\t4\n../6_mdref/b.pdb\t3\t-100\t1\t2\n"
    )
    results = refinement_report(tmp_path, top=2)
    assert [Path(model).name for model in results["refined_structure_path"]] == ["z.pdb.gz", "b.pdb.gz"]
    assert results["modelcluster_ranking"].tolist() == [1, 2]


def test_multiple_runs_csv(
    clustered_refinement_results_paths: dict[str, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    add_metadata(tmp_path)
    add_run(tmp_path, clustered_refinement_results_paths, "first")
    add_run(tmp_path, clustered_refinement_results_paths, "second")
    output = tmp_path / "report.csv"
    cli(["refine", "report", str(tmp_path), "--top", "2", "--output", str(output)])
    with output.open() as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 16
    assert "result_type" not in rows[0]
    assert {row["refine_run_id"] for row in rows} == {"first", "second"}
    assert {row["cluster_id"] for row in rows} == {"1", "2", "3", "4"}
    assert [int(row["modelcluster_ranking"]) for row in rows] == [1, 2] * 8
    assert {row["population"] for row in rows} == {"3"}
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    results = refinement_report(tmp_path, "first")
    assert len(results) == 4
    with pytest.raises(ValueError, match="Unknown refinement run ID"):
        refinement_report(tmp_path, "missing")


def test_stdout_is_csv_and_no_crate_write(
    clustered_refinement_results_paths: dict[str, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    add_metadata(tmp_path)
    add_run(tmp_path, clustered_refinement_results_paths)
    metadata = tmp_path / "ro-crate-metadata.json"
    original_metadata = metadata.read_bytes()
    cli(["refine", "report", str(tmp_path)])
    captured = capsys.readouterr()
    rows = list(csv.DictReader(captured.out.splitlines()))
    assert len(rows) == 4
    assert rows[0]["cluster_id"] == "2"
    assert captured.err == ""
    assert metadata.read_bytes() == original_metadata


@pytest.mark.parametrize("top", [0, -1])
def test_invalid_top(tmp_path: Path, top: int):
    with pytest.raises(ValidationError):
        app.parse_args(["refine", "report", str(tmp_path), "--top", str(top)], exit_on_error=False, print_error=False)
    with pytest.raises(ValueError, match="positive integer"):
        refinement_report(tmp_path, top=top)


@pytest.fixture
def session_with_earlier_stages(clustered_refinement_results_paths: dict[str, Path], tmp_path: Path) -> Path:
    first = add_run(tmp_path, clustered_refinement_results_paths, "first")
    add_run(tmp_path, clustered_refinement_results_paths, "second")
    for stage in ("refinement/2_caprieval", "refinement/7_caprieval", "refinement/analysis/8_caprieval"):
        directory = first / stage
        directory.mkdir(parents=True)
        shutil.copyfile(clustered_refinement_results_paths["models"], directory / "capri_ss.tsv")
    return tmp_path


def test_final_stage_metadata_loads_all_runs(session_with_earlier_stages: Path):
    with duckdb.connect() as con:
        execute_ddl_statements(
            con,
            refinements_io_as_duckdb_ddl(session_with_earlier_stages)
            + refinements_capri_ss_as_duckdb_ddl(session_with_earlier_stages),
        )
        assert con.execute("SELECT DISTINCT refine_run_id FROM refinements_io ORDER BY 1").fetchall() == [
            ("first",),
            ("second",),
        ]
        assert con.execute(
            "SELECT count(*) FROM refinements_capri_ss JOIN refinements_io USING (refine_run_dir)"
        ).fetchone() == (24,)


@pytest.fixture
def session_with_invalid_metadata(
    clustered_refinement_results_paths: dict[str, Path], tmp_path: Path, filename: str, contents: str | None
) -> Path:
    add_run(tmp_path, clustered_refinement_results_paths)
    add_metadata(tmp_path)
    path = tmp_path / "powerfit" / filename
    if contents is None:
        path.unlink()
    elif contents == "header_only":
        path.write_text(path.read_text().splitlines()[0] + "\n")
    else:
        path.write_text(contents)
    return tmp_path


@pytest.mark.parametrize("filename", ["fitted_models.csv", "fittable_structures.csv"])
@pytest.mark.parametrize("contents", [None, "", "header_only"])
def test_missing_or_empty_powerfit_file_is_rejected(
    session_with_invalid_metadata: Path, filename: str, contents: str | None
):
    error = FileNotFoundError if contents is None else ValueError
    with pytest.raises(error, match=filename):
        refinement_report(session_with_invalid_metadata)


def test_metadata_is_required_for_refinement_runs(clustered_refinement_results_paths: dict[str, Path], tmp_path: Path):
    add_run(tmp_path, clustered_refinement_results_paths)
    with pytest.raises(FileNotFoundError, match=r"fitted_models\.csv"):
        refinement_report(tmp_path)


def test_meta_cli_loads_all_refinements(clustered_refinement_results_paths: dict[str, Path], tmp_path: Path):
    add_run(tmp_path, clustered_refinement_results_paths, "first")
    add_run(tmp_path, clustered_refinement_results_paths, "second")
    (tmp_path / "ro-crate-metadata.json").write_text(
        json.dumps(
            {
                "@context": "https://w3id.org/ro/crate/1.1/context",
                "@graph": [
                    {
                        "@id": "ro-crate-metadata.json",
                        "@type": "CreativeWork",
                        "about": {"@id": "./"},
                        "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
                    },
                    {"@id": "./", "@type": "Dataset"},
                    {
                        "@id": "action",
                        "@type": "CreateAction",
                        "name": "refine run",
                        "description": "run",
                        "agent": {"@id": "agent"},
                        "instrument": {"@id": "tool"},
                        "object": [{"@id": "input"}],
                        "result": [{"@id": "output"}],
                        "startTime": "2026-10-12T10:00:00+00:00",
                        "endTime": "2026-10-12T10:01:00+00:00",
                    },
                ],
            }
        )
    )
    cli(["meta", str(tmp_path)])
    with duckdb.connect(str(tmp_path / "meta.duckdb"), read_only=True) as con:
        assert con.execute("SELECT DISTINCT refine_run_id FROM refinements_io ORDER BY 1").fetchall() == [
            ("first",),
            ("second",),
        ]
        assert con.execute("SELECT DISTINCT powerfit_run_id FROM refinements_io").fetchall() == [("run_001",)]
        assert con.execute(
            "SELECT count(*) FROM refinements_capri_ss JOIN refinements_io USING (refine_run_dir)"
        ).fetchone() == (24,)


def test_each_fitted_input_has_independent_clusters(
    clustered_refinement_results_paths: dict[str, Path], tmp_path: Path
):
    add_metadata(tmp_path)
    first = add_run(tmp_path, clustered_refinement_results_paths)
    second = first.parents[2] / "run_003/protein/fit_2.pdb"
    shutil.copytree(first, second)
    with (first.parents[2] / "io.csv").open("a") as fh:
        fh.write(f"experiment,run_003,powerfit/run_003/protein/fit_2.pdb,{second.relative_to(tmp_path)}\n")
    with (tmp_path / "powerfit/fitted_models.csv").open("a") as fh:
        fh.write("run_003,protein,2,powerfit/run_003/protein/fit_2.pdb\n")
    results = refinement_report(tmp_path, top=2)
    assert results.groupby("powerfit_run_id")["modelcluster_ranking"].apply(list).to_dict() == {
        "run_001": [1, 2] * 4,
        "run_003": [1, 2] * 4,
    }


def test_malformed_tsv_raises(clustered_refinement_results_paths: dict[str, Path], tmp_path: Path):
    add_metadata(tmp_path)
    run = add_run(tmp_path, clustered_refinement_results_paths)
    (run / "refinement/8_caprieval/capri_ss.tsv").write_text("invalid")
    with pytest.raises(duckdb.Error):
        refinement_report(tmp_path)


def test_report_uses_io_mapping(session_with_baseline: Path):
    session = session_with_baseline
    index = session / "refine/first/io.csv"
    index.write_text(
        index.read_text().replace("powerfit/run_001/protein/fit_1.pdb", "powerfit/run_001/protein/renamed.pdb")
    )
    with (session / "powerfit/fitted_models.csv").open("a") as fh:
        fh.write("run_001,protein,2,powerfit/run_001/protein/renamed.pdb\n")

    results = refinement_report(session, top=2)
    assert len(results) == 16
    assert (
        results.loc[results["refine_run_id"] == "first", "fitted_model"].tolist()
        == [str(session / "powerfit/run_001/protein/renamed.pdb")] * 8
    )
    assert results.loc[results["refine_run_id"] == "first", "fitted_rank"].tolist() == [2] * 8
    selected = refinement_report(session, "second", top=2)
    assert len(selected) == 8
    assert selected["refine_run_id"].tolist() == ["second"] * 8


def test_report_uses_recorded_runs(clustered_refinement_results_paths: dict[str, Path], tmp_path: Path):
    add_metadata(tmp_path)
    run = add_run(tmp_path, clustered_refinement_results_paths, "recorded")
    shutil.copytree(run.parents[2], tmp_path / "refine/unrecorded")
    index = tmp_path / "refine/unrecorded/io.csv"
    index.write_text(index.read_text().replace("recorded", "unrecorded"))

    results = refinement_report(tmp_path)
    assert results["refine_run_id"].tolist() == ["recorded"] * 4
    with pytest.raises(ValueError, match="Unknown refinement run ID: unrecorded"):
        refinement_report(tmp_path, "unrecorded")


def test_missing_scores_in_another_run_preserve_numeric_ranking(
    clustered_refinement_results_paths: dict[str, Path], tmp_path: Path
):
    add_metadata(tmp_path)
    valid = add_run(tmp_path, clustered_refinement_results_paths, "valid")
    missing = add_run(tmp_path, clustered_refinement_results_paths, "missing")
    (valid / "refinement/8_caprieval/capri_ss.tsv").write_text(
        "model\tcaprieval_rank\tscore\tcluster_id\tmodel-cluster_ranking\n../6_mdref/a.pdb\t1\t-9\t1\t2\n../6_mdref/b.pdb\t2\t-100\t1\t1\n"
    )
    (missing / "refinement/8_caprieval/capri_ss.tsv").write_text(
        "model\tcaprieval_rank\tscore\tcluster_id\tmodel-cluster_ranking\n../6_mdref/missing.pdb\t1\t-\t-\t-\n"
    )
    results = refinement_report(tmp_path, top=2)
    assert results["refined_score"].tolist() == [-100, -9]
    assert results["cluster_id"].tolist() == [1, 1]


@pytest.mark.parametrize("cwd_location", ["parent", "session", "elsewhere"])
@pytest.mark.parametrize("absolute_session", [False, True])
def test_report_paths_preserve_session_argument(
    clustered_refinement_results_paths: dict[str, Path], tmp_path: Path, cwd_location: str, absolute_session: bool
):
    session = tmp_path / "session with spaces"
    run = add_run(session, clustered_refinement_results_paths)
    add_metadata(session)
    fitted_model = session / "powerfit/run_001/protein/fit_1.pdb"
    fitted_model.parent.mkdir(parents=True)
    fitted_model.write_text("MODEL\nENDMDL\n")
    model = run / "refinement/6_mdref/mdref_8.pdb.gz"
    model.parent.mkdir()
    model.write_bytes(b"")
    cwd = {"parent": tmp_path, "session": session, "elsewhere": tmp_path / "elsewhere"}[cwd_location]
    cwd.mkdir(exist_ok=True)
    output = tmp_path / "report.csv"
    session_argument = session if absolute_session else session.relative_to(cwd, walk_up=True)
    with chdir(cwd):
        results = refinement_report(session_argument)
        cli(["refine", "report", str(session_argument), "--output", str(output)])
        with output.open() as fh:
            row = next(csv.DictReader(fh))
        for column, expected_path in (
            ("refined_structure_path", model),
            ("fitted_model", fitted_model),
            ("refine_run_dir", run),
        ):
            assert results.iloc[0][column] == row[column]
            assert row[column] == f"{session_argument}/{expected_path.relative_to(session)}"
            assert Path(row[column]).is_absolute() == absolute_session
            assert Path(row[column]).resolve() == expected_path


@pytest.mark.parametrize("top,expected", [(1, [-120]), (3, [-120, -100, -95]), (20, [-120, -100, -95, -90, -80])])
def test_no_group_by_structure_selects_best_models_overall(
    clustered_refinement_results_paths: dict[str, Path], tmp_path: Path, top: int, expected: list[int]
):
    add_metadata(tmp_path)
    first = add_run(tmp_path, clustered_refinement_results_paths, "first")
    second = add_run(tmp_path, clustered_refinement_results_paths, "second")
    second.parent.rename(second.parent.with_name("other_protein"))
    second = second.parent.with_name("other_protein") / second.name
    index = tmp_path / "refine/second/io.csv"
    index.write_text(index.read_text().replace("/protein/", "/other_protein/"))
    with (tmp_path / "powerfit/fitted_models.csv").open("a") as fh:
        fh.write("run_001,other_protein,1,powerfit/run_001/other_protein/fit_1.pdb\n")
    with (tmp_path / "powerfit/fittable_structures.csv").open("a") as fh:
        fh.write("other_protein,2abc,Q12345,false\n")
    (first / "refinement/8_caprieval/capri_ss.tsv").write_text(
        "model\tcaprieval_rank\tscore\tcluster_id\tmodel-cluster_ranking\n../6_mdref/a.pdb\t1\t-100\t1\t1\n../6_mdref/b.pdb\t2\t-95\t1\t2\n../6_mdref/c.pdb\t3\t-90\t2\t1\n"
    )
    (first / "refinement/8_caprieval/capri_clt.tsv").write_text(
        "cluster_id\tcluster_rank\tn\tunder_eval\tscore\tscore_std\n1\t1\t2\tyes\t-97.5\t2.5\n2\t2\t1\tyes\t-90\t0\n"
    )
    (second / "refinement/8_caprieval/capri_ss.tsv").write_text(
        "model\tcaprieval_rank\tscore\tcluster_id\tmodel-cluster_ranking\n../6_mdref/best.pdb\t1\t-120\t1\t1\n../6_mdref/z.pdb\t2\t-80\t2\t1\n"
    )
    (second / "refinement/8_caprieval/capri_clt.tsv").write_text(
        "cluster_id\tcluster_rank\tn\tunder_eval\tscore\tscore_std\n1\t1\t1\tyes\t-120\t0\n2\t2\t1\tyes\t-80\t0\n"
    )
    output = tmp_path / "report.csv"
    cli(["refine", "report", str(tmp_path), "--no-group-by-structure", "--top", str(top), "--output", str(output)])
    with output.open() as fh:
        rows = list(csv.DictReader(fh))
    assert [float(row["refined_score"]) for row in rows] == expected
    assert rows[0]["structure"] == "other_protein"
    assert rows[0]["cluster_id"] == "1"
    assert float(rows[0]["cluster_score"]) == -120
    selected = refinement_report(tmp_path, "first", top=2, group_by_structure=False)
    assert selected["refined_score"].tolist() == [-100, -95]
    default = refinement_report(tmp_path)
    assert default["refined_score"].tolist() == [-100, -90, -120, -80]
