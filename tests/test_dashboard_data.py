"""Dashboard joins, partial sessions, and safe local file resolution."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from protein_detective.dashboard.data import DashboardData, _normalize_json, _resolve_session_file


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
            CREATE TABLE powerfit_runs AS SELECT * FROM (VALUES
                ('fit-a', 'powerfit/fit-a/map.mrc'), ('fit-b', NULL)
            ) t(powerfit_run_id, used_target);
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
                ('refine-a','--first', 'known.pdb'), ('refine-b','--second', 'known.pdb')
            ) t(refine_run_id, options, known_structure);
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
    assert saved["model_absolute_path"] == str(session / saved["model_path"])
    assert saved["density_absolute_path"] == str(session / saved["density_path"])
    assert saved["relative_z"] == 1.0
    unsaved = next(row for row in rows if row["rank"] == 2)
    assert not unsaved["viewer_available"]
    assert unsaved["viewer_error"] == "Fitted structure not saved"
    assert unsaved["model_absolute_path"] is None
    assert unsaved["density_absolute_path"] == str(session / unsaved["density_path"])


def test_refinement_joins_are_scoped_by_independent_run_and_input(session: Path):
    rows = DashboardData(session).refinements()
    assert len(rows) == 3
    first = next(row for row in rows if row["id"] == "refine/a.pdb.gz")
    second = next(row for row in rows if row["id"] == "refine/b.pdb.gz")
    assert first["model_absolute_path"] == str(session / "refine/a.pdb.gz")
    assert first["density_absolute_path"] == str(session / "powerfit/fit-a/map.mrc")
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
    assert row["density_absolute_path"] is None


def test_ambiguous_density_disables_viewer(session: Path):
    with duckdb.connect(str(session / "meta.duckdb")) as con:
        con.execute("UPDATE powerfit_runs SET used_target = NULL WHERE powerfit_run_id = 'fit-a'")
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
    # Browsing uses recorded metadata, without scanning newly created directories.
    assert data.summary()["fitting_status"] == "not_started"
    with duckdb.connect(str(tmp_path / "meta.duckdb")) as con:
        con.execute("CREATE TABLE powerfit_runs AS SELECT 'run' AS powerfit_run_id")
    assert data.summary()["fitting_status"] == "incomplete"


def test_solutions_without_saved_models(session: Path):
    with duckdb.connect(str(session / "meta.duckdb")) as con:
        con.execute("DROP TABLE fitted_models")
    data = DashboardData(session)
    assert data.summary()["fitting_status"] == "structures_not_saved"
    assert all(not row["viewer_available"] for row in data.fitting())
    assert data.refinements() == []


def test_file_paths_resolve_after_relocation_and_reject_escapes(session: Path, tmp_path: Path):
    path = "powerfit/fit-a/map.mrc"
    expected = session / path
    assert _resolve_session_file(session, path) == expected
    assert _resolve_session_file(session, f"/old/location/session/{path}") == expected
    assert _resolve_session_file(session, f"docs/session/{path}") == expected
    with pytest.raises(ValueError):
        _resolve_session_file(session, "../outside")
    with pytest.raises(ValueError):
        _resolve_session_file(session, "/etc/passwd")
    outside = tmp_path / "outside"
    outside.write_text("private")
    (session / "escape").symlink_to(outside)
    with pytest.raises(ValueError):
        _resolve_session_file(session, "escape")
    with pytest.raises(FileNotFoundError):
        _resolve_session_file(session, "missing.pdb")


def test_json_normalization_is_strict():
    value = _normalize_json(
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
                ('renamed-chain.cif.gz', '1ABC', false, 'P1'),
                ('AF-P1-F1-model_v6.cif.gz', 'AF-P1-F1', true, 'P1')
            ) t(structure, structure_id, is_alphafold, uniprot_accessions);
            CREATE TABLE pdbe_retrieve_stats AS SELECT '1abc' AS pdb_id, 'downloads/renamed.cif.gz' AS output_file;
            CREATE TABLE uniprots_verified_stats AS SELECT
                'downloads/renamed.cif.gz' AS input_file, 'uniprots_verified/renamed.cif.gz' AS output_file;
            CREATE TABLE single_chain_stats AS SELECT * FROM (VALUES
                ('uniprots_verified/renamed.cif.gz', 'A', 'A', true, NULL, 'single_chain/arbitrary.cif.gz'),
                ('uniprots_verified/renamed.cif.gz', 'B', 'A', true, NULL, 'single_chain/other.cif.gz')
            ) t(input_file, chain2keep, output_chain, passed, discard_reason, output_file);
            CREATE TABLE merge_structure_files AS SELECT * FROM (VALUES
                ('single_chain/arbitrary.cif.gz', 'combined_input/renamed-chain.cif.gz'),
                ('single_chain/other.cif.gz', 'combined_input/rejected-chain.cif.gz')
            ) t(source, target);
            CREATE TABLE combined_stats AS SELECT 'combined_input/rejected-chain.cif.gz' AS input_file,
                '1ABC' AS structure_id, false AS is_alphafold, false AS passed, 'Too short' AS reason;
            CREATE TABLE pdbe AS SELECT * FROM (VALUES
                ('1ABC','P1','A'), ('1ABC','P1','B'), ('1ABC','P1','C')
            ) t(pdb_id, uniprot_accession, chain);
            CREATE TABLE alphafold AS SELECT * FROM (VALUES
                ('AF-P1-F1','P1'), ('AF-P1-F2','P1')
            ) t(af_id, uniprot_accession);
        """)
    candidates = DashboardData(tmp_path).candidates()
    assert {row["candidate_id"] for row in candidates} == {
        "renamed-chain.cif.gz",
        "rejected-chain.cif.gz",
        "1ABC:C",
        "AF-P1-F1-model_v6.cif.gz",
        "AF-P1-F2",
    }
    rejected = next(row for row in candidates if row["candidate_id"] == "rejected-chain.cif.gz")
    assert rejected["chain"] == "B"
    assert rejected["filtering_status"] == "rejected"
    assert rejected["rejection_reason"] == "Too short"


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
    assert _resolve_session_file(session, f"{prefix}/{relative}") == expected
    assert _resolve_session_file(session, relative) == expected


def test_renamed_session_rebasing_preserves_file_boundaries(tmp_path: Path):
    session = tmp_path / "renamed-session"
    session.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private.pdb").write_bytes(b"private")
    (session / "powerfit").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="outside"):
        _resolve_session_file(session, "/old/tutorial-6j5w/powerfit/private.pdb")
    with pytest.raises(ValueError, match="Invalid"):
        _resolve_session_file(session, "docs/tutorial-6j5w/powerfit/../../outside/private.pdb")
    with pytest.raises(ValueError, match="outside"):
        _resolve_session_file(session, str(outside / "private.pdb"))


def test_single_chain_candidates_retain_rejected_and_unfiltered_chains(tmp_path: Path):
    with duckdb.connect(str(tmp_path / "meta.duckdb")) as con:
        con.execute("""
            CREATE TABLE pdbe_retrieve_stats AS SELECT '1ABC' AS pdb_id, 'downloads/input.cif.gz' AS output_file;
            CREATE TABLE single_chain_stats AS SELECT * FROM (VALUES
                ('downloads/input.cif.gz', 'A', 'A', true, NULL, 'single_chain/renamed.cif.gz'),
                ('downloads/input.cif.gz', 'B', 'A', false, 'Missing chain', NULL)
            ) t(input_file, chain2keep, output_chain, passed, discard_reason, output_file);
            CREATE TABLE pdbe AS SELECT * FROM (VALUES
                ('1ABC','P1','A'), ('1ABC','P2','B'), ('1ABC','P3','C')
            ) t(pdb_id, uniprot_accession, chain);
        """)
    candidates = {row["candidate_id"]: row for row in DashboardData(tmp_path).candidates()}
    assert set(candidates) == {"renamed.cif.gz", "1ABC:B", "1ABC:C"}
    assert candidates["renamed.cif.gz"]["chain"] == "A"
    assert candidates["renamed.cif.gz"]["uniprot_accessions"] == "P1"
    assert candidates["1ABC:B"]["rejection_reason"] == "Missing chain"
    assert candidates["1ABC:B"]["filtering_status"] == "rejected"
    assert candidates["1ABC:C"]["filtering_status"] == "not recorded"


def test_candidates_without_chain_mapping_do_not_guess_chain_from_filename(tmp_path: Path):
    with duckdb.connect(str(tmp_path / "meta.duckdb")) as con:
        con.execute("""
            CREATE TABLE fittable_structures AS SELECT '1abc_updated_A2A.cif.gz' AS structure,
                '1ABC' AS structure_id, false AS is_alphafold;
            CREATE TABLE pdbe AS SELECT '1ABC' AS pdb_id, 'P1' AS uniprot_accession, 'A' AS chain;
        """)
    assert {row["candidate_id"] for row in DashboardData(tmp_path).candidates()} == {
        "1abc_updated_A2A.cif.gz",
        "1ABC:A",
    }


@pytest.mark.parametrize("structure_id", ["P1", "AF-P1-F2"])
def test_accession_only_alphafold_search_does_not_match_another_fragment(tmp_path: Path, structure_id: str):
    with duckdb.connect(str(tmp_path / "meta.duckdb")) as con:
        con.execute(
            "CREATE TABLE fittable_structures AS SELECT 'AF-P1-F2-model_v6.cif.gz' AS structure, "
            "$structure_id AS structure_id, true AS is_alphafold",
            {"structure_id": structure_id},
        )
        con.execute("CREATE TABLE alphafold AS SELECT 'P1' AS af_id, 'P1' AS uniprot_accession")
    assert {row["candidate_id"] for row in DashboardData(tmp_path).candidates()} == {"AF-P1-F2-model_v6.cif.gz", "P1"}
    with duckdb.connect(str(tmp_path / "meta.duckdb")) as con:
        con.execute("INSERT INTO fittable_structures VALUES ('AF-P1-F1-model_v6.cif.gz', 'P1', true)")
    assert {row["candidate_id"] for row in DashboardData(tmp_path).candidates()} == {
        "AF-P1-F2-model_v6.cif.gz",
        "AF-P1-F1-model_v6.cif.gz",
    }


def test_legacy_metadata_without_runs_keeps_scores_and_disables_viewer(session: Path):
    with duckdb.connect(str(session / "meta.duckdb")) as con:
        con.execute("DROP TABLE powerfit_runs")
    data = DashboardData(session)
    assert len(data.fitting()) == 3
    assert data.refinements() == []
    assert all(not row["viewer_available"] for row in data.fitting())
    assert data.summary()["powerfit_runs"] == ["fit-a", "fit-b"]


def test_candidates_merge_stage_measurements_without_losing_rejected_or_unfitted_rows(tmp_path: Path):
    with duckdb.connect(str(tmp_path / "meta.duckdb")) as con:
        con.execute("""
            CREATE TABLE combined_stats AS SELECT * FROM (VALUES
                ('combined_input/a.cif.gz', 'P1', true, NULL, 3.0),
                ('combined_input/b.cif.gz', 'P2', false, 'Too short', 4.0)
            ) t(input_file, uniprot_accession, passed, reason, resolution);
            CREATE TABLE secondary_structure_stats AS SELECT 'secondary_structure/a.cif.gz' AS input_file,
                false AS passed, 'Insufficient helices' AS reason, 0.2 AS helix_fraction;
            CREATE TABLE fittable_structures AS SELECT 'c.cif.gz' AS structure,
                'P3:P4' AS uniprot_accessions, true AS is_alphafold;
        """)
        before = con.execute("SHOW TABLES").fetchall()
    rows = {row["candidate_id"]: row for row in DashboardData(tmp_path).candidates()}
    assert set(rows) == {"a.cif.gz", "b.cif.gz", "c.cif.gz"}
    assert rows["a.cif.gz"]["filtering_status"] == "rejected"
    assert rows["a.cif.gz"]["rejection_reason"] == "Insufficient helices"
    assert rows["a.cif.gz"]["resolution"] == 3.0
    assert rows["a.cif.gz"]["helix_fraction"] == 0.2
    assert rows["b.cif.gz"]["rejection_reason"] == "Too short"
    assert rows["c.cif.gz"]["uniprot_accessions"] == "P3:P4"
    assert rows["c.cif.gz"]["filtering_status"] == "not recorded"
    with duckdb.connect(str(tmp_path / "meta.duckdb"), read_only=True) as con:
        assert con.execute("SHOW TABLES").fetchall() == before


def test_alphafold_retrieval_mapping_matches_renamed_output_without_conflating_fragments(tmp_path: Path):
    with duckdb.connect(str(tmp_path / "meta.duckdb")) as con:
        con.execute("""
            CREATE TABLE alphafold AS SELECT * FROM (VALUES
                ('P1', 'P1'), ('AF-P1-F2', 'P1')
            ) t(af_id, uniprot_accession);
            CREATE TABLE alphafold_retrieve_stats AS SELECT
                'P1' AS uniprot_accession, 'downloads/AF-P1-F1-model_v6.cif.gz' AS cif_file;
            CREATE TABLE merge_structure_files AS SELECT
                'downloads/AF-P1-F1-model_v6.cif.gz' AS source, 'combined_input/renamed.cif.gz' AS target;
            CREATE TABLE combined_stats AS SELECT 'combined_input/renamed.cif.gz' AS input_file,
                'P1' AS uniprot_accession, true AS is_alphafold, false AS passed, 'Low confidence' AS reason;
        """)
    rows = {row["candidate_id"]: row for row in DashboardData(tmp_path).candidates()}
    assert set(rows) == {"renamed.cif.gz", "AF-P1-F2"}
    assert rows["renamed.cif.gz"]["rejection_reason"] == "Low confidence"
    assert rows["AF-P1-F2"]["filtering_status"] == "not recorded"


def test_search_candidates_combine_accessions_without_duplicating_chains_or_fragments(tmp_path: Path):
    with duckdb.connect(str(tmp_path / "meta.duckdb")) as con:
        con.execute("""
            CREATE TABLE pdbe AS SELECT * FROM (VALUES
                ('1ABC', 'A', 'P2'), ('1ABC', 'A', 'P1'), ('1ABC', 'A', 'P1'), ('1ABC', 'B', 'P1')
            ) t(pdb_id, chain, uniprot_accession);
            CREATE TABLE alphafold AS SELECT * FROM (VALUES
                ('AF-P1-F1', 'P1'), ('AF-P1-F2', 'P1')
            ) t(af_id, uniprot_accession);
        """)
    rows = {row["candidate_id"]: row for row in DashboardData(tmp_path).candidates()}
    assert set(rows) == {"1ABC:A", "1ABC:B", "AF-P1-F1", "AF-P1-F2"}
    assert rows["1ABC:A"]["uniprot_accessions"] == "P1:P2"
    assert rows["1ABC:B"]["uniprot_accessions"] == "P1"


@pytest.mark.parametrize("recorded_prefix", ["", "/old/location/"])
def test_absolute_paths_follow_relocated_session(session: Path, recorded_prefix: str):
    with duckdb.connect(str(session / "meta.duckdb")) as con:
        con.execute("UPDATE fitted_models SET fitted_model_file = ? || fitted_model_file", [recorded_prefix])
        con.execute("UPDATE powerfit_runs SET used_target = ? || used_target", [recorded_prefix])
    relocated = session.with_name("relocated session")
    session.rename(relocated)
    row = next(row for row in DashboardData(relocated).fitting() if row["model_available"])
    assert row["model_absolute_path"] == str(relocated / "powerfit/fit-a/a.cif.gz/fit_1.pdb")
    assert row["density_absolute_path"] == str(relocated / "powerfit/fit-a/map.mrc")


@pytest.mark.parametrize("template", ["known partner #1.pdb", "../known partner #1.pdb", "{root}/known partner #1.pdb"])
def test_refinement_known_structure_link(session: Path, template: str):
    recorded = template.format(root=session.parent)
    known = (session / recorded).resolve()
    known.write_text("example")
    with duckdb.connect(str(session / "meta.duckdb")) as con:
        con.execute("UPDATE refinements_runs SET known_structure = ?", [recorded])
    rows = DashboardData(session).refinements()
    assert all(row["known_structure_absolute_path"] == str(known) for row in rows)


def test_missing_refinement_known_structure_has_no_link(session: Path):
    assert all(row["known_structure_absolute_path"] is None for row in DashboardData(session).refinements())


@pytest.mark.parametrize(
    "table",
    [
        "refinements_capri_ss",
        "refinements_io",
        "fitted_models",
        "fittable_structures",
        "refinements_capri_clt",
        "refinements_baseline",
        "powerfit_runs",
        "refinements_runs",
    ],
)
def test_refinements_require_all_joined_tables(session: Path, table: str):
    with duckdb.connect(str(session / "meta.duckdb")) as con:
        con.execute(f'DROP TABLE "{table}"')
    assert DashboardData(session).refinements() == []
