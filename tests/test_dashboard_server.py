"""Security and startup regressions for the local dashboard."""

import json
from pathlib import Path

import duckdb
import pytest
import pytest_asyncio
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from yarl import URL

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
    app = server.create_app(session, origin="http://127.0.0.1:1", token="a" * 43, assets=assets)
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
    assert (await client.get("/files/escape", headers=headers)).status == 403
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
    assert server.prepare_session(tmp_path) == tmp_path
    database = tmp_path / "meta.duckdb"
    before = database.stat().st_mtime_ns
    crate.unlink()
    server.prepare_session(tmp_path)
    assert database.stat().st_mtime_ns == before
    assert "generating meta.duckdb" in capsys.readouterr().err


def test_existing_invalid_database_not_regenerated(tmp_path: Path):
    database = tmp_path / "meta.duckdb"
    database.write_text("invalid")
    with pytest.raises(duckdb.Error, match="not a valid DuckDB database"):
        server.prepare_session(tmp_path)
    assert database.read_text() == "invalid"


def test_generation_failure_propagates(tmp_path: Path):
    # Without a RO-Crate, real metadata generation must fail and stop startup.
    with pytest.raises(ExecuteError):
        server.prepare_session(tmp_path)


def test_session_and_asset_validation(tmp_path: Path):
    with pytest.raises(ValueError, match="does not exist"):
        server.prepare_session(tmp_path / "missing")
    with pytest.raises(FileNotFoundError, match="assets are missing"):
        server.create_app(tmp_path, origin="http://127.0.0.1:8080", assets=tmp_path)
    with pytest.raises(ValueError, match="Port must"):
        server.dashboard(tmp_path, port=65536)


def test_broken_database_symlink_is_not_regenerated(tmp_path: Path):
    target = tmp_path / "missing-target.duckdb"
    database = tmp_path / "meta.duckdb"
    database.symlink_to(target)
    with pytest.raises(duckdb.Error):
        server.prepare_session(tmp_path)
    assert database.is_symlink()
    assert not target.exists()
