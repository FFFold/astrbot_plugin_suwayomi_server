from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import aiohttp

from astrbot.api import logger

if TYPE_CHECKING:
    from ..suwayomi.client import SuwayomiClient

from ..suwayomi import PLUGIN_NAME
_PLUGIN_NAME = PLUGIN_NAME


async def download_one(
    session: aiohttp.ClientSession, url: str, dest: Path, retries: int = 3
) -> bool:
    for attempt in range(retries):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    ext = ".jpg"
                    ct = resp.headers.get("Content-Type", "")
                    if "png" in ct:
                        ext = ".png"
                    elif "webp" in ct:
                        ext = ".webp"
                    dest = dest.with_suffix(ext)
                    dest.write_bytes(data)
                    return True
                elif resp.status < 500:
                    return False
                logger.warning(
                    f"[{_PLUGIN_NAME}] 图片下载 HTTP {resp.status}，"
                    f"重试 {attempt + 1}/{retries}: {url}"
                )
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.warning(
                f"[{_PLUGIN_NAME}] 图片下载超时/网络错误，"
                f"重试 {attempt + 1}/{retries}: {e}"
            )
        except Exception as e:
            logger.warning(f"[{_PLUGIN_NAME}] 图片下载异常: {e}")
            return False
        if attempt < retries - 1:
            await asyncio.sleep(0.5 * (2**attempt))
    return False


async def download_images(
    urls: list[str],
    concurrency: int = 6,
    custom_tmp: str = "",
    retries: int = 3,
    headers: dict[str, str] | None = None,
) -> tuple[list[str], Path]:
    tmp_dir = Path(tempfile.mkdtemp(prefix="suwayomi_", dir=custom_tmp or None))
    try:
        connector = aiohttp.TCPConnector(limit=concurrency)
        session_kwargs: dict = {"connector": connector}
        if headers:
            session_kwargs["headers"] = headers
        async with aiohttp.ClientSession(**session_kwargs) as session:
            tasks = [
                download_one(session, url, tmp_dir / f"{i:04d}.jpg", retries)
                for i, url in enumerate(urls)
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        paths: list[str] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning(
                    f"[{_PLUGIN_NAME}] 图片 {i + 1} 下载异常: {result}"
                )
                paths.append("")
            elif result:
                matches = sorted(tmp_dir.glob(f"{i:04d}.*"))
                paths.append(str(matches[-1]) if matches else "")
            else:
                paths.append("")
        return paths, tmp_dir
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise


async def fetch_pages_local(
    client: SuwayomiClient,
    chapter_id: int,
    max_pages: int = 0,
    concurrency: int = 6,
    custom_tmp: str = "",
    retries: int = 3,
    headers: dict[str, str] | None = None,
) -> tuple[int, list[str], list[str], Path | None]:
    pages = await client.fetch_chapter_pages(chapter_id)
    if not pages:
        return 0, [], [], None
    total_pages = len(pages)
    if max_pages > 0:
        pages = pages[:max_pages]
    page_urls = [client.build_image_url(p) for p in pages]
    local_paths, tmp_dir = await download_images(
        page_urls, concurrency, custom_tmp, retries, headers
    )
    return total_pages, page_urls, local_paths, tmp_dir
