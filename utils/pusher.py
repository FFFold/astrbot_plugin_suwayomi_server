from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Callable

import astrbot.api.message_components as Comp
from astrbot.api import logger
from astrbot.api.event import MessageChain

from ..suwayomi.models import Chapter
from ..suwayomi.service import fmt_chapter_display
from .pack import pack_cbz, pack_pdf, pack_zip

if TYPE_CHECKING:
    from astrbot.api.star import Context

    from ..suwayomi.client import SuwayomiClient

from ..suwayomi import PLUGIN_NAME
_PLUGIN_NAME = PLUGIN_NAME


def is_aiocqhttp_target(context: Context, umo: str) -> bool:
    pid = umo.split(":", 1)[0]
    platform = context.get_platform_inst(pid)
    return platform is not None and platform.meta().name == "aiocqhttp"


def schedule_cleanup(tmp_dir: Path | None, delay: int = 60):
    if tmp_dir is None:
        return

    async def _cleanup():
        await asyncio.sleep(delay)
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: shutil.rmtree(tmp_dir, ignore_errors=True)
            )
        except Exception:
            pass

    asyncio.create_task(_cleanup())


async def push_chapter_images(
    client: SuwayomiClient,
    context: Context,
    config: dict,
    umo: str,
    title: str,
    chapter: Chapter,
    fetch_pages_local_fn: Callable,
):
    ch_label = fmt_chapter_display(chapter)
    max_pages = config.get("max_pages", 30)
    fetch_mode = config.get("image_fetch_mode", "url")
    send_mode = config.get("send_mode", "image")

    local_paths: list[str] = []
    tmp_dir: Path | None = None
    try:
        if fetch_mode == "download":
            total_pages, page_urls, local_paths, tmp_dir = await fetch_pages_local_fn(
                chapter.id, max_pages
            )
            if page_urls and not any(local_paths):
                logger.error(
                    f"[{_PLUGIN_NAME}] 自动推送 {ch_label} 时所有图片下载均失败，"
                    "请检查 Suwayomi 认证配置"
                )
                schedule_cleanup(tmp_dir, delay=60)
                return
        else:
            pages = await client.fetch_chapter_pages(chapter.id)
            if not pages:
                return
            total_pages = len(pages)
            page_urls = [client.build_image_url(p) for p in pages[:max_pages]]

        if not page_urls:
            return

        def _img(idx: int) -> Comp.Image:
            if fetch_mode == "download" and idx < len(local_paths) and local_paths[idx]:
                return Comp.Image.fromFileSystem(local_paths[idx])
            if fetch_mode == "download":
                logger.warning(
                    f"[{_PLUGIN_NAME}] 自动推送图片 {idx + 1} 下载失败，"
                    "请检查 Suwayomi 认证配置"
                )
            return Comp.Image.fromURL(page_urls[idx])

        try:
            if send_mode == "forward" and is_aiocqhttp_target(context, umo):
                nodes = [
                    Comp.Node(
                        uin="0",
                        name=f"「{title}」{ch_label}",
                        content=[Comp.Plain(f"📖「{title}」{ch_label}")],
                    )
                ]
                for i in range(len(page_urls)):
                    nodes.append(
                        Comp.Node(
                            uin="0",
                            name=f"{ch_label} - 第 {i + 1} 页",
                            content=[_img(i)],
                        )
                    )
                if total_pages > max_pages:
                    nodes.append(
                        Comp.Node(
                            uin="0",
                            name="提示",
                            content=[
                                Comp.Plain(
                                    f"... 还有 {total_pages - max_pages} 页，"
                                    f"请使用「漫画 阅读」查看"
                                )
                            ],
                        )
                    )
                await context.send_message(
                    umo, MessageChain(chain=[Comp.Nodes(nodes)])
                )
            else:
                chain = [Comp.Plain(f"📖「{title}」{ch_label}")]
                chain.extend(_img(i) for i in range(len(page_urls)))
                if total_pages > max_pages:
                    chain.append(
                        Comp.Plain(
                            f"... 还有 {total_pages - max_pages} 页，"
                            f"请使用「漫画 阅读」查看"
                        )
                    )
                await context.send_message(umo, MessageChain(chain=chain))
        except Exception as e:
            logger.warning(
                f"[{_PLUGIN_NAME}] 图片推送到{umo}失败: {e}"
            )
            await context.send_message(
                umo,
                MessageChain().message(
                    f"📖「{title}」{ch_label}已更新，"
                    f"但图片发送失败，请使用「漫画 阅读」查看"
                ),
            )
    finally:
        schedule_cleanup(tmp_dir, delay=60)


async def push_chapter_file(
    context: Context,
    config: dict,
    umo: str,
    title: str,
    chapter: Chapter,
    fetch_pages_local_fn: Callable,
):
    ch_label = fmt_chapter_display(chapter)
    fmt = config.get("download_format", "pdf")

    _, page_urls, local_paths, tmp_dir = await fetch_pages_local_fn(chapter.id)
    if not page_urls:
        schedule_cleanup(tmp_dir, delay=120)
        return

    valid_paths = [p for p in local_paths if p]
    if not valid_paths:
        schedule_cleanup(tmp_dir, delay=120)
        return

    try:
        safe_title = "".join(c for c in title if c not in r'<>:"/\|?*')[:50]
        safe_label = "".join(
            c for c in str(ch_label) if c not in r'<>:"/\|?*'
        )
        ext_map = {"zip": "zip", "pdf": "pdf", "cbz": "cbz"}
        file_ext = ext_map.get(fmt, "zip")
        output_path = Path(valid_paths[0]).parent / f"{safe_title}_{safe_label}.{file_ext}"

        try:
            loop = asyncio.get_running_loop()
            if fmt == "pdf":
                await loop.run_in_executor(None, pack_pdf, valid_paths, output_path)
            elif fmt == "cbz":
                await loop.run_in_executor(None, pack_cbz, valid_paths, output_path)
            else:
                await loop.run_in_executor(None, pack_zip, valid_paths, output_path)
        except Exception as e:
            logger.error(f"[{_PLUGIN_NAME}] 自动推送打包失败: {e}")
            return

        filename = f"{safe_title}_{safe_label}.{file_ext}"
        chain = [Comp.File(file=str(output_path), name=filename)]
        try:
            await context.send_message(umo, MessageChain(chain=chain))
        except Exception as e:
            logger.warning(f"[{_PLUGIN_NAME}] 文件推送到{umo}失败: {e}")
            await context.send_message(
                umo,
                MessageChain().message(
                    f"📖「{title}」{ch_label}已更新，"
                    f"但文件发送失败，请使用「漫画 下载」获取"
                ),
            )
    finally:
        schedule_cleanup(tmp_dir, delay=120)
