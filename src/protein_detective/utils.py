import asyncio
from collections.abc import Iterable
from contextlib import asynccontextmanager
from pathlib import Path

import aiofiles
import aiohttp
from aiohttp_retry import ExponentialRetry, RetryClient
from tqdm.asyncio import tqdm


async def retrieve_files(
    urls: Iterable[tuple[str, str]],
    save_dir: Path,
    max_parallel_downloads: int = 5,
    retries: int = 3,
    total_timeout: int = 300,
) -> list[Path]:
    save_dir.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(max_parallel_downloads)
    async with friendly_session(retries, total_timeout) as session:
        tasks = [retrieve_file(session, url, save_dir / filename, semaphore) for url, filename in urls]
        files: list[Path] = await tqdm.gather(*tasks, desc="Downloading files")
        return files


async def retrieve_file(
    session: RetryClient,
    url: str,
    save_path: Path,
    semaphore: asyncio.Semaphore,
    ovewrite: bool = False,
    chunk_size: int = 131072,  # 128 KiB
) -> Path:
    if save_path.exists():
        if ovewrite:
            save_path.unlink()
        else:
            return save_path
    async with (
        semaphore,
        aiofiles.open(save_path, "xb") as f,
        session.get(url) as resp,
    ):
        resp.raise_for_status()
        async for chunk in resp.content.iter_chunked(chunk_size):
            await f.write(chunk)
    return save_path


@asynccontextmanager
async def friendly_session(retries: int = 3, total_timeout: int = 300):
    retry_options = ExponentialRetry(attempts=retries)
    timeout = aiohttp.ClientTimeout(total=total_timeout)  # pyrefly: ignore false positive
    async with aiohttp.ClientSession(timeout=timeout) as session:
        client = RetryClient(client_session=session, retry_options=retry_options)
        yield client
