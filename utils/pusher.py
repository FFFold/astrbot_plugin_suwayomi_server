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
from .pack import build_chapter_output_path, normalize_pack_format, pack_images

if TYPE_CHECKING:
    from astrbot.api.star import Context

    from ..suwayomi.client import SuwayomiClient

from ..suwayomi import PLUGIN_NAME
_PLUGIN_NAME = PLUGIN_NAME

_cleanup_tasks: set[asyncio.Task] = set()


def is_aiocqhttp_target(context: Context, umo: str) -> bool:
    pid = umo.split(":", 1)[0]
    platform = context.get_platform_inst(pid)
    return platform is not None and platform.meta().name == "aiocqhttp"


def schedule_cleanup(tmp_dir: Path | None, delay: int = 60) -> asyncio.Task | None:
    if tmp_dir is None:
        return None

    async def _cleanup():
        await asyncio.sleep(delay)
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: shutil.rmtree(tmp_dir, ignore_errors=True)
            )
        except Exception:
            pass

    task = asyncio.create_task(_cleanup())
    _cleanup_tasks.add(task)
    task.add_done_callback(_cleanup_tasks.discard)
    return task


def cancel_pending_cleanups() -> int:
    """Cancel pending temp-dir cleanup tasks (called on plugin terminate)."""
    tasks = list(_cleanup_tasks)
    for task in tasks:
        task.cancel()
    return len(tasks)


def build_image_chain(
    page_urls: list[str],
    local_paths: list[str],
    fetch_mode: str,
    *,
    send_mode: str,
    forward_platform: bool,
    page_label: str,
    header: str | None = None,
    header_node_name: str | None = None,
    total_pages: int,
    max_pages: int,
    tail_text: str,
) -> list:
    """Build the image/forward message chain shared by read, push and AI send."""

    def _img(idx: int) -> Comp.Image:
        if fetch_mode == "download" and idx < len(local_paths) and local_paths[idx]:
            return Comp.Image.fromFileSystem(local_paths[idx])
        if fetch_mode == "download":
            logger.warning(
                f"[{_PLUGIN_NAME}] 图片 {idx + 1} 下载失败，将使用 URL 直连"
                "（带认证的服务器可能无法加载，请检查认证配置）"
            )
        return Comp.Image.fromURL(page_urls[idx])

    if send_mode == "forward" and forward_platform:
        nodes: list[Comp.Node] = []
        if header is not None:
            nodes.append(Comp.Node(
                uin="0",
                name=header_node_name or page_label,
                content=[Comp.Plain(header)],
            ))
        for i in range(len(page_urls)):
            nodes.append(Comp.Node(
                uin="0",
                name=f"{page_label} - 第 {i + 1} 页",
                content=[_img(i)],
            ))
        if total_pages > max_pages:
            nodes.append(Comp.Node(
                uin="0",
                name="提示",
                content=[Comp.Plain(tail_text)],
            ))
        return [Comp.Nodes(nodes)]

    chain: list = []
    if header is not None:
        chain.append(Comp.Plain(header))
    chain.extend(_img(i) for i in range(len(page_urls)))
    if total_pages > max_pages:
        chain.append(Comp.Plain(tail_text))
    return chain


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
    fetch_mode = config.get("image_fetch_mode", "download")
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
            if client.auth_mode != "none":
                logger.warning(
                    f"[{_PLUGIN_NAME}] 自动推送图片获取方式为 URL 模式，但 Suwayomi "
                    f"开启了 {client.auth_mode} 认证，图片可能无法加载，请改用下载模式"
                )

        if not page_urls:
            return

        chain = build_image_chain(
            page_urls, local_paths, fetch_mode,
            send_mode=send_mode,
            forward_platform=is_aiocqhttp_target(context, umo),
            page_label=ch_label,
            header=f"📖「{title}」{ch_label}",
            header_node_name=f"「{title}」{ch_label}",
            total_pages=total_pages,
            max_pages=max_pages,
            tail_text=f"... 还有 {total_pages - max_pages} 页，请使用「漫画 阅读」查看",
        )
        try:
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
        file_ext = normalize_pack_format(fmt)
        output_path = build_chapter_output_path(
            Path(valid_paths[0]).parent, title, str(ch_label), file_ext
        )

        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, pack_images, valid_paths, output_path, fmt)
        except Exception as e:
            logger.error(f"[{_PLUGIN_NAME}] 自动推送打包失败: {e}")
            return

        filename = output_path.name
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
