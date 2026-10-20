"""Host the dashboard frontend, API, and session files with aiohttp.

A launch token authenticates access to session data. Metadata is read-only;
missing metadata is generated before startup. The default host is loopback.
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
from cyclopts import Parameter, validators

from protein_detective.common_cli import console
from protein_detective.dashboard.data import DashboardData
from protein_detective.meta import create_meta_duckdb

COOKIE_NAME = "protein_detective_dashboard"
AUTH_MESSAGE = "Open the current dashboard launch URL printed in your terminal to authenticate."


@dataclass
class DashboardConfig:
    """Settings for one dashboard launch.

    Attributes:
        session_dir: Resolved session root.
        token: In-memory launch credential.
        origin: Exact HTTP origin accepted by request validation.
        assets: Compiled frontend directory.
    """

    session_dir: Path
    token: str
    origin: str
    assets: Path


CONFIG = web.AppKey("dashboard_config", DashboardConfig)


def _valid_token(value: object, expected: str) -> bool:
    return (
        isinstance(value, str)
        and len(value) == len(expected)
        and value.isascii()
        and secrets.compare_digest(value, expected)
    )


@web.middleware
async def _security(
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
    protected = request.path.startswith(("/api/", "/files/")) or request.path == "/files"
    if protected and request.path != "/api/auth" and not _valid_token(request.cookies.get(COOKIE_NAME), config.token):
        raise web.HTTPUnauthorized(text=AUTH_MESSAGE)
    response = await handler(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    elif request.path.startswith("/files/"):
        # Revalidate cached session bytes on every request; authentication above
        # also runs before FileResponse can produce a conditional 304 response.
        response.headers["Cache-Control"] = "private, no-cache"
    return response


async def _authenticate(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except (ValueError, UnicodeError):
        raise web.HTTPBadRequest(text="Expected a JSON token object") from None
    if not isinstance(payload, dict) or not _valid_token(payload.get("token"), request.app[CONFIG].token):
        raise web.HTTPUnauthorized(text=AUTH_MESSAGE)
    response = web.json_response({"authenticated": True})
    response.set_cookie(COOKIE_NAME, request.app[CONFIG].token, httponly=True, samesite="Strict", path="/")
    return response


async def _dataset(request: web.Request) -> web.Response:
    name = request.match_info["dataset"]
    if name not in {"summary", "candidates", "fitting", "refinements", "provenance"}:
        raise web.HTTPNotFound(text="Unknown dataset")
    if request.query:
        raise web.HTTPBadRequest(text="Dataset endpoints do not accept query parameters")
    data = DashboardData(request.app[CONFIG].session_dir)
    result = await asyncio.to_thread(getattr(data, name))
    return web.json_response(result)


async def _index(request: web.Request) -> web.FileResponse:
    path = request.match_info.get("path", "")
    if path.startswith(("api/", "files/", "assets/")) or path in {"api", "files", "assets"}:
        raise web.HTTPNotFound
    return web.FileResponse(request.app[CONFIG].assets / "index.html")


def _create_app(
    session_dir: Path, *, origin: str, token: str | None = None, assets: Path | None = None
) -> web.Application:
    app = web.Application(middlewares=[_security], client_max_size=2048)
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
    app.router.add_post("/api/auth", _authenticate)
    app.router.add_get("/api/{dataset}", _dataset)
    app.router.add_static("/files/", session_dir, show_index=False, follow_symlinks=False)
    if (assets / "assets").is_dir():
        app.router.add_static("/assets/", assets / "assets")
    app.router.add_get("/{path:.*}", _index)
    return app


def _prepare_session(session_dir: Path) -> Path:
    session_dir = session_dir.resolve()
    database = session_dir / "meta.duckdb"
    if not database.exists() and not database.is_symlink():
        console.print("[yellow]Metadata is missing; generating meta.duckdb in the session directory.[/yellow]")
        create_meta_duckdb(session_dir)
    # Never regenerate an existing database, even when it cannot be read.
    with duckdb.connect(str(database), read_only=True) as connection:
        connection.execute("SHOW TABLES").fetchall()
    return session_dir


def _dashboard_origin(host: str, port: int) -> str:
    url_host = f"[{host}]" if ":" in host else host
    return f"http://{url_host}:{port}"


async def _serve(session_dir: Path, *, port: int, no_browser: bool, host: str = "127.0.0.1") -> None:
    app = _create_app(session_dir, origin=_dashboard_origin(host, port))
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    try:
        site = web.TCPSite(runner, host, port)
        await site.start()
        addresses = runner.addresses
        actual_port = addresses[0][1]
        config = app[CONFIG]
        config.origin = _dashboard_origin(host, actual_port)
        url = f"{config.origin}/#token={config.token}"
        console.print("Do not modify the session directory while the dashboard is running.")
        console.print(url, markup=False, highlight=False, soft_wrap=True)
        if not no_browser:
            await asyncio.to_thread(webbrowser.open, url)
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


def dashboard(
    session_dir: Annotated[Path, Parameter(validator=validators.Path(file_okay=False, dir_okay=True, exists=True))],
    /,
    *,
    host: str = "127.0.0.1",
    port: Annotated[int, Parameter(validator=validators.Number(gte=0, lte=65535))] = 8080,
    browser: Annotated[bool, Parameter(negative=False)] = False,
) -> None:
    """Browse a session snapshot in the dashboard. Stop with Ctrl+C.

    Args:
        session_dir: Existing session directory. Missing metadata is generated before startup.
        host: Address to bind and use in the launch URL; defaults to loopback.
        port: Listening port from 0 to 65535; zero chooses an available port.
        browser: Open the printed launch URL automatically; disabled by default.
    """
    session_dir = _prepare_session(session_dir)
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_serve(session_dir, host=host, port=port, no_browser=not browser))
