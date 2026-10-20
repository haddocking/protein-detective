# Browse a session in the dashboard

Install the published Python package, then start the local dashboard:

```shell
protein-detective dashboard mysession
# Open a browser automatically:
protein-detective dashboard mysession --browser
# Choose a host and port (add --browser to open a browser):
protein-detective dashboard mysession --host localhost --port 8765
```

The installed package includes the built interface. Node.js and a frontend build
are not required to launch it. The command prints a launch URL without opening a
browser by default; add `--browser` to open it automatically. The server binds
to `127.0.0.1` by default. Use `--host HOST` to select another IP address or
hostname for the binding and launch URL; IPv6 addresses such as `--host ::1` are
supported. Open the exact URL printed in the terminal. Its fragment
authenticates this browser and is removed from the address bar once
authentication succeeds. Reloads use an HttpOnly, SameSite=Strict cookie. Each
server launch creates a new token, so after a restart open the newly printed
URL. Stop the server with Ctrl+C.

**Do not modify the session directory while the dashboard is running.** The
dashboard treats it as a stable snapshot. It reads an existing `meta.duckdb`
without replacing or updating it. If metadata is missing, the command warns and
runs `protein-detective meta` before starting; metadata generation is the only
startup operation that writes to the session. An unreadable existing database
raises an error instead of being regenerated.

Overview includes searched and rejected candidates alongside fitted candidates.
Fitting results initially show the best solution per structure and PowerFit run.
Refinement results initially show the best member per cluster, fitted input, and
refinement run. Filters, sorting, and selection are retained in navigation URLs.
CSV exports include the filtered, sorted selection across all pages; choose All
solutions or All members before exporting every filtered result. Score charts
show all filtered rows before the top-N selection and pagination.

Select a result to inspect its details. Use View structure to load a saved model
and its associated source density map on demand. Unsaved fitted solutions remain
available for inspection and export; save structures with
`protein-detective powerfit fit-models` before viewing them. Missing density
maps or ambiguous provenance associations must be repaired before 3D viewing.

The viewer retains its Mol\* instance and the current density map while the
result panel remains open, including when switching to Details. Viewing another
model from the same source map replaces only the structure and preserves density
visibility, opacity, and contour settings. Selecting a different source map
replaces the loaded map; closing the panel releases the viewer. Structure and
map responses use private browser caching with authenticated revalidation, so
unchanged files can return HTTP 304 without transferring their contents again.

The 3D viewer downloads Mol\* 5.4.2 JavaScript and CSS from jsDelivr only when
it is opened. Both assets use pinned SHA-384 Subresource Integrity hashes and
anonymous CORS. **Internet access is required for the first 3D viewer
download**; tables, filters, details, export, and provenance work without it. A
blocked download shows a Retry viewer action. Structures and density maps stay
on the authenticated local server. Refined models already include the candidate
(chain A, blue) and fixed partner (chain B, orange), each with a visibility
toggle. Density controls adjust visibility, opacity, and contour in standard
deviations; Reset camera frames the scene again.

## Frontend development and packaging

The React/TypeScript frontend lives in `dashboard/` and uses Vite+ (`vp`). With
Node.js installed:

```shell
cd dashboard
npm ci
npm run format
npx vp check
npx vp test run
npx vp build
```

From the repository root, launch the frontend and Python API together:

```shell
uv run protein-detective dashboard SESSION_DIR --dev
# Choose a port and open the browser automatically:
uv run protein-detective dashboard SESSION_DIR --dev --port 8765 --browser
```

Open the printed launch URL. Vite serves frontend source directly, with React
Fast Refresh and hot module replacement (HMR): saving a component such as
`dashboard/src/pages/overview-page.tsx` updates the browser without a production
build or manual reload. Vite proxies API and session-file requests to a private
Python server, preserving the launch-token authentication and same-origin
cookies. `--host`, `--port` (including `0`), and `--browser` work as usual.
Ctrl+C stops both servers; a Vite startup failure also stops the Python server.
Python code changes still require restarting the command. Do not modify session
files during development.

Dev mode requires a source checkout, Node.js, and `npm ci` in `dashboard/`.
`npm run dev` starts only the standalone Vite frontend; use the Python command
above to include the authenticated API. The default command without `--dev`
continues to serve compiled assets and requires no Node.js runtime.

After the frontend build, run `uv build` from the repository root. Hatchling
includes `dashboard/dist/` at `protein_detective/dashboard/static/` in the wheel
and includes those compiled assets in the source distribution. A wheel can then
be built from the source distribution without Node.js. Packaging fails clearly
when compiled assets are missing; editable Python installs remain available for
frontend development. Generated assets and `node_modules` are ignored by Git. CI
and the PyPI publishing workflow install the locked frontend dependencies and
run the `vp` production build before `uv build`. The Mol\* runtime is downloaded
by the browser and is excluded from Python distributions.

Mol\* integration follows the
[official Viewer integration documentation](https://molstar.org/docs/v5/plugin/instance/).
