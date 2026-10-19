"""Loopback-only, authenticated dashboard hosting.

The session is a stable snapshot: queries open independent read-only connections,
while files are streamed on demand without copying them into the application.
"""

import asyncio
import contextlib
import secrets
import webbrowser
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import duckdb
from aiohttp import web
from cyclopts import Parameter

from protein_detective.common_cli import console
from protein_detective.dashboard.data import DashboardData
from protein_detective.meta import create_meta_duckdb

COOKIE_NAME = "protein_detective_dashboard"
AUTH_MESSAGE = "Open the current dashboard launch URL printed in your terminal to authenticate."


@dataclass
class DashboardConfig:
    session_dir: Path
    token: str
    origin: str
    assets: Path


CONFIG = web.AppKey("dashboard_config", DashboardConfig)


def valid_token(value: object, expected: str) -> bool:
    return (
        isinstance(value, str)
        and len(value) == len(expected)
        and value.isascii()
        and secrets.compare_digest(value, expected)
    )


@web.middleware
async def security(
    request: web.Request, handler: Callable[[web.Request], Awaitable[web.StreamResponse]]
) -> web.StreamResponse:
    config = request.app[CONFIG]
    if request.headers.get("Host") != config.origin.removeprefix("http://"):
        raise web.HTTPForbidden(text="Invalid dashboard host")
    origin = request.headers.get("Origin")
    if origin is not None and origin != config.origin:
        raise web.HTTPForbidden(text="Foreign origins are not allowed")
    if request.path == "/api/auth" and origin != config.origin:
        raise web.HTTPForbidden(text="Authentication requires the dashboard origin")
    if (request.path.startswith(("/api/", "/files/")) and request.path != "/api/auth") and not valid_token(
        request.cookies.get(COOKIE_NAME), config.token
    ):
        raise web.HTTPUnauthorized(text=AUTH_MESSAGE)
    response = await handler(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    if request.path.startswith(("/api/", "/files/")):
        response.headers["Cache-Control"] = "no-store"
    return response


async def authenticate(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except (ValueError, UnicodeError):
        raise web.HTTPBadRequest(text="Expected a JSON token object") from None
    if not isinstance(payload, dict) or not valid_token(payload.get("token"), request.app[CONFIG].token):
        raise web.HTTPUnauthorized(text=AUTH_MESSAGE)
    response = web.json_response({"authenticated": True})
    response.set_cookie(COOKIE_NAME, request.app[CONFIG].token, httponly=True, samesite="Strict", path="/")
    return response


async def dataset(request: web.Request) -> web.Response:
    name = request.match_info["dataset"]
    if name not in {"summary", "candidates", "fitting", "refinements", "provenance"}:
        raise web.HTTPNotFound(text="Unknown dataset")
    if request.query:
        raise web.HTTPBadRequest(text="Dataset endpoints do not accept query parameters")
    data = DashboardData(request.app[CONFIG].session_dir)
    result = await asyncio.to_thread(getattr(data, name))
    response = web.json_response(result)
    response.enable_compression()
    return response


async def session_file(request: web.Request) -> web.FileResponse:
    root = request.app[CONFIG].session_dir.resolve()
    relative = Path(request.match_info["path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise web.HTTPForbidden(text="File outside session directory")
    try:
        path = (root / relative).resolve()
    except (ValueError, OSError, RuntimeError):
        raise web.HTTPForbidden(text="Invalid session file path") from None
    if not path.is_relative_to(root):
        raise web.HTTPForbidden(text="File outside session directory")
    if not path.is_file():
        raise web.HTTPNotFound(text="Referenced session file is missing")
    return web.FileResponse(path)


async def shell(request: web.Request) -> web.FileResponse:
    path = request.match_info.get("path", "")
    if path.startswith(("api/", "files/", "assets/")) or path in {"api", "files", "assets"}:
        raise web.HTTPNotFound
    return web.FileResponse(request.app[CONFIG].assets / "index.html")


def create_app(
    session_dir: Path, *, origin: str, token: str | None = None, assets: Path | None = None
) -> web.Application:
    app = web.Application(middlewares=[security], client_max_size=2048)
    assets = assets or Path(__file__).parent / "static"
    # Source checkouts use the same compiled files as the package build.
    if not (assets / "index.html").is_file() and assets == Path(__file__).parent / "static":
        assets = Path(__file__).parents[3] / "dashboard" / "dist"
    if not (assets / "index.html").is_file():
        message = (
            "Dashboard assets are missing. Build the frontend with `cd dashboard && vp build`, "
            "or reinstall the package."
        )
        raise FileNotFoundError(message)
    app[CONFIG] = DashboardConfig(session_dir.resolve(), token or secrets.token_urlsafe(32), origin, assets)
    app.router.add_post("/api/auth", authenticate)
    app.router.add_get("/api/{dataset}", dataset)
    app.router.add_get("/files/{path:.*}", session_file)
    if (assets / "assets").is_dir():
        app.router.add_static("/assets/", assets / "assets")
    app.router.add_get("/{path:.*}", shell)
    return app


def prepare_session(session_dir: Path) -> Path:
    session_dir = session_dir.resolve()
    if not session_dir.is_dir():
        message = f"Session directory does not exist: {session_dir}"
        raise ValueError(message)
    database = session_dir / "meta.duckdb"
    if not database.exists() and not database.is_symlink():
        console.print("[yellow]Metadata is missing; generating meta.duckdb in the session directory.[/yellow]")
        create_meta_duckdb(session_dir)
    # Never regenerate an existing database, even when it cannot be read.
    with duckdb.connect(str(database), read_only=True) as connection:
        connection.execute("SHOW TABLES").fetchall()
    return session_dir


async def serve(session_dir: Path, *, port: int, no_browser: bool) -> None:
    app = create_app(session_dir, origin=f"http://127.0.0.1:{port}")
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    try:
        site = web.TCPSite(runner, "127.0.0.1", port)
        await site.start()
        addresses = runner.addresses
        actual_port = addresses[0][1]
        config = app[CONFIG]
        config.origin = f"http://127.0.0.1:{actual_port}"
        url = f"{config.origin}/#token={config.token}"
        console.print("Do not modify the session directory while the dashboard is running.")
        console.print(url, markup=False, highlight=False, soft_wrap=True)
        if not no_browser:
            await asyncio.to_thread(webbrowser.open, url)
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


def dashboard(
    session_dir: Path,
    *,
    port: Annotated[int, Parameter(help="Loopback port (0 chooses an available port).")] = 8080,
    no_browser: Annotated[bool, Parameter(help="Print the launch URL without opening a browser.")] = False,
) -> None:
    """Browse a session snapshot in the local dashboard."""
    if not 0 <= port <= 65535:
        message = "Port must be between 0 and 65535"
        raise ValueError(message)
    session_dir = prepare_session(session_dir)
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(serve(session_dir, port=port, no_browser=no_browser))
