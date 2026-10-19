"""Dashboard joins, partial sessions, and safe local file resolution."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from protein_detective.dashboard.data import DashboardData, normalize_json, resolve_session_file


@pytest.fixture
def session(tmp_path: Path):
    root = tmp_path / "session"
    root.mkdir()
    with duckdb.connect(str(root / "meta.duckdb")) as con:
        con.execute("""
            CREATE TABLE combined_stats AS SELECT * FROM (VALUES
            ('combined_input/a.cif.gz', 'A', 'P12345', true, NULL::VARCHAR, false),
            ('combined_input/b.cif.gz', 'B', 'P12345', false, 'Too short', false)
            ) t(input_file, structure_id, uniprot_accession, passed, reason, is_alphafold);
            CREATE TABLE fittable_structures AS SELECT 'a.cif.gz' AS structure,
                'A' AS structure_id, 'P12345' AS uniprot_accessions, false AS is_alphafold;
            CREATE TABLE solutions AS SELECT * FROM (VALUES
                ('fit-a','a.cif.gz',1,0.8,0.9,1.0,'P12345',false),
                ('fit-a','a.cif.gz',2,0.7,0.8,0.9,'P12345',false),
                ('fit-b','a.cif.gz',1,0.9,1.0,1.1,'P12345',false)
            ) t(powerfit_run_id, structure, rank, cc, fishz, relz, uniprot_accessions, is_alphafold);
            CREATE TABLE fitted_models AS SELECT * FROM (VALUES
                ('fit-a','a.cif.gz',1,'powerfit/fit-a/a.cif.gz/fit_1.pdb'),
                ('fit-a','a.cif.gz',1,'powerfit/fit-a/a.cif.gz/fit_1.pdb')
            ) t(powerfit_run_id, structure, rank, fitted_model_file);
            CREATE TABLE refinements_runs AS SELECT * FROM (VALUES
                ('refine-a','--first', 'fixed.pdb'), ('refine-b','--second', 'fixed.pdb')
            ) t(refine_run_id, options, fixed_structure);
            CREATE TABLE refinements_io AS SELECT * FROM (VALUES
                ('refine-a','powerfit/fit-a/a.cif.gz/fit_1.pdb','refine/refine-a/input'),
                ('refine-b','powerfit/fit-a/a.cif.gz/fit_1.pdb','refine/refine-b/input')
            ) t(refine_run_id, fitted_model, refine_run_dir);
            CREATE TABLE refinements_capri_ss AS SELECT * FROM (VALUES
                ('refine-a','fit-a','a.cif.gz','refine/refine-a/input',1,1,-12.0,'refine/a.pdb.gz'),
                ('refine-a','fit-a','a.cif.gz','refine/refine-a/input',1,2,-11.0,'refine/a2.pdb.gz'),
                ('refine-b','fit-a','a.cif.gz','refine/refine-b/input',1,1,-25.0,'refine/b.pdb.gz')
            ) t(refine_run_id, powerfit_run_id, unfitted_structure, refine_run_dir,
                cluster_id, modelcluster_ranking, score, refined_structure_path);
            CREATE TABLE refinements_capri_clt AS SELECT * FROM (VALUES
                ('refine/refine-a/input',1,1,2,-11.5,0.5),
                ('refine/refine-b/input',1,2,1,-25.0,0.0)
            ) t(refine_run_dir, cluster_id, cluster_rank, n, score, score_std);
            CREATE TABLE refinements_baseline AS SELECT * FROM (VALUES
                ('refine/refine-a/input',-10.0),('refine/refine-b/input',-20.0)
            ) t(refine_run_dir, score);
            CREATE TABLE rocrate_create_actions AS SELECT
                'action' AS id, 'protein-detective powerfit run map.mrc 4 session' AS command,
                '2026-01-01' AS startTime, '2026-01-02' AS endTime;
            CREATE TABLE rocrate_objects AS SELECT
                'action' AS action_id, 'powerfit/fit-a/map.mrc' AS object_id;
            CREATE TABLE rocrate_results AS SELECT
                'action' AS action_id, 'powerfit/fit-a/' AS result_id;
            CREATE TABLE rocrate_inodes AS SELECT
                'powerfit/fit-a/map.mrc' AS id, 'File' AS type, 'Copied map' AS description;
        """)
    for path in (
        "powerfit/fit-a/map.mrc",
        "powerfit/fit-a/a.cif.gz/fit_1.pdb",
        "refine/a.pdb.gz",
        "refine/a2.pdb.gz",
        "refine/b.pdb.gz",
    ):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"example")
    return root


def test_structure_identity_includes_rejected_candidates(session: Path):
    data = DashboardData(session)
    candidates = data.candidates()
    assert [row["candidate_id"] for row in candidates] == ["a.cif.gz", "b.cif.gz"]
    assert candidates[1]["rejection_reason"] == "Too short"
    assert candidates[1]["filtering_status"] == "rejected"
    summary = data.summary()
    assert summary["candidate_structures"] == 2
    assert summary["uniprot_accessions"] == 1
    assert summary["filtering_passed"] == summary["filtering_rejected"] == 1
    assert summary["fitted_structures"] == 1
    assert summary["refined_structures"] == 3


def test_fitting_keeps_runs_and_unsaved_solutions_without_duplicate_models(session: Path):
    rows = DashboardData(session).fitting()
    assert len(rows) == 3
    assert len({row["id"] for row in rows}) == 3
    saved = next(row for row in rows if row["powerfit_run_id"] == "fit-a" and row["rank"] == 1)
    assert saved["viewer_available"]
    assert saved["density_path"] == "powerfit/fit-a/map.mrc"
    assert saved["relative_z"] == 1.0
    unsaved = next(row for row in rows if row["rank"] == 2)
    assert not unsaved["viewer_available"]
    assert unsaved["viewer_error"] == "Fitted structure not saved"


def test_refinement_joins_are_scoped_by_independent_run_and_input(session: Path):
    rows = DashboardData(session).refinements()
    assert len(rows) == 3
    first = next(row for row in rows if row["id"] == "refine/a.pdb.gz")
    second = next(row for row in rows if row["id"] == "refine/b.pdb.gz")
    assert first["fitted_rank"] == second["fitted_rank"] == 1
    assert first["powerfit_run_id"] == second["powerfit_run_id"] == "fit-a"
    assert first["refine_run_id"] != second["refine_run_id"]
    assert first["cluster_score"] == -11.5
    assert first["cluster_score_std"] == 0.5
    assert first["refined_score"] == -12
    assert first["baseline_score"] == -10
    assert first["score_change"] == -2
    assert second["baseline_score"] == -20
    assert second["score_change"] == -5
    assert second["cluster_rank"] == 2
    assert all(row["viewer_available"] for row in rows)


def test_density_association_uses_provenance_not_directory_scan(session: Path):
    (session / "powerfit/fit-a/map.mrc").unlink()
    (session / "powerfit/fit-a/unrelated.mrc").write_bytes(b"unrelated")
    row = next(row for row in DashboardData(session).fitting() if row["model_available"])
    assert not row["viewer_available"]
    assert "map.mrc" in row["viewer_error"]
    assert row["density_path"] == "powerfit/fit-a/map.mrc"


def test_ambiguous_density_disables_viewer(session: Path):
    with duckdb.connect(str(session / "meta.duckdb")) as con:
        con.execute("INSERT INTO rocrate_objects VALUES ('action', 'powerfit/fit-a/other.mrc')")
    row = next(row for row in DashboardData(session).fitting() if row["model_available"])
    assert not row["viewer_available"]
    assert "ambiguous" in row["viewer_error"]


def test_provenance_contains_chronological_commands_and_recorded_paths(session: Path):
    row = DashboardData(session).provenance()[0]
    assert row["command"].startswith("protein-detective powerfit run")
    assert row["start_time"] == "2026-01-01"
    assert row["inputs"] == ["powerfit/fit-a/map.mrc"]
    assert row["outputs"] == ["powerfit/fit-a/"]
    assert row["files"][0]["description"] == "Copied map"


def test_empty_and_search_only_sessions(tmp_path: Path):
    with duckdb.connect(str(tmp_path / "meta.duckdb")) as con:
        con.execute("CREATE TABLE alphafold AS SELECT 'AF-P1-F1' AS af_id, 'P1' AS uniprot_accession")
    data = DashboardData(tmp_path)
    assert data.summary()["fitting_status"] == "not_started"
    assert data.candidates()[0]["structure"] == "AF-P1-F1"
    assert data.fitting() == data.refinements() == data.provenance() == []
    assert "fitting_solutions" not in data.summary()
    (tmp_path / "powerfit/run").mkdir(parents=True)
    assert data.summary()["fitting_status"] == "incomplete"


def test_solutions_without_saved_models(session: Path):
    with duckdb.connect(str(session / "meta.duckdb")) as con:
        con.execute("DROP TABLE fitted_models")
    data = DashboardData(session)
    assert data.summary()["fitting_status"] == "structures_not_saved"
    assert all(not row["viewer_available"] for row in data.fitting())
    assert len(data.refinements()) == 3


def test_file_paths_resolve_after_relocation_and_reject_escapes(session: Path, tmp_path: Path):
    path = "powerfit/fit-a/map.mrc"
    expected = session / path
    assert resolve_session_file(session, path) == expected
    assert resolve_session_file(session, f"/old/location/session/{path}") == expected
    assert resolve_session_file(session, f"docs/session/{path}") == expected
    with pytest.raises(ValueError):
        resolve_session_file(session, "../outside")
    with pytest.raises(ValueError):
        resolve_session_file(session, "/etc/passwd")
    outside = tmp_path / "outside"
    outside.write_text("private")
    (session / "escape").symlink_to(outside)
    with pytest.raises(ValueError):
        resolve_session_file(session, "escape")
    with pytest.raises(FileNotFoundError):
        resolve_session_file(session, "missing.pdb")


def test_json_normalization_is_strict():
    value = normalize_json(
        {
            "nan": float("nan"),
            "inf": float("inf"),
            "decimal": Decimal("1.5"),
            "date": date(2026, 1, 1),
            "array": (1, 2),
            "path": Path("somewhere"),
        }
    )
    assert value == {
        "nan": None,
        "inf": None,
        "decimal": 1.5,
        "date": "2026-01-01",
        "array": [1, 2],
        "path": "somewhere",
    }
    json.dumps(value, allow_nan=False)


def test_search_structures_sharing_pdb_or_uniprot_are_independent(tmp_path: Path):
    with duckdb.connect(str(tmp_path / "meta.duckdb")) as con:
        con.execute("""
            CREATE TABLE fittable_structures AS SELECT * FROM (VALUES
                ('1abc_updated_A2A.cif.gz', '1ABC', false, 'P1'),
                ('AF-P1-F1-model_v6.cif.gz', 'AF-P1-F1', true, 'P1')
            ) t(structure, structure_id, is_alphafold, uniprot_accessions);
            CREATE TABLE pdbe AS SELECT * FROM (VALUES
                ('1ABC','P1','A'), ('1ABC','P1','B')
            ) t(pdb_id, uniprot_accession, chain);
            CREATE TABLE alphafold AS SELECT * FROM (VALUES
                ('AF-P1-F1','P1'), ('AF-P1-F2','P1')
            ) t(af_id, uniprot_accession);
        """)
    candidates = DashboardData(tmp_path).candidates()
    assert {row["candidate_id"] for row in candidates} == {
        "1abc_updated_A2A.cif.gz",
        "1ABC:B",
        "AF-P1-F1-model_v6.cif.gz",
        "AF-P1-F2",
    }


@pytest.mark.parametrize(
    "stage",
    [
        "powerfit",
        "refine",
        "combined_input",
        "combined_output",
        "downloads",
        "imported_structures",
        "secondary_structure",
        "single_chain",
        "uniprots_verified",
    ],
)
@pytest.mark.parametrize("prefix", ["/old/project/docs/tutorial-6j5w", "docs/tutorial-6j5w", "tutorial-6j5w"])
def test_recorded_paths_resolve_in_renamed_session(tmp_path: Path, stage: str, prefix: str):
    session = tmp_path / "renamed-session"
    relative = f"{stage}/run/model.pdb"
    expected = session / relative
    expected.parent.mkdir(parents=True)
    expected.write_bytes(b"model")
    assert resolve_session_file(session, f"{prefix}/{relative}") == expected
    assert resolve_session_file(session, relative) == expected


def test_renamed_session_rebasing_preserves_file_boundaries(tmp_path: Path):
    session = tmp_path / "renamed-session"
    session.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private.pdb").write_bytes(b"private")
    (session / "powerfit").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="outside"):
        resolve_session_file(session, "/old/tutorial-6j5w/powerfit/private.pdb")
    with pytest.raises(ValueError, match="Invalid"):
        resolve_session_file(session, "docs/tutorial-6j5w/powerfit/../../outside/private.pdb")
    with pytest.raises(ValueError, match="outside"):
        resolve_session_file(session, str(outside / "private.pdb"))
