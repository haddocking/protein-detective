# Plan for the refinement TODOs

TODO remove this file before merging PR.

This plan covers refinement subcommands, run IDs, reporting, and score
comparison. It proposes implementation work; no application code has been
changed. Resume and cleanup of incomplete runs are out of scope and tracked in
[issue #98](https://github.com/haddocking/protein-detective/issues/98). Renaming
`powerfit` to `fit` is also out of scope and tracked in
[issue #99](https://github.com/haddocking/protein-detective/issues/99).

## Findings from the current code

- `src/protein_detective/cli.py` registers refinement as a single command.
  PowerFit already has `run`, `report`, `fit-models`, and `list-runs`
  subcommands.
- `refine_with_haddock3()` creates `session/refine` with `mkdir()` and therefore
  cannot perform a second refinement in the same session. Its nested `run_001`
  currently identifies the **source PowerFit run**, not a refinement experiment.
- `refine_structure_task()` infers the source run from three parent directories.
  It discards that run ID when constructing the output path. Consequently,
  matching structure names and fitted model names from different PowerFit runs
  collide when refining all runs together. Its input path resolution also relies
  on the current directory when the session path is relative.
- The generated workflow is `0_topoaa`, `1_rigidbody`, `2_caprieval`,
  `3_clustfcc`, `4_caprieval`, `5_seletopclusts`, `6_mdref`, `7_caprieval`. Thus
  `2_caprieval` already evaluates rigid-body-refined models. It is a
  pre-**mdref** score, not a score of the original fitted placement.
- `meta.py` already reads final `capri_ss.tsv` and `capri_clt.tsv`, handles TSV
  comments and `-` nulls, and joins through session-relative `refine_run_dir`.
  Its glob fixes both directory depth and final stage number. Adding a run
  directory or changing the workflow requires updating this loader.
- `powerfit/fitted_models.csv` supplies source run, structure, fitted rank, and
  model paths. `powerfit/fittable_structures.csv` supplies `uniprot_accessions`,
  `structure_id`, and `is_alphafold`; the existing report uses a colon-separated
  accession string. Reuse these files instead of fetching metadata again.
- Existing CAPRI fixtures include an unclustered aggregate (`cluster_id` and
  `cluster_rank` are `-`). A report cannot assume every result has valid
  clusters. Existing refinement tests cover configuration, chain preparation,
  CLI parsing, and a manual HADDOCK run; metadata tests cover final-stage
  selection and joins.
- See manual-test/ for output of previous run of
  `uv run pytest -vv -m manual tests/test_refine.py::test_refine_with_haddock3`.

## 1. Introduce subcommands and independent refinement runs

First add a Cyclopts `refine_app`, following `powerfit/cli.py`, with:

```text
protein-detective refine run SESSION FIXED_STRUCTURE [--refine-run-id ID]
protein-detective refine list-runs SESSION
```

Keep `refine_with_haddock3()` callable from Python and move CLI registration to
the subcommand app. Start with CLI wrappers and helpers in `refine.py`; a new
package is unnecessary at this size. Preserve the current refinement options,
chain-removal option, source `--powerfit-run-id` selector, and scheduler option.

Allocate a refinement ID independently of the source fitting ID. Use the next
unused numeric ID above the current maximum, rather than copying PowerFit's
`len(existing_runs) + 1` algorithm, which collides after runs are deleted.
Create the directory exclusively; explicit IDs must be a single safe path
component and cannot overwrite an existing run.

Proposed layout:

```text
session/refine/refine_run_001/
    fixed_structure.pdb
    io.csv
    <source-fit-run-id>/<structure>/fit_1.pdb.cfg
    <source-fit-run-id>/<structure>/fit_1.pdb/<HADDOCK steps>
```

Assume PowerFit files are written once. Reuse the existing fitting CSVs for
input metadata and `io.csv` for the selected fitted-model paths and their
refinement directories. No separate input snapshot or `run.json` is needed:
generated HADDOCK configs already record effective tool options, and RO-Crate
records the invocation and fixed-structure preparation. Use file timestamps when
inspecting output dates and the expected HADDOCK results to determine result
availability, without storing a separate timestamp or run status. Use
session-relative paths in `io.csv` and resolve absolute paths explicitly against
`session_dir` at the HADDOCK boundary. Deduplicate selected model paths and
reject missing inputs or an empty selection before creating a run. Preserve the
source fitting ID in the model directory to prevent collisions, without an
additional `models/` grouping directory. Keep configs outside HADDOCK model run
directories, as required by the existing `setup_run()` behavior.

Write `io.csv` with the expected input/output mapping before launching work,
including `refine_run_id` and source fitting ID. Mapping presence does not imply
completion. Keep `refine_run_dir` as the session-relative model-level HADDOCK
directory so existing joins remain meaningful. Update RO-Crate outputs and
command metadata to reference the particular run, inputs, config, and options.
Keep index writes in the coordinator; workers write only their own results.

Replace the draft `refine SESSION FIXED_STRUCTURE` command with `refine run`
directly; no default-command wrapper or CLI transition period is needed.
backwards compatibility is unnecessary while this PR is a draft.

Refactor tests/test_refine.py to tests/refine/, layout tests same way as src.

## 2. Add a report with accessions and top N members of every cluster

Use an in-memory DuckDB connection to read the run indexes, PowerFit CSVs, and
CAPRI TSVs and perform the joins and per-cluster member ranking. Users do not
need to build a persistent database first. Reuse queries and CAPRI parsing
conventions between reporting and `meta.py`; retain the existing database table
names and session-relative join keys.

Define `--top N` as the best N **final-stage members of every cluster per fitted
input per refinement run**, with a default of 1 and positive-integer validation.
Keep all clusters; select members within each cluster by numeric model HADDOCK
score ascending, with rank/path as deterministic tie breakers. For one fitted
PDB producing five clusters with three members each, `--top 2` returns ten rows:
two members from each of the five clusters. A cluster with fewer than N members
contributes all its members. This report option does not change the workflow's
`top_clusters` or `top_models` sampling/selection options. Allow reporting all
refinement runs or one explicit run; report missing IDs clearly. An overall
ranking across proteins can be a later addition.

One row per selected member should contain:

- Refinement run ID, source fitting run ID, structure, fitted rank, and
  `uniprot_accessions` from the existing PowerFit metadata, using the existing
  colon separator.
- Cluster ID/rank, population, `under_eval`, cluster score, and cluster score
  standard deviation, repeated for each selected member of that cluster.
- Model rank within the cluster, model score, and model path. Keep model scores
  and cluster summary scores in separately named columns.
- Fitted input and model run paths, plus available score-stage fields from
  step 3.

Join `io.csv` to `powerfit/fitted_models.csv` through the fitted-model path,
then join `powerfit/fittable_structures.csv` through the source structure key.
Use the existing PowerFit metadata sources; do not infer UniProt accessions from
`fit_1.pdb` filenames. Missing metadata should give empty accessions without
dropping valid refinement results.

Use `capri_ss.tsv` to select members grouped by cluster and join `capri_clt.tsv`
for cluster summaries. Resolve each member's `model` path relative to the CAPRI
directory and account for `.pdb.gz` output after HADDOCK cleanup. Treat `-`
values as missing. If there are no valid clusters, return the best N individual
models per fitted input with `cluster_id=-` and empty cluster summary fields; do
not label the unclustered aggregate as cluster 1. Keep cluster IDs null
internally in DuckDB and render them as `-` in CSV output. No `result_type`
column is needed. Exclude incomplete model runs from ranked results and
summarize them on stderr. Keep stdout as CSV, with `--output` following the
existing PowerFit convention.

Update `meta.py` to read per-run indexes. Discover explicitly selected CAPRI
stages from the generated HADDOCK configs, with the current `7_caprieval`
fallback. Do not use an unrestricted recursive glob that also includes
intermediate or `analysis/` copies. Review database joins in documentation
notebooks for the new run ID.

Add `--refine-run-id` to `uv run protein-detective meta` and pass it through the
metadata-loading helpers. When supplied, load refinement mappings and CAPRI
results only for that refinement run; when omitted, load all refinement runs.
Keep this selector independent of `--powerfit-run-id`, and report an unknown
refinement run ID clearly.

## 3. Report HADDOCK3 scores before and after refinement

For each fitted input, create `fitted-and-fixed.pdb` in the existing coordinate
frame, with the fitted structure as chain A and the fixed structure as chain B.
Run a separate HADDOCK3 scoring workflow before refinement using this
configuration:

```toml
molecules = ["fitted-and-fixed.pdb"] # A: fitted structure; B: fixed structure

[topoaa]

[emscoring]

[caprieval]
```

Take the `score` column from the first data row of this workflow's
`2_caprieval/capri_ss.tsv` as the score of the unrefined fitted structure. Skip
TSV comments and the header; do not select a different row by sorting scores.
This baseline replaces the existing refinement workflow's `2_caprieval` score
and the proposed `best_rigidbody_score` field.

Include this pre-refinement score in the report alongside final individual and
cluster scores from the refinement workflow's final CAPRI stage (currently
`7_caprieval`). Record the baseline scoring config and output directory so the
two workflows' `2_caprieval` stages cannot be confused. Update stage discovery,
configuration tests, and metadata loading for the separate baseline workflow.

Label the baseline as the unrefined fitted-structure HADDOCK3 score obtained
with `emscoring`. This protocol includes energy minimization; it is not an
unchanged-coordinate score. A baseline individual score and a final cluster
average summarize different populations, so their difference must not be
presented as improvement of the same individual model. Before offering a paired
score delta, verify model lineage and comparable scoring weights; otherwise
report the scores separately.

## Delivery order and validation

Deliver this as small, reviewable changes:

1. **Run storage and CLI:** refinement subcommands, IDs, per-run IO index, path
   fixes, metadata loading, and provenance. Test two refinements of the same
   fitted input, duplicate source names across fit runs, deleted numeric IDs,
   explicit-ID rejection, empty selections, and relative/absolute sessions when
   invoked outside the session directory.
2. **Reporting:** member ranking within every cluster, UniProt joins, model
   fallback, and pre-refinement score columns from TODO 3. Use existing CAPRI
   fixtures plus a small clustered fixture. Test the five-cluster/three-member
   example (`--top 2` yields ten rows), clusters smaller than N, top-N
   boundaries, missing metadata, compressed model paths, multiple runs, partial
   results, and exclusion of intermediate/analysis copies. Extend metadata join
   tests for both layouts and verify `meta --refine-run-id` selects only the
   requested refinement run. Check that unclustered output uses `cluster_id=-`
   without a `result_type` column.
3. **Score comparison:** create `fitted-and-fixed.pdb`, run the separate
   `topoaa` / `emscoring` / `caprieval` workflow, and report the first data
   row's `score` from its `capri_ss.tsv` alongside final refinement scores. Test
   chain assignment, configuration, first-row extraction, and baseline/final
   workflow separation. Verify model lineage before paired deltas.

For implementation, run the repository checks: `uv run pytest`,
`uvx ruff format`, `uvx ruff check --fix`, `uv run pyrefly check`, and
`uvx prek run --all-files`. Use stubs and local fixtures for automated tests;
then explicitly run the manual HADDOCK integration test with small sampling to
verify actual output stages, compression, and provenance. The manual test's
paths and comparison against `manual-refine-test-output` will need adjustment
for independent refinement run directories.

The primary decisions are settled above: independent refinement IDs and top N
members of every cluster per fitted input. Keep the existing `powerfit` command
name in this PR. The pre-refinement baseline is the separate HADDOCK3 `topoaa` /
`emscoring` / `caprieval` protocol specified in TODO 3, replacing the refinement
workflow's pre-mdref `2_caprieval` score.

---

## Refinement TODO 1: completed

Progress as of 2026-10-07. Specification: the implementation plan above. TODO 1
is complete. Final validation and review finished on 2026-10-07.

### User scope and constraints

- Implement the first TODO only.
- **Do not implement any report command yet.** The initial report implementation
  and its tests were removed after the user clarified this scope. Reporting
  belongs to the next TODO; do not add a placeholder command.
- **`refine list-runs` must not write to RO-Crate.** Current implementation only
  reads indexes/results and writes CSV. A regression assertion confirms that
  crate bytes are unchanged after listing.
- Repository checks are in AGENTS.md. Ponytail skill was read and applied:
  `.agents/skills/ponytail/SKILL.md`.

### Implemented

- `src/protein_detective/refine/cli.py` defines a Cyclopts `refine_app` with
  `run` and `list-runs`. Main CLI registers that app. Python callable
  `refine_with_haddock3()` remains available. Old direct refine invocation was
  replaced by `refine run`.
- Independent refinement IDs: `refine_run_NNN`, with the next numeric ID above
  the existing maximum; explicit IDs accept safe ASCII components. Exclusive
  mkdir prevents overwrites.
- New layout: `refine/<refinement-id>/<powerfit-id>/<structure>/<fit.pdb>/`.
  Configs remain adjacent to model directories as `<fit.pdb>.cfg`.
- Session paths are resolved explicitly. Selected model files are deduplicated
  and checked for existence/layout; empty selections fail before creating a run.
- Per-run `io.csv` is written by the coordinator before workers start, with
  `refine_run_id,powerfit_run_id,fitted_model,refine_run_dir` and
  session-relative paths. Workers only write their own configs/results.
- RO-Crate includes model directories, per-run IO index and configs. Prepared
  fixed structure input metadata describes removed/renamed chains. Effective
  invocation includes refinement ID, source selector and all HADDOCK options.
  `common_cli.write_ro_crate()` gained an optional `argv` argument for this. The
  recorder ignores Program.subcommands metadata; explicit argv is needed to
  distinguish repeated Python invocations (otherwise pytest/process argv
  collapses actions). Refinement function returns None to preserve CLI behavior.
- `meta.py` discovers per-run `refine/*/io.csv` and reads the new directory
  layout for final `7_caprieval` results. Existing CAPRI table columns/joins
  remain intact. Stage discovery and `meta --refine-run-id` belong to TODO 2 and
  are not added.
- README CLI examples and metadata notebook explanation updated.
- Moved `tests/test_refine.py` to `tests/refine/test_run.py` and adjusted
  CLI/manual test paths and provenance expectations.
- Tests in `tests/refine/test_run.py` cover safe IDs, deleted numeric IDs,
  exclusive creation, missing/empty selections and manual HADDOCK integration.
  Configuration and chain preparation tests are in `test_haddock.py`; RO-Crate
  round-trip tests are in `test_provenance.py`. These mirror the source modules.
  Mocked repeated-run and worker-failure tests were removed to comply with the
  repository's mocking policy.
- `tests/refine/test_cli.py` covers CLI validation, source selection and
  read-only listing. Shared refinement fixtures are in
  `tests/refine/conftest.py`. Multiple-run metadata index tests live in
  `tests/test_meta.py`.

### Final validation

- `uv run pytest`: **81 passed, 2 skipped, 1 deselected**.
- `uv run pyrefly check`: **0 errors**.
- `uvx ruff format` and `uvx ruff check --fix`: passed.
- `uvx prek run --all-files`: passed, including the mocking policy. CLI
  selection and read-only listing tests use argument parsing and local files
  without mocks.
- Real HADDOCK integration test:
  `uv run pytest -vv -m manual tests/refine/test_run.py::test_refine_with_haddock3`:
  **1 passed** in 104.63 seconds. Verified the independent-run output layout,
  compressed mdref model, IO mapping, final CAPRI output and RO-Crate
  provenance.
- Reviewed run allocation, exclusive directory creation, relative paths,
  provenance, and metadata joins across refinement runs.
- Removed the added early-CAPRI assertion: early-score validation belongs to the
  reporting work. No report command has been implemented.

### Next work

TODO 2 (reporting) remains separate. No push has been requested.

### Working tree notes

Pre-existing untracked items should be left alone: `.agents/`, `.vscode/`,
`1L5W.cif.gz`, `fitted-models.csv`, `gpus.sh`, `manual-test/`, `session.sh`,
`skills-lock.json`. `tests/refine/` contains new task files. The original plan
above is preserved; this handoff was appended.
