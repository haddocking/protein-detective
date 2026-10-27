# Dashboard snapshot API

<!-- TODO this is way to much docs, simplify it or construct an openapi specification -->

The frontend and Python server share one configured origin (loopback by
default). Each dataset is stable for one server lifetime. There is no refresh or
workflow mutation endpoint. React fetches each needed dataset once and performs
filtering, grouping, sorting, pagination, charts, and CSV export locally. Types
live in `src/data.ts`.

## Authentication and files

`POST /api/auth` accepts JSON `{"token":"LAUNCH_TOKEN"}`. The token must be an
ASCII string with exactly the current launch token's length and value. On
success the server returns `{"authenticated":true}` and sets the launch token in
an HttpOnly, SameSite=Strict, host-only session cookie with path `/`. React
removes `#token=...` after successful authentication. All subsequent requests,
including model/map downloads, use that cookie. Foreign Host and Origin values
are rejected; use the exact configured origin printed at startup. The public
shell, assets, and token endpoint are the only public resources. Invalid
credentials return HTTP 401; open the current launch URL to authenticate again.

`GET /files/{session-relative-path}` serves an existing session file and
supports HTTP range requests. Encode individual path segments, preserving `/`
separators. Traversal and symlinks escaping the supplied session are rejected.
`model_path` and `density_path` in datasets are session-relative or null.
`model_absolute_path` and `density_absolute_path` contain resolved absolute
paths on the dashboard server for opening files in external applications. Each
is null when its file is unavailable. Downloads occur only when the viewer
opens. File responses use `Cache-Control: private, no-cache`: browser caches may
store them, but reuse requires an authenticated server check. Unchanged files
support ETag/Last-Modified validation with HTTP 304; unauthenticated conditional
requests are rejected. Dataset and authentication responses use
`Cache-Control: no-store`. The viewer retains the current density map when
switching models from the same source map and keeps it through Details
navigation until the panel closes. Browsing never generates a fitted model or
modifies the session.

## Dataset endpoints

All endpoints below require authentication. They accept no filtering parameters.
Successful responses are JSON. Missing optional tables yield empty arrays and
omit the corresponding stage counts. Zero counts describe present stages. Dates
become ISO strings; nonfinite numbers become null. Additional recorded metadata
may accompany these documented fields.

| Endpoint               | Response                                                  |
| ---------------------- | --------------------------------------------------------- |
| `GET /api/summary`     | Session counts and workflow status object                 |
| `GET /api/candidates`  | `Candidate[]`, including rejected and unfitted structures |
| `GET /api/fitting`     | `FittingResult[]`, including unsaved solutions            |
| `GET /api/refinements` | `RefinementResult[]`                                      |
| `GET /api/provenance`  | `ProvenanceAction[]`                                      |

Summary fields are `session_name`, `candidate_structures`, `uniprot_accessions`,
`available_tables`, `powerfit_runs`, and `fitting_status`. Optional stage counts
are `filtering_passed`, `filtering_rejected`, `fitting_solutions`,
`fitted_structures`, `refinement_runs`, and `refined_structures`.
`fitting_status` is `not_started`, `incomplete`, `structures_not_saved`, or
`complete`.

## Row fields and relationships

Candidate fields include `candidate_id`, `structure`, `structure_id`,
`uniprot_accessions` (colon-separated), `source` (`PDB` or `AlphaFold`),
`filtering_status` (`passed`, `rejected`, or `not recorded`), and nullable
`rejection_reason`. Candidate identity is an individual structure, never a
UniProt accession. Available quality measurements accompany these fields.

Both result types include `id`, `candidate_id`, `structure`, `powerfit_run_id`,
`model_path`, `density_path`, `model_available`, `density_available`,
`viewer_available`, and nullable `viewer_error`. Viewing requires a saved model
and an unambiguous density association with its source PowerFit run. Unavailable
structures still support Details and CSV export.

Fitting fields include `rank`, `cc`, `fishz`, and `relative_z`. Default grouping
uses `(powerfit_run_id, candidate_id)`, retaining the lowest solution rank;
default sorting uses CC descending. FishZ and relative Z are separate metrics.

Refinements also include nullable `original_known_structure_absolute_path`,
constructed from `original_known_structure` relative to the current session
root. It is null when no original path is recorded. The dashboard shows compact
buttons that copy absolute paths to the clipboard, with the full path in each
tooltip.

Refinement rows include `refined_complex`, `refined_fitted_structure`, and
`refined_known_structure` from `9_reconstruct/io.csv`. The viewer loads the
reconstructed fitted and known partners as separate structures, preserving the
known partner's original chains. `refined_known_structure_absolute_path` is the
copyable path to that refined partner.

The refinement details panel groups local file paths into inputs (density,
unrefined fitted model, original known structure) and outputs (refined fitted
structure, refined known structure). `fitted_model_absolute_path` and
`refined_fitted_structure_absolute_path` distinguish the fitted model before and
after refinement.

Refinement fields include `refine_run_id`, `refine_run_dir`, `fitted_model`,
`fitted_rank`, `cluster_id`, `cluster_rank`, `member_rank`, `refined_score`,
`baseline_score`, `score_change`, `population`, `cluster_score`, and
`cluster_score_std`. Default member selection retains the lowest `member_rank`
within each independent refinement run, fitted input, and cluster. Default
sorting uses `after_cc` (PowerFit CC after refinement) descending. `before_cc`
and `after_cc` are fixed-coordinate PowerFit scores; `cc_change` is
`after_cc - before_cc`, where positive values indicate improvement.
`refined_score`, `baseline_score`, `cluster_score`, and `cluster_score_std` are
CAPRI scores. `score_change` is `refined_score - baseline_score`; negative
values indicate improvement. Dashboard and CSV labels explicitly name each
scoring system. Missing baseline/cluster measurements are null. Refinement run
IDs are independent of source PowerFit run IDs, and multiple refinement runs can
reuse a fitted input.

Provenance fields include `command`, nullable `start_time` and `end_time`, and
`inputs` and `outputs` arrays of recorded paths. Additional `files` metadata
provides recorded inode details. Commands are displayed chronologically for
copying and path inspection. There is no command execution endpoint.
