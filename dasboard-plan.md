# Protein Detective dashboard plan

TODO remove this document before merging PR

Build a local dashboard backed by Python and DuckDB, with the JavaScript app in
`./dashboard/`.

## Current state

The data and visualization foundations exist; the dashboard itself is still to
be built.

- `src/protein_detective/meta.py` generates candidate, filtering, PowerFit,
  refinement, and RO-Crate tables through `protein-detective meta SESSION_DIR`.
- Refinement metadata now includes independent refinement run IDs, source
  PowerFit run IDs, input/output mappings, final model scores, cluster
  summaries, baseline scores, and known structure paths/options recorded in
  RO-Crate.
- `src/protein_detective/refine/report.py` joins those refinement sources with
  PowerFit metadata in an in-memory DuckDB connection. It provides the reference
  joins and ranking semantics; it does not require an existing `meta.duckdb`.
- `src/protein_detective/visualization.py` already uses MolViewSpec/Mol\* to
  show fitted models and density in HTML, notebooks, and Streamlit. Its current
  fitted-model viewer embeds file bytes eagerly; on-demand dashboard loading
  remains to be implemented.
- DuckDB and MolViewSpec are direct Python dependencies. `aiohttp` is currently
  an indirect dependency through `protein-quest`; declare it directly when
  implementing the dashboard. There is no dashboard CLI command, Python
  dashboard package, `dashboard/` frontend, or frontend asset packaging yet.

## Server approach

Use `aiohttp` to serve the React app, a small JSON API, and session files from
one local origin. The dashboard always runs on loopback. Add `aiohttp` as a
direct dependency; its built-in server, static routes, JSON responses, and
`FileResponse` cover the hosting needs.

Keep Python small: provide a few fixed dataset endpoints, and let React handle
presentation joins, filtering, sorting, pagination, and plot calculations over
the loaded data. Start by loading all fitting rows for the tutorial session
once, and load other datasets when needed. Measure payload size and browser
responsiveness before introducing server-side filtering or pagination.

Keep the initial dataset SQL on the server. Run synchronous query functions with
`asyncio.to_thread()`, creating and closing a separate read-only DuckDB
connection inside each invocation. Return JSON using `web.json_response()` and
normalize database values at that boundary.

Treat the session as a stable snapshot for the lifetime of the dashboard
process. Print a CLI startup notice: **Do not modify the session directory while
the dashboard is running.** Do not add live updates or a refresh mechanism.
Missing metadata may be generated before the server starts, as described below.

Reading `meta.duckdb` read-only does not prevent future action endpoints. A
later authenticated POST endpoint can submit a refinement run through the
existing Python workflow or CLI and return a job ID without blocking the HTTP
server. Job submission, status tracking, and refreshing metadata after
completion are future work, outside the initial browsing dashboard. Keep
submission arguments structured and validated rather than accept shell command
strings.

### Local access token

- Generate a new launch token in Python with `secrets.token_urlsafe(32)` on
  every server start; keep it in memory.
- Print a URL such as `http://127.0.0.1:PORT/#token=TOKEN`, and open it
  automatically only with `--browser`. The fragment stays in the browser and is
  not sent in the initial HTTP request. See
  [URI fragments](https://developer.mozilla.org/en-US/docs/Web/URI/Reference/Fragment).
- React reads the fragment and submits the token as JSON to `POST /api/auth`.
  Validate its type and length and compare it with `secrets.compare_digest()`;
  reject missing or invalid tokens. See
  [Python secrets](https://docs.python.org/3/library/secrets.html).
- After successful verification, set the same launch token in an `HttpOnly`,
  `SameSite=Strict`, host-only session cookie with path `/`, and remove the
  fragment with `history.replaceState()`. Reloads use the cookie; restarting the
  server generates a new token and requires the new launch URL. Use aiohttp's
  cookie support directly; no separate session credentials, registry, or session
  package is needed.
- Protect every dataset and session-file endpoint with authentication middleware
  that validates the cookie token against the in-memory launch token using
  `secrets.compare_digest()`. Reject missing or invalid cookie tokens. Only the
  frontend shell/assets and the token verification endpoint are accessible
  before authentication. The cookie lets same-origin Mol\* model/map requests
  authenticate without putting tokens in file URLs.
- Serve from the exact loopback host/port printed at startup. Validate the
  `Host` header, reject foreign `Origin` headers, and require the exact
  dashboard origin for authentication and future mutation requests. Keep
  cross-origin API access disabled.
- Keep tokens out of request logs and error messages; the printed launch URL is
  the intentional exception. Authentication failures show a clear message
  directing the user to the current launch URL.

## Target command

```bash
uv run protein-detective dashboard /home/verhoes/git/protein-detective/protein-detective/docs/tutorial-6j5w
```

The command starts a local web server and prints the launch URL. Add `--browser`
to open the dashboard in a web browser automatically.

## Example session

Use `/home/verhoes/git/protein-detective/protein-detective/docs/tutorial-6j5w`
for development and validation. Its `meta.duckdb` contains:

- 24,790 fitting solutions.
- 12 fitted structures.
- 48 refined structures.
- 12 refinement cluster summaries and 12 baseline scores.
- One refinement run with 12 input/output mappings.
- Candidate metadata, filtering results, and workflow provenance.

Only the 12 saved fitted structures can be viewed initially; the remaining
fitting solutions still support inspection, filtering, and CSV export. Refined
structure files already contain both the candidate and known partner. The
tutorial's PowerFit density map is `powerfit/emd0683/emd_0683-without-rks1.mrc`,
relative to the session directory.

The metadata generator now produces the refinement tables in this example
database. Tables are conditional on available session files, so support them
when present and show clear empty states otherwise. Recorded file paths may be
relative to the session's original location and must be resolved against the
supplied session directory.

## Remaining implementation

### 1. Add the dashboard command

- Register a `dashboard` command in the existing Cyclopts CLI.
- Validate the session directory. If `meta.duckdb` is missing, warn and run the
  existing metadata generator in place before starting the server. Stop and
  report any generation failure. If an existing database is unreadable, raise an
  error; do not replace or regenerate it automatically. Use a readable existing
  database as supplied.
- Print the notice that no changes should be made to the session directory while
  the dashboard is running.
- Add a direct `aiohttp` dependency and start its local server bound to
  `127.0.0.1`.
- Generate the launch token and print the fragment-bearing URL once the server
  is ready. Open the browser only when `--browser` is supplied.
- Support `--host`, `--port`, and the opt-in `--browser` flag.
- Print the dashboard URL and stop cleanly with Ctrl+C.

### 2. Build a read-only data API

- Add a Python dashboard package that reads `meta.duckdb` without modifying it.
- Provide endpoints for session summaries, candidates, fitting solutions,
  refinements, and provenance.
- Use an individual structure as the candidate identity; UniProt accessions link
  related structures and are not unique candidate keys. Include candidates
  without fitting results and rejected candidates, using recorded search/filter
  metadata rather than only `fittable_structures`.
- Query the existing metadata tables rather than introduce a second metadata
  schema:
  - `solutions`, `fittable_structures`, and `fitted_models` for fitting results
    and candidate identities.
  - `refinements_runs` and `refinements_io` for independent run metadata and
    fitted-input mappings.
  - `refinements_capri_ss`, `refinements_capri_clt`, and `refinements_baseline`
    for final model scores, cluster summaries, and unrefined scores.
  - `rocrate_create_actions`, `rocrate_inodes`, `rocrate_objects`, and
    `rocrate_results` for workflow provenance.
- Follow the joins in `refine/report.py`: connect models and input mappings by
  `refine_run_dir`, fitted models by their recorded path, and cluster summaries
  by `(refine_run_dir, cluster_id)`. Deduplicate `fitted_models` rows as the
  report does.
- Keep `refine_run_id` and `powerfit_run_id` distinct in filters and responses;
  multiple refinement runs can reuse the same fitted input.
- Return datasets for client-side filtering, sorting, pagination, and
  presentation joins. Use the existing report joins as the reference for
  candidate/refinement relationships, whether performed in fixed SQL or React.
- Detect available tables so sessions without fitting or refinement results
  still work.
- Normalize database values into JSON responses and document the frontend API
  contract.
- Validate the few endpoint inputs explicitly; keep the API contract small and
  documented alongside its TypeScript types.
- Implement the token verification endpoint and shared authentication middleware
  described above.

### 3. Create the frontend in `./dashboard/`

Use React, TypeScript, and Vite+ (`vp`) for frontend tooling. Prioritize desktop
and laptop use, with stacked panels and horizontally scrollable tables on
narrower screens. Use a restrained scientific interface, readable tables,
accessible score colors, and light/dark appearance following the operating
system.

#### Navigation and shared behavior

- Provide four main views: **Overview**, **Fitting results**, **Refinement
  results**, and **Provenance**. Open on Overview.
- Give each view its own URL. Reflect filters, sorting, and selected
  candidate/result in the URL so copied links and browser Back/Forward restore
  the view. Authentication remains in the cookie, not navigation URLs.
- Authenticate from the launch URL before loading session data. Keep UI state in
  React and reuse fetched datasets during navigation.
- Use a resizable side panel beside the results with **Details** and **3D
  viewer** tabs. Candidate selection opens Details; an explicit View structure
  action opens the viewer. Keep the table and filters visible. Start with the
  panel closed unless the URL specifies a selection.
- View one selected fitted or refined structure at a time; selecting another
  replaces it. Load Mol\* only when the 3D viewer tab first opens.
- Paginate tables with 50 rows by default and choices of 25, 50, or 100.
- Offer CSV export from fitting and refinement tables. Export the table's
  columns and result set after filters and top-N/all selection, in current sort
  order, across all pages. Users select All solutions/members before exporting
  the full filtered dataset.
- Include loading, error, and empty states.

#### Overview and candidate details

- Show counts of candidate structures, distinct UniProt accessions, filtering
  outcomes, fitting solutions, fitted structures, refinement runs, and refined
  structures. Omit summaries for workflow stages absent from the database.
- Show the five highest-CC fitting results and five lowest-score refinement
  results, applying the same default group/member selection as their respective
  tables. Link to detailed results.
- Provide a searchable candidate list covering structures with and without
  fitting results, including rejected candidates. Show filtering status and
  rejection reason where recorded; selecting a candidate opens Details.
- Details show structure identifiers, source and UniProt links, filtering
  information/reasons, available structure-quality measurements, and related
  fitting/refinement results. Omit missing fields and place additional recorded
  metadata in an expandable section.

#### Fitting results

- Initially include all PowerFit runs, with run identifiers visible.
- Search across structure identifiers and UniProt accessions; filter by PowerFit
  run and source.
- Default to the best solution for each `(powerfit_run_id, structure)` group.
  Offer top N and All solutions controls. This intentionally differs from the
  CLI's grouping across selected runs for each structure.
- Sort by CC descending. Keep solution rank, CC, FishZ, and relative Z
  explicitly labeled.
- Default columns: structure, UniProt accessions, source, PowerFit run, solution
  rank, CC, FishZ, relative Z, and fitted-structure availability.
- Allow inspection and CSV export for unsaved solutions, but show “Fitted
  structure not saved” instead of generating a structure or enabling 3D viewing
  for that solution.

#### Refinement results

- Initially include all refinement runs; keep refinement and source PowerFit run
  identifiers distinct.
- Search across structure identifiers and UniProt accessions; filter by source,
  PowerFit run, refinement run, and cluster within its fitted input/refinement
  run.
- Default to one best member per cluster for each fitted input and refinement
  run, using `modelcluster_ranking`. Offer top N members per cluster and All
  members controls.
- Sort individual refined scores ascending. Keep cluster scores and standard
  deviations separate from individual scores.
- Default columns: structure, refinement run, source PowerFit run, fitted rank,
  cluster rank, member rank, refined score, baseline score, and score change.
- Define score change as `refined - baseline`; negative values indicate
  improvement. Show cluster population, cluster score, and cluster score
  standard deviation in Details.

#### Score charts

- Try a pinned release of `@tanstack/charts`, using its React adapter. Verify
  integration and production bundle size during implementation.
- Plot all rows matching search, run, source, and other applicable filters,
  before top-N selection and pagination; label that scope explicitly.
- Fitting histogram: default to CC, with a selector for FishZ or relative Z.
  Tooltips show score ranges and counts; histogram interaction is informational
  and does not change table filters.
- Refinement scatterplot: baseline score on X, refined score on Y, equal axis
  scales, and a diagonal reference line. Explain that points below the line
  indicate improvement.
- Clicking a refinement point selects its result and reveals the corresponding
  table page. If the point is excluded by top N, switch to All members while
  retaining the other filters and briefly explain the change.

#### Provenance

- Show a chronological list of recorded commands with expandable timestamps,
  inputs, and outputs.
- Provide command copying and recorded path inspection. Running or rerunning
  commands is outside the initial release.

#### Partial and incomplete sessions

- Before PowerFit runs, keep Overview, candidate Details, and Provenance usable.
  Results views explain the prerequisite and show the command template
  `protein-detective powerfit run TARGET_MAP RESOLUTION SESSION_DIR`.
- A PowerFit run directory and copied map alone do not prove completion. If the
  run has no solutions, explain that fitting is incomplete or results are
  missing.
- If solutions exist but no fitted structures have been saved, direct the user
  to `protein-detective powerfit fit-models`.
- Handle absent refinement results with a clear empty state. Do not hide
  available candidate or fitting information because later workflow stages are
  absent.

### 4. Integrate a 3D viewer

- Embed Mol\* to display the selected fitted or refined structure alongside its
  density map.
- Load Mol*JavaScript and CSS from jsDelivr on demand when the viewer first
  opens. Pin an exact version and use Subresource Integrity hashes with
  `crossorigin="anonymous"`; do not bundle the Mol* runtime in the webapp or
  Python distribution. Follow the
  [Mol\* integration documentation](https://molstar.org/docs/v5/plugin/instance/).
- Load the CDN script into the local dashboard page so model/map requests remain
  same-origin and use the authentication cookie. Keep model/map URLs local.
- Show loading and retry/error states for CDN failures. Document that 3D viewing
  requires internet access to fetch Mol\*; the rest of the dashboard must work
  without that download.
- Reuse the existing MolViewSpec scene construction where useful, with HTTP URLs
  for dashboard file loading.
- Load large files on demand.
- Resolve recorded paths against the supplied session directory.
- Use `refinements_capri_ss.refined_structure_path` for cleaned, compressed PDB
  outputs. Those refined files already contain the candidate and known partner;
  display them with distinct colors and independent visibility toggles. Do not
  also load `refinements_runs.processed_known_structure`, which would duplicate
  the partner.
- Require the density map associated with the source PowerFit run, including for
  refined structures. Join the run's recorded provenance inputs and outputs to
  locate its copied map; do not select an arbitrary first file in the run
  directory.
- Initially show density, with controls for visibility, opacity, and contour
  level, plus a reset-camera action.
- Restrict file serving to the session directory, including checks on resolved
  symlinks and traversal attempts.
- Require the authenticated session cookie for model/map files, including
  partial file requests.
- Show a useful message when a referenced structure is missing. If solutions
  exist but their associated density file is missing or cannot be resolved
  unambiguously, identify the missing file or association, retain usable tables,
  and disable 3D viewing until the session is repaired. Distinguish this from
  PowerFit not having run.

### 5. Package the frontend

- Build the React webapp in CI and include its compiled HTML, JavaScript, and
  CSS in the PyPI wheel. Users install and launch the dashboard without building
  the webapp.
- In both `.github/workflows/ci.yml` and `.github/workflows/pypi-publish.yml`,
  install the frontend toolchain and locked dependencies, run the `vp`
  production build, then run `uv build`.
- Use Hatchling to include the generated `dashboard/dist/` assets under the
  installed `protein_detective` package. Include the built assets in the source
  distribution too, so building a wheel from the published source distribution
  requires no frontend toolchain. Keep generated assets out of Git and fail
  packaging clearly if they are missing.
- Serve compiled assets with aiohttp static routes and the React entry page from
  the same app as `/api/` and the authenticated session-file endpoint. Keep
  API/file errors separate from any frontend route fallback.
- Ensure launching the dashboard requires no Node.js installation or frontend
  build.
- Use `vp` for frontend development, builds, and checks, and document that
  workflow.
- Document the dashboard command and its options, metadata startup behavior, the
  no-session-changes notice, and internet access required for the 3D viewer.

### 6. Verify the complete workflow

- Test dataset queries and JSON normalization; verify filtering, sorting,
  pagination, and presentation joins in the frontend.
- Verify candidate identity is structure-based, rejected/unfitted candidates
  remain accessible, fitting groups stay separate across runs, and refinement
  member selection stays separate per cluster/input/run.
- Verify the four views, URL restoration and Back/Forward navigation, panel
  tabs, narrow-screen layout, and system theme behavior.
- Verify CSV columns/order match the table and exports include every page after
  filters and top-N/all selection.
- Verify chart metrics and data scope, refinement comparison axes, and chart
  selection revealing a row excluded by top N.
- Build on the existing metadata and refinement report tests; add dashboard
  coverage for independent refinement runs, duplicate fitted-model rows,
  cluster/member score separation, and baseline joins.
- Test missing tables, path resolution, missing files, and file access
  boundaries.
- Test missing metadata generation in place with a warning, generation failures,
  and unreadable existing databases raising an error without regeneration.
  Confirm the CLI prints the no-session-changes notice and the UI does not
  refresh session data automatically.
- Verify distinct messages for no PowerFit run, incomplete fitting, solutions
  without fitted structures, and missing source density. Confirm read-only
  browsing never generates fitted structures.
- Test that token verification sets the same token in a cookie with the required
  attributes; reject invalid/missing tokens at both verification and protected
  API/file endpoints. Verify fragment removal, cookie-based reloads, and
  rejection of the old token after restart. Verify foreign origins/hosts are
  rejected and tokens do not appear in request logs.
- Build the frontend and inspect the wheel/source distribution for compiled
  dashboard assets and the absence of the Mol\* runtime. Build a wheel from the
  source distribution without Node.js, install it outside the checkout, and
  verify the dashboard serves its packaged assets.
- Verify Mol\* is fetched only when opening the viewer, uses pinned CDN URLs
  with valid integrity hashes, and can load authenticated local model/map files.
  Verify a failed or blocked CDN download shows a useful error while other views
  still work.
- Verify browser interactions against the tutorial session, including selecting
  models and loading density maps.
- Verify refined files show both partners once, visibility toggles work
  independently, and density controls/reset camera work. Confirm unsaved fitting
  solutions and missing density do not enable 3D viewing.
- Confirm the target command prints a usable launch URL without opening a
  browser by default, `--browser` opens and authenticates a working dashboard,
  and Ctrl+C shuts down the server.
- Run the repository checks:

  ```bash
  uv run pytest
  uvx ruff format
  uvx ruff check --fix
  uv run pyrefly check
  uvx prek run --all-files
  ```

## Completion criteria

The target command prints the launch URL for a usable dashboard for the tutorial
session, opens a browser only with `--browser`, and authenticates through the
token in the launch URL fragment. Session data and files require authentication.
Users can browse and filter fitting results, inspect candidates and refinement
scores, view structures with density maps, and inspect workflow provenance. The
dashboard handles partial sessions gracefully and runs from the packaged Python
application without a frontend toolchain at runtime. The compiled webapp ships
in the wheel; Mol\* is fetched from a pinned internet URL on demand, with a
clear error when unavailable.

The refinement metadata foundation is implemented in
`src/protein_detective/meta.py` and covered by `tests/test_meta.py`; no separate
refinement metadata prerequisite remains for this plan.
