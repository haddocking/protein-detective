"""Security and startup regressions for the local dashboard."""

import json
import re
import tempfile
from pathlib import Path

import duckdb
import pytest
import pytest_asyncio
from aiohttp import ClientConnectorError, ClientSession, web
from aiohttp.test_utils import TestClient, TestServer
from cyclopts import ValidationError
from yarl import URL

from protein_detective.cli import app
from protein_detective.dashboard import server
from protein_detective.meta import ExecuteError


@pytest_asyncio.fixture
async def client(tmp_path: Path):
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "index.html").write_text("dashboard shell")
    session = tmp_path / "session"
    session.mkdir()
    (session / "model.pdb").write_bytes(b"MODEL contents")
    app = server._create_app(session, origin="http://127.0.0.1:1", token="a" * 43, assets=assets)
    async with TestClient(TestServer(app)) as client:
        app[server.CONFIG].origin = str(client.make_url("")).rstrip("/")
        yield client


async def login(client: TestClient[web.Request, web.Application]):
    return await client.post(
        "/api/auth", json={"token": "a" * 43}, headers={"Origin": client.app[server.CONFIG].origin}
    )


@pytest.mark.asyncio
async def test_auth_cookie_and_protected_files(client: TestClient[web.Request, web.Application]):
    assert (await client.get("/")).status == 200
    assert (await client.get("/files/model.pdb")).status == 401
    assert (await client.get("/api/summary")).status == 401
    response = await login(client)
    assert response.status == 200
    cookie = response.cookies[server.COOKIE_NAME]
    assert cookie.value == "a" * 43
    assert cookie["httponly"]
    assert cookie["samesite"] == "Strict"
    assert cookie["path"] == "/"
    assert not cookie["domain"]
    headers = {"Cookie": f"{server.COOKIE_NAME}={'a' * 43}"}
    response = await client.get("/files/model.pdb", headers=headers)
    assert response.status == 200
    assert await response.read() == b"MODEL contents"
    partial = await client.get("/files/model.pdb", headers={**headers, "Range": "bytes=0-4"})
    assert partial.status == 206
    assert await partial.read() == b"MODEL"
    client.app[server.CONFIG].token = "b" * 43
    assert (await client.get("/files/model.pdb", headers=headers)).status == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("token", [None, 123, [], {}, "", "invalid", "é" * 43])
async def test_invalid_token(client: TestClient[web.Request, web.Application], token: object):
    response = await client.post(
        "/api/auth", json={"token": token}, headers={"Origin": client.app[server.CONFIG].origin}
    )
    assert response.status == 401
    assert "current dashboard launch URL" in await response.text()


@pytest.mark.asyncio
async def test_foreign_host_and_origin(client: TestClient[web.Request, web.Application]):
    assert (await client.get("/", headers={"Host": "attacker.example"})).status == 403
    assert (await client.get("/", headers={"Origin": "https://attacker.example"})).status == 403
    assert (await client.post("/api/auth", json={"token": "a" * 43})).status == 403
    assert (await client.post("/api/auth", json={"token": "a" * 43}, headers={"Origin": "null"})).status == 403


@pytest.mark.asyncio
async def test_file_boundaries_and_missing_routes(client: TestClient[web.Request, web.Application], tmp_path: Path):
    outside = tmp_path / "secret.txt"
    outside.write_text("secret")
    (client.app[server.CONFIG].session_dir / "escape").symlink_to(outside)
    headers = {"Cookie": f"{server.COOKIE_NAME}={'a' * 43}"}
    assert (await client.get("/files/escape", headers=headers)).status == 404
    assert (await client.get(URL("/files/%2e%2e/secret.txt", encoded=True), headers=headers)).status in {403, 404}
    assert (await client.get("/files/missing.pdb", headers=headers)).status == 404
    assert (await client.get("/api/unknown", headers=headers)).status == 404
    assert (await client.get("/api/summary?sql=DROP", headers=headers)).status == 400
    assert (await client.get("/fitting")).status == 200
    assert (await client.get("/assets/missing.js")).status == 404


def test_missing_metadata_generated_once(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    graph = [
        {
            "@id": "ro-crate-metadata.json",
            "@type": "CreativeWork",
            "about": {"@id": "./"},
            "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
        },
        {"@id": "./", "@type": "Dataset", "description": "Session", "name": "session"},
        {
            "@id": "command",
            "@type": "CreateAction",
            "name": "protein-detective candidates search session",
            "agent": {"@id": "user"},
            "instrument": {"@id": "protein-detective"},
            "startTime": "2026-01-01T00:00:00Z",
            "endTime": "2026-01-01T00:00:01Z",
            "object": [{"@id": "input"}],
            "result": [{"@id": "output"}],
        },
    ]
    crate = tmp_path / "ro-crate-metadata.json"
    crate.write_text(json.dumps({"@context": "https://w3id.org/ro/crate/1.1/context", "@graph": graph}))
    assert server._prepare_session(tmp_path) == tmp_path
    database = tmp_path / "meta.duckdb"
    before = database.stat().st_mtime_ns
    crate.unlink()
    server._prepare_session(tmp_path)
    assert database.stat().st_mtime_ns == before
    assert "generating meta.duckdb" in capsys.readouterr().err


def test_existing_invalid_database_not_regenerated(tmp_path: Path):
    database = tmp_path / "meta.duckdb"
    database.write_text("invalid")
    with pytest.raises(duckdb.Error, match="not a valid DuckDB database"):
        server._prepare_session(tmp_path)
    assert database.read_text() == "invalid"


def test_generation_failure_propagates(tmp_path: Path):
    # Without a RO-Crate, real metadata generation must fail and stop startup.
    with pytest.raises(ExecuteError):
        server._prepare_session(tmp_path)


def test_asset_validation(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="assets are missing"):
        server._create_app(tmp_path, origin="http://127.0.0.1:8080", assets=tmp_path)


@pytest.mark.asyncio
async def test_dev_api_needs_no_built_assets(tmp_path: Path):
    app = server._create_app(tmp_path, origin="http://127.0.0.1:1", assets=tmp_path, dev=True)
    async with TestClient(TestServer(app)) as client:
        app[server.CONFIG].origin = str(client.make_url("")).rstrip("/")
        assert (await client.get("/api/summary")).status == 401
        assert (await client.get("/")).status == 404


@pytest.mark.parametrize(("options", "expected"), [([], False), (["--dev"], True)])
def test_dashboard_cli_dev_is_opt_in(tmp_path: Path, options: list[str], expected: bool):
    _, bound, _ = app.parse_args(["dashboard", str(tmp_path), *options], exit_on_error=False)
    bound.apply_defaults()
    assert bound.arguments["dev"] is expected


def test_dev_requires_node(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PATH", "")
    with pytest.raises(FileNotFoundError, match="npm ci"):
        server._dev_command()


@pytest.fixture
def dev_module():
    try:
        _, source = server._dev_command()
    except FileNotFoundError:
        pytest.skip("Requires Node.js and dashboard npm ci")
    with tempfile.TemporaryDirectory(prefix="hmr-test-", dir=source) as directory:
        module = Path(directory) / "main.ts"
        module.write_text("export const value = 1; if (import.meta.hot) import.meta.hot.accept();")
        yield module, f"/{module.relative_to(source).as_posix()}"


@pytest.mark.asyncio
async def test_vite_proxy_hmr_and_cleanup(tmp_path: Path, dev_module: tuple[Path, str]):
    """Exercise real Vite without touching the developer's frontend source files."""
    module, module_url = dev_module
    session = tmp_path / "session"
    session.mkdir()
    (session / "model.pdb").write_text("MODEL")
    app = server._create_app(session, origin="http://127.0.0.1:1", dev=True)
    async with TestServer(app) as backend:
        async with server._dev_frontend("127.0.0.1", 0, str(backend.make_url(""))) as (port, process):
            origin = server._dashboard_origin("127.0.0.1", port)
            app[server.CONFIG].origin = origin
            async with ClientSession() as client:
                assert (await client.get(f"{origin}/")).status == 200
                component = await client.get(f"{origin}/src/pages/overview-page.tsx")
                assert component.status == 200
                assert "$RefreshReg$" in await component.text()
                assert (await client.get(f"{origin}/files/model.pdb")).status == 401
                response = await client.post(
                    f"{origin}/api/auth", json={"token": app[server.CONFIG].token}, headers={"Origin": origin}
                )
                assert response.status == 200
                headers = {"Cookie": f"{server.COOKIE_NAME}={app[server.CONFIG].token}"}
                response = await client.get(f"{origin}/files/model.pdb", headers={**headers, "Range": "bytes=0-2"})
                assert response.status == 206
                assert await response.text() == "MOD"
                assert (await client.get(f"{origin}/api/summary", headers={**headers, "Origin": "null"})).status == 403
                response = await client.get(f"{origin}/@vite/client")
                script = await response.text()
                token = re.search(r'const wsToken = "([^"]+)"', script)
                assert token is not None
                async with client.ws_connect(f"{origin}/?token={token[1]}", protocols=["vite-hmr"]) as ws:
                    assert (await ws.receive_json(timeout=10))["type"] == "connected"
                    assert (await client.get(f"{origin}{module_url}")).status == 200
                    module.write_text("export const value = 2; if (import.meta.hot) import.meta.hot.accept();")
                    update = await ws.receive_json(timeout=10)
                    assert update["type"] == "update"
                    assert update["updates"][0]["path"] == module_url
        assert process.returncode is not None
        async with ClientSession() as client:
            with pytest.raises(ClientConnectorError):
                await client.get(f"{origin}/")


def test_broken_database_symlink_is_not_regenerated(tmp_path: Path):
    target = tmp_path / "missing-target.duckdb"
    database = tmp_path / "meta.duckdb"
    database.symlink_to(target)
    with pytest.raises(duckdb.Error):
        server._prepare_session(tmp_path)
    assert database.is_symlink()
    assert not target.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("host", ["localhost", "127.0.0.2", "::1"])
async def test_configured_host_origin_authentication(client: TestClient[web.Request, web.Application], host: str):
    origin = server._dashboard_origin(host, 8765)
    client.app[server.CONFIG].origin = origin
    headers = {"Host": origin.removeprefix("http://"), "Origin": origin}
    assert (await client.get("/", headers=headers)).status == 200
    response = await client.post("/api/auth", json={"token": "a" * 43}, headers=headers)
    assert response.status == 200
    assert (await client.get("/", headers={"Host": "127.0.0.1:8765"})).status == 403
    assert (await client.get("/", headers={**headers, "Origin": "http://127.0.0.1:8765"})).status == 403


@pytest.mark.parametrize("port", [-1, 65536])
def test_dashboard_cli_rejects_out_of_range_port(tmp_path: Path, port: int):
    with pytest.raises(ValidationError, match="Must be"):
        app.parse_args(
            ["dashboard", str(tmp_path), "--port", str(port)],
            exit_on_error=False,
            print_error=False,
        )


@pytest.mark.parametrize("port", [0, 65535])
def test_dashboard_cli_accepts_port_boundaries(tmp_path: Path, port: int):
    _, bound, _ = app.parse_args(
        ["dashboard", str(tmp_path), "--port", str(port)],
        exit_on_error=False,
        print_error=False,
    )
    assert bound.arguments["port"] == port


def test_dashboard_cli_rejects_missing_session_path(tmp_path: Path):
    with pytest.raises(ValidationError):
        app.parse_args(
            ["dashboard", str(tmp_path / "missing")],
            exit_on_error=False,
            print_error=False,
        )


def test_dashboard_cli_rejects_session_file(tmp_path: Path):
    session_path = tmp_path / "session"
    session_path.write_text("not a directory")
    with pytest.raises(ValidationError):
        app.parse_args(
            ["dashboard", str(session_path)],
            exit_on_error=False,
            print_error=False,
        )


@pytest.mark.parametrize(("options", "expected"), [([], False), (["--browser"], True)])
def test_dashboard_cli_browser_is_opt_in(tmp_path: Path, options: list[str], expected: bool):
    _, bound, _ = app.parse_args(
        ["dashboard", str(tmp_path), *options],
        exit_on_error=False,
        print_error=False,
    )
    bound.apply_defaults()
    assert bound.arguments["browser"] is expected


@pytest.mark.asyncio
@pytest.mark.parametrize("validator", ["If-None-Match", "If-Modified-Since"])
async def test_files_revalidate_authenticated_private_cache(
    client: TestClient[web.Request, web.Application], validator: str
):
    headers = {"Cookie": f"{server.COOKIE_NAME}={'a' * 43}"}
    original = await client.get("/files/model.pdb", headers=headers)
    assert original.status == 200
    assert await original.read() == b"MODEL contents"
    assert original.headers["Cache-Control"] == "private, no-cache"
    assert original.headers["ETag"]
    assert original.headers["Last-Modified"]
    value = original.headers["ETag" if validator == "If-None-Match" else "Last-Modified"]
    conditional = await client.get("/files/model.pdb", headers={**headers, validator: value})
    assert conditional.status == 304
    assert await conditional.read() == b""
    assert conditional.headers["Cache-Control"] == "private, no-cache"
    assert conditional.headers["ETag"] == original.headers["ETag"]
    assert conditional.headers["Last-Modified"] == original.headers["Last-Modified"]
    assert conditional.headers["X-Content-Type-Options"] == "nosniff"

    # Knowing validators never bypasses the launch-cookie check.
    unauthenticated = await client.get("/files/model.pdb", headers={validator: value})
    assert unauthenticated.status == 401
    client.app[server.CONFIG].token = "b" * 43
    expired = await client.get("/files/model.pdb", headers={**headers, validator: value})
    assert expired.status == 401


@pytest.mark.asyncio
async def test_files_keep_range_and_if_range_semantics_with_private_cache(
    client: TestClient[web.Request, web.Application],
):
    headers = {"Cookie": f"{server.COOKIE_NAME}={'a' * 43}"}
    original = await client.get("/files/model.pdb", headers=headers)
    await original.read()
    partial = await client.get(
        "/files/model.pdb",
        headers={**headers, "Range": "bytes=0-4", "If-Range": original.headers["Last-Modified"]},
    )
    assert partial.status == 206
    assert await partial.read() == b"MODEL"
    assert partial.headers["Cache-Control"] == "private, no-cache"
    assert partial.headers["Accept-Ranges"] == "bytes"
    assert partial.headers["Content-Range"] == "bytes 0-4/14"
    assert partial.headers["ETag"] == original.headers["ETag"]
    assert partial.headers["Last-Modified"] == original.headers["Last-Modified"]


@pytest.mark.asyncio
async def test_api_returns_uncached_uncompressed_datasets(client: TestClient[web.Request, web.Application]):
    response = await login(client)
    assert response.headers["Cache-Control"] == "no-store"
    with duckdb.connect(str(client.app[server.CONFIG].session_dir / "meta.duckdb")):
        pass
    response = await client.get(
        "/api/summary",
        headers={"Cookie": f"{server.COOKIE_NAME}={'a' * 43}", "Accept-Encoding": "gzip, deflate"},
    )
    assert response.status == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert "Content-Encoding" not in response.headers
    assert (await response.json())["candidate_structures"] == 0


@pytest.mark.asyncio
async def test_static_session_files_allow_internal_symlinks_without_directory_listings(
    client: TestClient[web.Request, web.Application],
):
    root = client.app[server.CONFIG].session_dir
    (root / "alias.pdb").symlink_to(root / "model.pdb")
    headers = {"Cookie": f"{server.COOKIE_NAME}={'a' * 43}"}
    response = await client.get("/files/alias.pdb", headers=headers)
    assert response.status == 200
    assert await response.read() == b"MODEL contents"
    assert (await client.get("/files")).status == 401
    assert (await client.get("/files/")).status == 401
    assert (await client.get("/files", headers=headers)).status == 403
    directory = await client.get("/files/", headers=headers)
    assert directory.status == 403
    assert "model.pdb" not in await directory.text()
