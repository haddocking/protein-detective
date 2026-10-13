import csv
import json
import shutil
import warnings
from contextlib import chdir
from pathlib import Path

import duckdb
import pytest
from cyclopts.exceptions import ValidationError

from protein_detective.cli import app
from protein_detective.meta import capri_as_duckdb_ddl, create_meta_duckdb_file, refinements_io_as_duckdb_ddl
from protein_detective.refine.report import refinement_report
from tests.helpers import cli


def add_run(session: Path, clustered_refinement_results_paths: dict[str, Path], run_id: str = "experiment") -> Path:
    run = session / "refine" / run_id / "run_001" / "protein" / "fit_1.pdb"
    run.mkdir(parents=True)
    (run.parents[2] / "io.csv").write_text(
        "refine_run_id,powerfit_run_id,fitted_model,refine_run_dir\n"
        f"{run_id},run_001,powerfit/run_001/protein/fit_1.pdb,{run.relative_to(session)}\n"
    )
    stage = run / "8_caprieval"
    stage.mkdir()
    for key, table in (("models", "ss"), ("clusters", "clt")):
        shutil.copyfile(clustered_refinement_results_paths[key], stage / f"capri_{table}.tsv")
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


def test_cluster_members_metadata_and_compressed_paths(
    clustered_refinement_results_paths: dict[str, Path], tmp_path: Path
):
    run = add_run(tmp_path, clustered_refinement_results_paths)
    add_metadata(tmp_path)
    model = run / "6_mdref/mdref_9.pdb.gz"
    model.parent.mkdir()
    model.write_bytes(b"")
    results = refinement_report(tmp_path, top=2)
    assert len(results) == 8
    assert results["uniprot_accessions"].tolist() == ["P12345:Q67890"] * 8
    assert results["fitted_rank"].tolist() == [1] * 8
    assert results["cluster_id"].tolist() == [2, 2, 1, 1, 4, 4, 3, 3]
    assert results["population"].tolist() == [3] * 8
    assert results["cluster_score"].tolist() == [-121.192] * 2 + [-70.837] * 2 + [-63.228] * 2 + [-58.954] * 2
    assert results["cluster_score_std"].tolist() == [0] * 8
    assert results["model_score"].tolist() == [-121.192] * 2 + [-70.837] * 2 + [-63.228] * 2 + [-58.954] * 2
    assert results["model_rank"].tolist() == [1, 2] * 4
    assert results.iloc[0]["model_path"] == str(model.relative_to(tmp_path))


@pytest.mark.parametrize("top,expected", [(1, 5), (2, 10), (3, 15), (4, 15)])
def test_top_members_of_every_cluster(
    clustered_refinement_results_paths: dict[str, Path], tmp_path: Path, top: int, expected: int
):
    add_metadata(tmp_path)
    run = add_run(tmp_path, clustered_refinement_results_paths)
    stage = run / "8_caprieval"
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
    assert results.groupby("cluster_id")["model_rank"].apply(list).tolist() == [list(range(1, min(top, 3) + 1))] * 5
    assert results["uniprot_accessions"].tolist() == ["P12345:Q67890"] * expected


def test_capri_member_ranks(clustered_refinement_results_paths: dict[str, Path], tmp_path: Path):
    add_metadata(tmp_path)
    run = add_run(tmp_path, clustered_refinement_results_paths)
    (run / "8_caprieval/capri_ss.tsv").write_text(
        "model\tcaprieval_rank\tscore\tcluster_id\tmodel-cluster_ranking\n"
        "z.pdb\t1\t-9\t1\t1\na.pdb\t2\t-100\t1\t3\nc.pdb\t3\t-100\t1\t4\nb.pdb\t3\t-100\t1\t2\n"
    )
    results = refinement_report(tmp_path, top=2)
    assert [Path(model).name for model in results["model_path"]] == ["z.pdb.gz", "b.pdb.gz"]
    assert results["model_rank"].tolist() == [1, 2]


def test_multiple_runs_csv_and_partial_results(
    clustered_refinement_results_paths: dict[str, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    add_metadata(tmp_path)
    add_run(tmp_path, clustered_refinement_results_paths, "first")
    add_run(tmp_path, clustered_refinement_results_paths, "second")
    partial = add_run(tmp_path, clustered_refinement_results_paths, "partial")
    (partial / "8_caprieval").rename(partial / "7_caprieval")
    output = tmp_path / "report.csv"
    with pytest.warns(UserWarning, match="Excluded 1 incomplete") as caught:
        cli(["refine", "report", str(tmp_path), "--top", "2", "--output", str(output)])
    with output.open() as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 16
    assert "result_type" not in rows[0]
    assert {row["refine_run_id"] for row in rows} == {"first", "second"}
    assert {row["cluster_id"] for row in rows} == {"1", "2", "3", "4"}
    assert [int(row["model_rank"]) for row in rows] == [1, 2] * 8
    assert {row["population"] for row in rows} == {"3"}
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert str(partial.relative_to(tmp_path)) in str(caught[0].message)
    results = refinement_report(tmp_path, "first")
    assert len(results) == 4
    with pytest.raises(ValueError, match="Unknown refinement run ID"):
        refinement_report(tmp_path, "missing")


def test_stdout_is_csv_and_no_crate_write(
    clustered_refinement_results_paths: dict[str, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    add_metadata(tmp_path)
    add_run(tmp_path, clustered_refinement_results_paths)
    cli(["refine", "report", str(tmp_path)])
    captured = capsys.readouterr()
    rows = list(csv.DictReader(captured.out.splitlines()))
    assert len(rows) == 4
    assert rows[0]["cluster_id"] == "2"
    assert captured.err == ""
    assert not (tmp_path / "ro-crate-metadata.json").exists()


@pytest.mark.parametrize("top", [0, -1])
def test_invalid_top(tmp_path: Path, top: int):
    with pytest.raises(ValidationError):
        app.parse_args(["refine", "report", str(tmp_path), "--top", str(top)], exit_on_error=False, print_error=False)
    with pytest.raises(ValueError, match="positive integer"):
        refinement_report(tmp_path, top=top)


@pytest.fixture
def incomplete_session(clustered_refinement_results_paths: dict[str, Path], tmp_path: Path, state: str) -> Path:
    add_metadata(tmp_path)
    if state != "no_runs":
        run = add_run(tmp_path, clustered_refinement_results_paths)
        scores = run / "8_caprieval/capri_ss.tsv"
        if state == "missing_final":
            scores.unlink()
        else:
            scores.write_text("model\tcaprieval_rank\tscore\tcluster_id\tmodel-cluster_ranking\n")
    return tmp_path


@pytest.mark.parametrize("state", ["no_runs", "missing_final", "empty_scores"])
def test_no_complete_results_is_rejected_without_writing_csv(incomplete_session: Path, state: str):
    tmp_path = incomplete_session
    output = tmp_path / "report.csv"
    with pytest.raises(ValueError, match="No complete refinement results"):
        cli(["refine", "report", str(tmp_path), "--output", str(output)])
    assert not output.exists()


@pytest.fixture
def session_with_earlier_stages(clustered_refinement_results_paths: dict[str, Path], tmp_path: Path) -> Path:
    first = add_run(tmp_path, clustered_refinement_results_paths, "first")
    add_run(tmp_path, clustered_refinement_results_paths, "second")
    for stage in ("2_caprieval", "7_caprieval", "analysis/8_caprieval"):
        directory = first / stage
        directory.mkdir(parents=True)
        shutil.copyfile(clustered_refinement_results_paths["models"], directory / "capri_ss.tsv")
    return tmp_path


@pytest.fixture
def selected_refinement_metadata(session_with_earlier_stages: Path):
    with duckdb.connect() as con:
        for statement, params in refinements_io_as_duckdb_ddl(
            session_with_earlier_stages, "first"
        ) + capri_as_duckdb_ddl(session_with_earlier_stages, "first"):
            con.execute(statement, params)
        yield con


def test_final_stage_and_meta_selector(
    session_with_earlier_stages: Path, selected_refinement_metadata: duckdb.DuckDBPyConnection
):
    tmp_path = session_with_earlier_stages
    con = selected_refinement_metadata
    assert con.execute("SELECT DISTINCT refine_run_id FROM refinements_io").fetchall() == [("first",)]
    assert con.execute(
        "SELECT count(*) FROM refinements_capri_ss JOIN refinements_io USING (refine_run_dir)"
    ).fetchone() == (12,)
    # Unknown selector is rejected before a persistent database is created.
    with pytest.raises(ValueError, match="Unknown refinement run ID"):
        create_meta_duckdb_file(tmp_path, refine_run_id="unknown")
    assert not (tmp_path / "meta.duckdb").exists()
    command, arguments, _ = app.parse_args(
        ["meta", str(tmp_path), "--refine-run-id", "first", "--powerfit-run-id", "run_003"]
    )
    assert arguments.arguments["refine_run_id"] == "first"
    assert arguments.arguments["powerfit_run_id"] == "run_003"
    assert command.__name__ == "create_meta_duckdb"


def test_missing_metadata_row_preserves_members(clustered_refinement_results_paths: dict[str, Path], tmp_path: Path):
    add_run(tmp_path, clustered_refinement_results_paths)
    add_metadata(tmp_path)
    metadata = tmp_path / "powerfit/fittable_structures.csv"
    metadata.write_text(metadata.read_text().replace("protein,1abc", "other,1abc"))
    results = refinement_report(tmp_path, top=2)
    assert len(results) == 8
    assert results["uniprot_accessions"].tolist() == [""] * 8


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


def test_metadata_is_required_for_complete_refinement_runs(
    clustered_refinement_results_paths: dict[str, Path], tmp_path: Path
):
    add_run(tmp_path, clustered_refinement_results_paths)
    with pytest.raises(FileNotFoundError, match=r"fitted_models\.csv"):
        refinement_report(tmp_path)


def test_meta_cli_loads_only_selected_refinement(clustered_refinement_results_paths: dict[str, Path], tmp_path: Path):
    add_run(tmp_path, clustered_refinement_results_paths, "first")
    add_run(tmp_path, clustered_refinement_results_paths, "second")
    (tmp_path / "ro-crate-metadata.json").write_text(
        json.dumps(
            {
                "@graph": [
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
                    }
                ]
            }
        )
    )
    cli(["meta", str(tmp_path), "--refine-run-id", "second", "--powerfit-run-id", "run_003"])
    with duckdb.connect(str(tmp_path / "meta.duckdb"), read_only=True) as con:
        assert con.execute("SELECT DISTINCT refine_run_id FROM refinements_io").fetchall() == [("second",)]
        assert con.execute("SELECT DISTINCT powerfit_run_id FROM refinements_io").fetchall() == [("run_001",)]
        assert con.execute(
            "SELECT count(*) FROM refinements_capri_ss JOIN refinements_io USING (refine_run_dir)"
        ).fetchone() == (12,)


def test_each_fitted_input_has_independent_clusters(
    clustered_refinement_results_paths: dict[str, Path], tmp_path: Path
):
    add_metadata(tmp_path)
    first = add_run(tmp_path, clustered_refinement_results_paths)
    second = first.parents[2] / "run_003/protein/fit_2.pdb"
    shutil.copytree(first, second)
    with (first.parents[2] / "io.csv").open("a") as fh:
        fh.write(f"experiment,run_003,powerfit/run_003/protein/fit_2.pdb,{second.relative_to(tmp_path)}\n")
    results = refinement_report(tmp_path, top=2)
    assert results.groupby("powerfit_run_id")["model_rank"].apply(list).to_dict() == {
        "run_001": [1, 2] * 4,
        "run_003": [1, 2] * 4,
    }


def test_partial_tsv_is_not_loaded_when_cluster_output_is_missing(
    clustered_refinement_results_paths: dict[str, Path], tmp_path: Path
):
    add_metadata(tmp_path)
    add_run(tmp_path, clustered_refinement_results_paths, "complete")
    partial = add_run(tmp_path, clustered_refinement_results_paths, "partial")
    (partial / "8_caprieval/capri_clt.tsv").unlink()
    (partial / "8_caprieval/capri_ss.tsv").write_text("unfinished")
    with pytest.warns(UserWarning, match="Excluded 1 incomplete") as caught:
        results = refinement_report(tmp_path)
    assert len(results) == 4
    assert str(partial.relative_to(tmp_path)) in str(caught[0].message)


def test_empty_model_run_is_warned(clustered_refinement_results_paths: dict[str, Path], tmp_path: Path):
    add_metadata(tmp_path)
    add_run(tmp_path, clustered_refinement_results_paths, "complete")
    partial = add_run(tmp_path, clustered_refinement_results_paths, "partial")
    shutil.rmtree(partial)
    partial.mkdir()
    with pytest.warns(UserWarning, match="Excluded 1 incomplete") as caught:
        results = refinement_report(tmp_path)
    assert len(results) == 4
    assert str(partial.relative_to(tmp_path)) in str(caught[0].message)


@pytest.fixture
def session_without_io_indexes(
    clustered_refinement_results_paths: dict[str, Path], tmp_path: Path, index_contents: str | None
) -> Path:
    for run_id in ("first", "second"):
        run = add_run(tmp_path, clustered_refinement_results_paths, run_id)
        index = run.parents[2] / "io.csv"
        if index_contents is None:
            index.unlink()
        else:
            index.write_text(index_contents)
    add_metadata(tmp_path)
    return tmp_path


@pytest.mark.parametrize("index_contents", [None, "not a valid IO index"])
def test_report_discovers_results_without_io_indexes(session_without_io_indexes: Path, index_contents: str | None):
    tmp_path = session_without_io_indexes
    results = refinement_report(tmp_path, top=2)
    assert len(results) == 16
    assert set(results["refine_run_id"]) == {"first", "second"}
    assert results["uniprot_accessions"].tolist() == ["P12345:Q67890"] * 16
    assert results["fitted_model"].tolist() == ["powerfit/run_001/protein/fit_1.pdb"] * 16
    selected = refinement_report(tmp_path, "second", top=2)
    assert len(selected) == 8
    assert selected["refine_run_id"].tolist() == ["second"] * 8


def test_report_rejects_empty_run_without_io_index(tmp_path: Path):
    add_metadata(tmp_path)
    (tmp_path / "refine/empty").mkdir(parents=True)
    with pytest.raises(ValueError, match="No complete refinement results"):
        refinement_report(tmp_path, "empty")


def test_missing_scores_in_another_run_preserve_numeric_ranking(
    clustered_refinement_results_paths: dict[str, Path], tmp_path: Path
):
    add_metadata(tmp_path)
    valid = add_run(tmp_path, clustered_refinement_results_paths, "valid")
    missing = add_run(tmp_path, clustered_refinement_results_paths, "missing")
    (valid / "8_caprieval/capri_ss.tsv").write_text(
        "model\tcaprieval_rank\tscore\tcluster_id\tmodel-cluster_ranking\na.pdb\t1\t-9\t1\t2\nb.pdb\t2\t-100\t1\t1\n"
    )
    (missing / "8_caprieval/capri_ss.tsv").write_text(
        "model\tcaprieval_rank\tscore\tcluster_id\tmodel-cluster_ranking\nmissing.pdb\t1\t-\t-\t-\n"
    )
    with pytest.warns(UserWarning, match="Excluded 1 incomplete") as caught:
        results = refinement_report(tmp_path, top=2)
    assert results["model_score"].tolist() == [-100, -9]
    assert results["cluster_id"].tolist() == [1, 1]
    assert str(missing.relative_to(tmp_path)) in str(caught[0].message)


@pytest.mark.parametrize("cwd_location", ["parent", "session", "elsewhere"])
@pytest.mark.parametrize("absolute_session", [False, True])
def test_csv_paths_are_relative_to_cwd(
    clustered_refinement_results_paths: dict[str, Path], tmp_path: Path, cwd_location: str, absolute_session: bool
):
    session = tmp_path / "session with spaces"
    run = add_run(session, clustered_refinement_results_paths)
    add_metadata(session)
    fitted_model = session / "powerfit/run_001/protein/fit_1.pdb"
    fitted_model.parent.mkdir(parents=True)
    fitted_model.write_text("MODEL\nENDMDL\n")
    model = run / "6_mdref/mdref_9.pdb.gz"
    model.parent.mkdir()
    model.write_bytes(b"")
    cwd = {"parent": tmp_path, "session": session, "elsewhere": tmp_path / "elsewhere"}[cwd_location]
    cwd.mkdir(exist_ok=True)
    output = tmp_path / "report.csv"
    session_argument = session if absolute_session else session.relative_to(cwd, walk_up=True)
    with chdir(cwd):
        cli(["refine", "report", str(session_argument), "--output", str(output)])
        with output.open() as fh:
            row = next(csv.DictReader(fh))
        for column, expected_path in (
            ("model_path", model),
            ("fitted_model", fitted_model),
            ("refine_run_dir", run),
        ):
            assert row[column] == str(expected_path.relative_to(cwd, walk_up=True))
            assert not Path(row[column]).is_absolute()
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
    (first / "8_caprieval/capri_ss.tsv").write_text(
        "model\tcaprieval_rank\tscore\tcluster_id\tmodel-cluster_ranking\na.pdb\t1\t-100\t1\t1\nb.pdb\t2\t-95\t1\t2\nc.pdb\t3\t-90\t2\t1\n"
    )
    (first / "8_caprieval/capri_clt.tsv").write_text(
        "cluster_id\tcluster_rank\tn\tunder_eval\tscore\tscore_std\n1\t1\t2\tyes\t-97.5\t2.5\n2\t2\t1\tyes\t-90\t0\n"
    )
    (second / "8_caprieval/capri_ss.tsv").write_text(
        "model\tcaprieval_rank\tscore\tcluster_id\tmodel-cluster_ranking\nbest.pdb\t1\t-120\t1\t1\nz.pdb\t2\t-80\t2\t1\n"
    )
    (second / "8_caprieval/capri_clt.tsv").write_text(
        "cluster_id\tcluster_rank\tn\tunder_eval\tscore\tscore_std\n1\t1\t1\tyes\t-120\t0\n2\t2\t1\tyes\t-80\t0\n"
    )
    output = tmp_path / "report.csv"
    with warnings.catch_warnings(record=True) as caught:
        cli(["refine", "report", str(tmp_path), "--no-group-by-structure", "--top", str(top), "--output", str(output)])
    assert not caught
    with output.open() as fh:
        rows = list(csv.DictReader(fh))
    assert [float(row["model_score"]) for row in rows] == expected
    assert rows[0]["structure"] == "other_protein"
    assert rows[0]["cluster_id"] == "1"
    assert float(rows[0]["cluster_score"]) == -120
    selected = refinement_report(tmp_path, "first", top=2, group_by_structure=False)
    assert selected["model_score"].tolist() == [-100, -95]
    default = refinement_report(tmp_path)
    assert default["model_score"].tolist() == [-100, -90, -120, -80]
