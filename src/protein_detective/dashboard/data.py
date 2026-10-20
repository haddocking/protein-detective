"""Read-only datasets for the dashboard API.

Each dataset call opens its own DuckDB connection. Missing workflow stages
produce empty results; recorded file paths are resolved against the session.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb


def _normalize_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _normalize_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_normalize_json(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return _normalize_json(float(value))
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Path):
        return str(value)
    return value


_SESSION_STAGE_DIRS = frozenset(
    {
        "powerfit",
        "refine",
        "combined_input",
        "combined_output",
        "downloads",
        "imported_structures",
        "secondary_structure",
        "single_chain",
        "uniprots_verified",
    }
)


def _relative_path(session_dir: Path, recorded_path: str) -> Path:
    path = Path(recorded_path)
    if not recorded_path or ".." in path.parts or "\x00" in recorded_path:
        msg = "Invalid session file path"
        raise ValueError(msg)
    root = session_dir.resolve()
    if path.is_absolute() and path.is_relative_to(root):
        return path.relative_to(root)
    # A relocated session can retain its old absolute or repository-relative prefix.
    # Recognized workflow directories remain meaningful even if the session was renamed.
    # Rebase only the suffix; the final resolution still enforces the session boundary.
    if root.name in path.parts and (path.is_absolute() or path.parts[0] in {"docs", root.name}):
        index = len(path.parts) - 1 - path.parts[::-1].index(root.name)
        return Path(*path.parts[index + 1 :])
    for index, part in enumerate(path.parts):
        if part in _SESSION_STAGE_DIRS:
            return Path(*path.parts[index:])
    if path.is_absolute():
        msg = "File is outside the session directory"
        raise ValueError(msg)
    return path


def _resolve_session_file(session_dir: Path, recorded_path: str) -> Path:
    root = session_dir.resolve()
    resolved = (root / _relative_path(root, recorded_path)).resolve()
    if not resolved.is_relative_to(root):
        msg = "File is outside the session directory"
        raise ValueError(msg)
    if not resolved.is_file():
        msg = f"Session file is missing: {recorded_path}"
        raise FileNotFoundError(msg)
    return resolved


class DashboardData:
    """Read session metadata without modifying the database or generating files.

    Keep the session unchanged while browsing. Database errors propagate to callers.

    Attributes:
        session_dir: Resolved session root.
        database: Path to the session's meta.duckdb.
    """

    def __init__(self, session_dir: Path):
        """Store the session location without opening its database.

        Args:
            session_dir: Directory containing existing metadata and workflow files.
        """
        self.session_dir = session_dir.resolve()
        self.database = self.session_dir / "meta.duckdb"
        self._file_availability: dict[str, bool] = {}

    def _connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(str(self.database), read_only=True)

    @staticmethod
    def _tables(con: duckdb.DuckDBPyConnection) -> set[str]:
        return {row[0] for row in con.execute("SHOW TABLES").fetchall()}

    @staticmethod
    def _query(con: duckdb.DuckDBPyConnection, sql: str) -> list[dict[str, Any]]:
        cursor = con.execute(sql)
        names = [column[0] for column in (cursor.description or [])]
        return [dict(zip(names, _normalize_json(row), strict=True)) for row in cursor.fetchall()]

    def _rows(self, con: duckdb.DuckDBPyConnection, table: str) -> list[dict[str, Any]]:
        if table not in self._tables(con):
            return []
        # Table names are internal constants, never request inputs.
        return self._query(con, f'SELECT DISTINCT * FROM "{table}"')  # noqa: S608 - internal table names

    def _path(self, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        try:
            return _relative_path(self.session_dir, value).as_posix()
        except ValueError:
            return None

    def _exists(self, path: str | None) -> bool:
        if path is None:
            return False
        if path not in self._file_availability:
            try:
                _resolve_session_file(self.session_dir, path)
            except (ValueError, OSError):
                self._file_availability[path] = False
            else:
                self._file_availability[path] = True
        return self._file_availability[path]

    def _single_chain_candidates_query(self, tables: set[str]) -> str | None:
        """Build a query linking original PDB chains to processed structures.

        Args:
            tables: Metadata tables available in the session.

        Returns:
            A SELECT retaining rejected chain extractions, or None when retrieval
            or chain statistics are absent. Optional workflow joins are omitted.
        """
        if not {"single_chain_stats", "pdbe_retrieve_stats"} <= tables:
            return None
        joins = []
        input_file = "sc.input_file"
        output_file = "sc.output_file"
        search_fields = ""
        accession = "''"
        if "uniprots_verified_stats" in tables:
            joins.append("LEFT JOIN uniprots_verified_stats v ON sc.input_file = v.output_file")
            input_file = "coalesce(v.input_file, sc.input_file)"
        joins.append(f"JOIN pdbe_retrieve_stats d ON d.output_file = {input_file}")
        if "merge_structure_files" in tables:
            joins.append("LEFT JOIN merge_structure_files m ON sc.output_file = m.source")
            output_file = "coalesce(m.target, sc.output_file)"
        if "pdbe" in tables:
            joins.append("LEFT JOIN pdbe p ON upper(p.pdb_id) = upper(d.pdb_id) AND p.chain = sc.chain2keep")
            search_fields = "p.* EXCLUDE (chain),"
            accession = "coalesce(p.uniprot_accession, '')"
        return f"""\
            SELECT DISTINCT
                {search_fields}
                CASE WHEN nullif(sc.output_file, '') IS NOT NULL
                    THEN parse_filename({output_file})
                    ELSE d.pdb_id || ':' || sc.chain2keep
                END AS structure,
                d.pdb_id AS structure_id,
                sc.chain2keep AS chain,
                false AS is_alphafold,
                {accession} AS uniprot_accessions,
                sc.passed,
                sc.discard_reason AS reason
            FROM single_chain_stats sc
            {" ".join(joins)}
            """  # noqa: S608 - SQL fragments are internal constants

    @staticmethod
    def _candidate_source(con: duckdb.DuckDBPyConnection, table: str) -> str:
        """Expose optional candidate fields as NULL without changing metadata tables.

        Only dashboard identity/filtering fields need defaults. Existing quality
        columns are retained as supplied by each workflow stage.
        """
        cursor = con.execute(f'SELECT * FROM "{table}" LIMIT 0')  # noqa: S608 - internal table
        columns = {column[0] for column in (cursor.description or [])}
        fields = (
            "structure",
            "structure_id",
            "is_alphafold",
            "chain",
            "passed",
            "reason",
            "uniprot_accessions",
            "uniprot_accession",
            "input_file",
            "structure_file",
        )
        missing = [
            f'NULL::{"BOOLEAN" if field in {"is_alphafold", "passed"} else "VARCHAR"} AS "{field}"'
            for field in fields
            if field not in columns
        ]
        if not missing:
            return f'"{table}"'
        return f'(SELECT *, {", ".join(missing)} FROM "{table}")'  # noqa: S608 - internal identifiers

    @staticmethod
    def _merge_candidate_rows(source: str) -> str:
        """Group candidate rows, keeping later non-null measurements and unique accessions."""
        return f"""
            SELECT structure,
                first(COLUMNS(* EXCLUDE (structure, uniprot_accessions, _stage_priority))
                    ORDER BY _stage_priority DESC)
                    FILTER (WHERE COLUMNS(* EXCLUDE (
                        structure, uniprot_accessions, _stage_priority
                    )) IS NOT NULL),
                coalesce(array_to_string(list_sort(list_distinct(flatten(
                    list(string_split(nullif(uniprot_accessions, ''), ':'))
                ))), ':'), '') AS uniprot_accessions
            FROM {source}
            GROUP BY structure
        """  # noqa: S608 - internal CTE name

    def _candidates(self, con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
        """Assemble available stages and unmatched search hits using SQL CTEs."""
        tables = self._tables(con)
        stages = []
        chain_query = self._single_chain_candidates_query(tables)
        if chain_query:
            stages.append(f"SELECT *, 0 AS _stage_priority FROM ({chain_query})")  # noqa: S608
        for priority, table in enumerate(("combined_stats", "secondary_structure_stats", "fittable_structures"), 1):
            if table not in tables:
                continue
            source = self._candidate_source(con, table)
            stages.append(f"""
                SELECT *, {priority} AS _stage_priority
                FROM (
                    SELECT * REPLACE (
                        parse_filename(coalesce(
                            nullif(structure, ''),
                            nullif(input_file, ''),
                            nullif(structure_file, '')
                        )) AS structure,
                        coalesce(nullif(uniprot_accessions, ''), uniprot_accession) AS uniprot_accessions
                    )
                    FROM {source}
                )
                WHERE structure IS NOT NULL AND structure <> ''
            """)  # noqa: S608 - internal source and priority

        ctes = []
        candidates = []
        if stages:
            ctes.append("stage_rows AS (" + " UNION ALL BY NAME ".join(stages) + ")")
            ctes.append("processed AS (" + self._merge_candidate_rows("stage_rows") + ")")
            candidates.append("SELECT *, 0 AS _stage_priority FROM processed")

        af_join = ""
        af_model = "regexp_extract(c.structure, '^(AF-.+-F[0-9]+)(?:[-.]|$)', 1)"
        if stages and "alphafold_retrieve_stats" in tables:
            merge = (
                "LEFT JOIN merge_structure_files m ON a.cif_file = m.source"
                if "merge_structure_files" in tables
                else ""
            )
            target = "coalesce(m.target, a.cif_file)" if merge else "a.cif_file"
            ctes.append(f"""
                af_sources AS (
                    SELECT parse_filename({target}) AS structure,
                        regexp_extract(parse_filename(a.cif_file), '^(AF-.+-F[0-9]+)(?:[-.]|$)', 1) AS model_id
                    FROM alphafold_retrieve_stats a
                    {merge}
                )
            """)  # noqa: S608 - internal source mapping
            af_join = "LEFT JOIN af_sources a ON a.structure = c.structure"
            af_model = f"coalesce(nullif(a.model_id, ''), {af_model})"

        for table, identifier, is_af in (("alphafold", "af_id", True), ("pdbe", "pdb_id", False)):
            if table not in tables:
                continue
            source = self._candidate_source(con, table)
            structure = f"s.{identifier}" if is_af else "s.pdb_id || ':' || coalesce(s.chain, '')"
            unmatched = (
                """
                    AND NOT EXISTS (
                        SELECT 1 FROM processed c
                        WHERE NOT coalesce(c.is_alphafold, false)
                            AND upper(c.structure_id) = upper(s.pdb_id)
                            AND c.chain = s.chain
                    )
                """
                if stages and not is_af
                else ""
            )
            if stages and is_af:
                unmatched = f"""
                    AND NOT EXISTS (
                        SELECT 1 FROM processed c
                        {af_join}
                        WHERE c.is_alphafold AND (
                            c.structure = s.af_id OR {af_model} =
                                CASE WHEN starts_with(s.af_id, 'AF-') THEN s.af_id
                                    ELSE 'AF-' || s.af_id || '-F1' END
                        )
                    )
                """  # noqa: S608 - internal source mapping
            candidates.append(f"""
                SELECT s.* REPLACE (
                    {structure} AS structure,
                    s.{identifier} AS structure_id,
                    {str(is_af).lower()} AS is_alphafold,
                    coalesce(nullif(s.uniprot_accessions, ''), s.uniprot_accession) AS uniprot_accessions
                ), 0 AS _stage_priority
                FROM {source} s
                WHERE nullif(s.{identifier}, '') IS NOT NULL
                {unmatched}
            """)  # noqa: S608 - internal source and identity expressions

        if not candidates:
            return []
        ctes.append("candidate_rows AS (" + " UNION ALL BY NAME ".join(candidates) + ")")
        ctes.append("candidates AS (" + self._merge_candidate_rows("candidate_rows") + ")")
        return self._query(
            con,
            f"""
            WITH {", ".join(ctes)}
            SELECT *, structure AS candidate_id,
                CASE WHEN is_alphafold THEN 'AlphaFold' ELSE 'PDB' END AS source,
                CASE WHEN passed THEN 'passed' WHEN NOT passed THEN 'rejected'
                    ELSE 'not recorded' END AS filtering_status,
                reason AS rejection_reason
            FROM candidates
            ORDER BY structure
        """,  # noqa: S608 - internal CTE definitions
        )

    def candidates(self) -> list[dict[str, Any]]:
        """Return candidate structures, including rejected and unfitted candidates.

        Returns:
            Rows ordered by structure, with identifiers, UniProt accessions, source,
                filtering outcomes, and available quality measurements. Missing tables
                yield an empty list.
        """
        with self._connect() as con:
            return self._candidates(con)

    def _provenance(self, con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
        inodes = {row["id"]: row for row in self._rows(con, "rocrate_inodes")}
        inputs: dict[str, list[str]] = {}
        outputs: dict[str, list[str]] = {}
        for row in self._rows(con, "rocrate_objects"):
            inputs.setdefault(row["action_id"], []).append(row["object_id"])
        for row in self._rows(con, "rocrate_results"):
            outputs.setdefault(row["action_id"], []).append(row["result_id"])
        actions = self._rows(con, "rocrate_create_actions")
        for action in actions:
            action["start_time"] = action.get("startTime")
            action["end_time"] = action.get("endTime")
            action["inputs"] = inputs.get(action["id"], [])
            action["outputs"] = outputs.get(action["id"], [])
            action["files"] = [inodes.get(path, {"id": path}) for path in action["inputs"] + action["outputs"]]
        return sorted(actions, key=lambda row: (row.get("start_time") or "", row["id"]))

    def provenance(self) -> list[dict[str, Any]]:
        """Return recorded workflow commands with their inputs and outputs.

        Returns:
            Actions ordered by start time and ID, or an empty list when none are recorded.
        """
        with self._connect() as con:
            return self._provenance(con)

    def _viewer(self, row: dict[str, Any], model: Any) -> None:
        row["model_path"] = self._path(model)
        row["model_available"] = self._exists(row["model_path"])
        row["density_path"] = self._path(row.get("used_target"))
        row["density_available"] = self._exists(row["density_path"])
        row["viewer_available"] = row["model_available"] and row["density_available"]
        row["viewer_error"] = (
            ("Fitted structure not saved" if model is None else f"Structure file is missing or inaccessible: {model}")
            if not row["model_available"]
            else (
                "Source density association is missing or ambiguous"
                if row["density_path"] is None
                else f"Source density file is missing or inaccessible: {row['density_path']}"
            )
            if not row["density_available"]
            else None
        )

    def _fitting(self, con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
        tables = self._tables(con)
        if "solutions" not in tables:
            return []
        join = (
            "LEFT JOIN (SELECT DISTINCT * FROM fitted_models) fm USING (powerfit_run_id, structure, rank)"
            if "fitted_models" in tables
            else ""
        )
        model_column = "fm.fitted_model_file" if join else "NULL"
        target_join = "LEFT JOIN powerfit_runs pr USING (powerfit_run_id)" if "powerfit_runs" in tables else ""
        target_column = "pr.used_target" if target_join else "NULL"
        rows = self._query(
            con,
            f"SELECT s.*, {model_column} AS fitted_model_file, {target_column} AS used_target "  # noqa: S608
            f"FROM solutions s {join} {target_join} "
            "ORDER BY cc DESC, powerfit_run_id, structure, rank",
        )
        for row in rows:
            # Browsing never uses transform matrices to regenerate models.
            row.pop("rotation", None)
            row.pop("translation", None)
            row["id"] = f"{row['powerfit_run_id']}:{row['structure']}:{row['rank']}"
            row["candidate_id"] = row["structure"]
            row["source"] = "AlphaFold" if row.get("is_alphafold") else "PDB"
            row["relative_z"] = row.get("relz")
            self._viewer(row, row.get("fitted_model_file"))
        return rows

    def fitting(self) -> list[dict[str, Any]]:
        """Return all fitting solutions, including solutions without saved structures.

        Returns:
            Rows ordered by CC descending, with run/structure/rank identity, scores,
                and viewer availability. Group top solutions by (powerfit_run_id,
                structure). Returns an empty list when solutions are absent.
        """
        with self._connect() as con:
            return self._fitting(con)

    def _refinements(self, con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
        tables = self._tables(con)
        if "refinements_capri_ss" not in tables:
            return []
        fields = [
            "m.*",
            "m.unfitted_structure AS structure",
            "m.score AS refined_score",
            "m.modelcluster_ranking AS member_rank",
        ]
        joins = []
        if "refinements_io" in tables:
            joins.append("LEFT JOIN refinements_io io ON m.refine_run_dir = io.refine_run_dir")
            fields.append("io.fitted_model")
            if "fitted_models" in tables:
                joins.append(
                    "LEFT JOIN (SELECT DISTINCT * FROM fitted_models) fm ON io.fitted_model = fm.fitted_model_file"
                )
                fields.append("fm.rank AS fitted_rank")
        if "fittable_structures" in tables:
            joins.append("LEFT JOIN fittable_structures fs ON m.unfitted_structure = fs.structure")
            fields += ["fs.uniprot_accessions", "fs.is_alphafold", "fs.structure_id"]
        if "refinements_capri_clt" in tables:
            joins.append(
                "LEFT JOIN refinements_capri_clt cl ON m.refine_run_dir = cl.refine_run_dir "
                "AND m.cluster_id = cl.cluster_id"
            )
            fields += [
                "cl.cluster_rank",
                "cl.n AS population",
                "cl.score AS cluster_score",
                "cl.score_std AS cluster_score_std",
            ]
        if "refinements_baseline" in tables:
            joins.append("LEFT JOIN refinements_baseline b ON m.refine_run_dir = b.refine_run_dir")
            fields.append("b.score AS baseline_score")
        if "powerfit_runs" in tables:
            joins.append("LEFT JOIN powerfit_runs pr ON m.powerfit_run_id = pr.powerfit_run_id")
            fields.append("pr.used_target")
        if "refinements_runs" in tables:
            joins.append("LEFT JOIN refinements_runs r ON m.refine_run_id = r.refine_run_id")
            fields += ["r.options AS refinement_options", "r.fixed_structure"]
        rows = self._query(
            con,
            f"SELECT {', '.join(fields)} FROM refinements_capri_ss m {' '.join(joins)} "  # noqa: S608
            "WHERE m.score IS NOT NULL ORDER BY m.score, m.refined_structure_path",
        )
        for row in rows:
            row["candidate_id"] = row["structure"]
            row["id"] = row["refined_structure_path"]
            row["source"] = "AlphaFold" if row.get("is_alphafold") else "PDB"
            baseline = row.get("baseline_score")
            row["score_change"] = row["refined_score"] - baseline if baseline is not None else None
            self._viewer(row, row["refined_structure_path"])
        return rows

    def refinements(self) -> list[dict[str, Any]]:
        """Return final refinement members across independent refinement runs.

        Returns:
            Rows ordered by individual score, with cluster scores kept separate.
                Score change is refined minus baseline; negative means improvement.
                Group members by refinement run, fitted input, and cluster. Returns
                an empty list when refinement results are absent.
        """
        with self._connect() as con:
            return self._refinements(con)

    def summary(self) -> dict[str, Any]:
        """Return session counts and fitting progress.

        Returns:
            Candidate and workflow counts, available tables, PowerFit runs, and fitting
                status. Counts for absent workflow stages are omitted.
        """
        with self._connect() as con:
            tables = self._tables(con)
            candidates = self._candidates(con)
            counts = {}
            for key, table in (
                ("fitting_solutions", "solutions"),
                ("fitted_structures", "fitted_models"),
                ("refinement_runs", "refinements_runs"),
                ("refined_structures", "refinements_capri_ss"),
            ):
                if table in tables:
                    result = con.execute(
                        f'SELECT count(*) FROM (SELECT DISTINCT * FROM "{table}")'  # noqa: S608
                    ).fetchone()
                    counts[key] = result[0] if result else 0
            if "combined_stats" in tables:
                counts["filtering_passed"] = sum(row.get("passed") is True for row in candidates)
                counts["filtering_rejected"] = sum(row.get("passed") is False for row in candidates)
            run_table = "powerfit_runs" if "powerfit_runs" in tables else "solutions" if "solutions" in tables else None
            runs: list[str] = (
                [
                    row[0]
                    for row in con.execute(
                        f"SELECT DISTINCT powerfit_run_id FROM {run_table} ORDER BY powerfit_run_id"  # noqa: S608
                    ).fetchall()
                ]
                if run_table
                else []
            )
            status = "complete" if counts.get("fitting_solutions") else "incomplete" if runs else "not_started"
            if status == "complete" and not counts.get("fitted_structures"):
                status = "structures_not_saved"
            return {
                "session_name": self.session_dir.name,
                "candidate_structures": len(candidates),
                "uniprot_accessions": len(
                    {
                        accession
                        for row in candidates
                        for accession in str(row.get("uniprot_accessions") or "").split(":")
                        if accession
                    }
                ),
                **counts,
                "available_tables": sorted(tables),
                "fitting_status": status,
                "powerfit_runs": runs,
            }
