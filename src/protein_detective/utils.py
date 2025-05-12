import asyncio
from pathlib import Path

import aiofiles
import aiohttp
from tqdm.asyncio import tqdm


async def retrieve_files(
    urls: set[tuple[str, str]], save_dir: Path, max_parallel_downloads: int = 5
):
    save_dir.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(max_parallel_downloads)

    async with aiohttp.ClientSession() as session:
        tasks = [
            retrieve_file(session, url, save_dir / filename, semaphore)
            for url, filename in urls
        ]
        await tqdm.gather(*tasks)


async def retrieve_file(
    session: aiohttp.ClientSession,
    url: str,
    save_path: Path,
    semaphore: asyncio.Semaphore,
    chunk_size: int = 131072, # 128 KiB
):
    if save_path.exists():
        return
    async with (
        semaphore,
        aiofiles.open(save_path, "wb") as f,
        session.get(url) as resp,
    ):
        resp.raise_for_status()
        async for chunk in resp.content.iter_chunked(chunk_size):
            await f.write(chunk)
