from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Callable

from astrbot.api import logger
from astrbot.api.event import MessageChain

from . import PLUGIN_NAME
from .service import (
    fmt_chapter_display,
    fmt_chapter_label,
    fmt_chapter_num,
    get_chapter_timestamp,
    get_or_fetch_chapters,
)

if TYPE_CHECKING:
    from ..utils.subscription import SubscriptionManager
    from .client import SuwayomiClient

_PLUGIN_NAME = PLUGIN_NAME


async def check_updates(
    client: SuwayomiClient,
    sub_mgr: SubscriptionManager,
    context,
    config: dict,
    get_kv_data: Callable,
    put_kv_data: Callable,
    update_lock: asyncio.Lock,
    push_chapter_images_fn: Callable,
    push_chapter_file_fn: Callable,
    force: bool = False,
) -> str:
    logger.info(f"[{_PLUGIN_NAME}] 开始检查更新 (force={force})")
    async with update_lock:
        all_subs = await sub_mgr.get_all_subscriptions()
        if not all_subs:
            logger.info(f"[{_PLUGIN_NAME}] 没有订阅的漫画，无需检查更新。")
            return "📭 没有订阅的漫画，无需检查更新。"

        try:
            await asyncio.wait_for(client.update_library(), timeout=30)
        except asyncio.TimeoutError:
            logger.warning(f"[{_PLUGIN_NAME}] 触发书库更新超时(30s)，跳过")
        except Exception as e:
            logger.warning(f"[{_PLUGIN_NAME}] 触发书库更新失败: {e}")

        updated_mangas: list[tuple[int, str, list[str], list, dict]] = []

        cache_hours = config.get("chapter_cache_hours", 6)
        if cache_hours < -1:
            cache_hours = 0

        for manga_id_str, info in all_subs.items():
            manga_id = int(manga_id_str)
            title = info.get("title", f"ID:{manga_id}")
            latest_stored = info.get("latest_chapter_id", 0)
            subscribers = info.get("subscribers", {})

            if not subscribers:
                continue

            try:
                if force or cache_hours != 0:
                    last_ts = await get_chapter_timestamp(get_kv_data, manga_id)
                    if (
                        force
                        or last_ts == 0
                        or cache_hours == -1
                        or (time.time() - last_ts) > cache_hours * 3600
                    ):
                        try:
                            manga = await client.get_manga(manga_id)
                            if await sub_mgr.update_title(manga_id, manga.title):
                                logger.info(
                                    f"[{_PLUGIN_NAME}] 漫画标题已更新: "
                                    f"「{title}」->「{manga.title}」(ID:{manga_id})"
                                )
                                title = manga.title
                        except Exception:
                            pass

                chapters = await get_or_fetch_chapters(
                    client, get_kv_data, put_kv_data, config, manga_id, force=force
                )
                if not chapters:
                    continue

                new_chapters = []
                max_id = latest_stored
                for ch in chapters:
                    if ch.id > latest_stored:
                        new_chapters.append(ch)
                        if ch.id > max_id:
                            max_id = ch.id

                if new_chapters:
                    await sub_mgr.update_latest_chapter(manga_id, max_id)
                    logger.info(
                        f"[{_PLUGIN_NAME}] 发现更新: 「{title}」"
                        f"新增 {len(new_chapters)} 章节"
                    )
                    num_count: dict[float, int] = {}
                    for ch in chapters:
                        num_count[ch.chapter_number] = (
                            num_count.get(ch.chapter_number, 0) + 1
                        )

                    new_chapters.sort(key=lambda ch: ch.source_order)
                    ch_info = [
                        fmt_chapter_label(ch, num_count) for ch in new_chapters
                    ]
                    updated_mangas.append(
                        (manga_id, title, ch_info, new_chapters, subscribers)
                    )

            except Exception as e:
                logger.warning(
                    f"[{_PLUGIN_NAME}] 检查漫画 {title} "
                    f"(ID:{manga_id}) 更新失败: {e}"
                )
                continue

        if not updated_mangas:
            logger.info(
                f"[{_PLUGIN_NAME}] 更新检查完成: 检查 {len(all_subs)} 部漫画，"
                f"暂无更新"
            )
            return "✅ 所有订阅的漫画暂无更新。"

        logger.info(
            f"[{_PLUGIN_NAME}] 更新检查完成: 检查 {len(all_subs)} 部漫画，"
            f"发现 {len(updated_mangas)} 部有更新"
        )

        user_msgs: dict[str, list[str]] = {}
        for manga_id, title, ch_info, new_chapters, subscribers in updated_mangas:
            latest_num = fmt_chapter_num(new_chapters[-1].chapter_number)
            msg = (
                f"📢「{title}」更新了！\n"
                f"新增章节：{', '.join(ch_info)}\n"
                f"发送「漫画 阅读 {title} {latest_num}」开始阅读"
            )
            for umo in subscribers:
                user_msgs.setdefault(umo, []).append(msg)

        for umo, msgs in user_msgs.items():
            try:
                chain = MessageChain().message("\n---\n".join(msgs))
                await context.send_message(umo, chain)
            except Exception as e:
                logger.warning(
                    f"[{_PLUGIN_NAME}] 推送到 {umo} 失败: {e}"
                )

        logger.info(
            f"[{_PLUGIN_NAME}] 更新推送到 {len(user_msgs)} 个会话"
        )

        auto_push_mode = config.get("auto_push_mode", "image")
        for manga_id, title, ch_info, new_chapters, subscribers in updated_mangas:
            for umo in subscribers:
                if not sub_mgr.is_auto_push_enabled(
                    all_subs, manga_id, umo
                ):
                    continue
                for ch in new_chapters:
                    try:
                        if auto_push_mode == "file":
                            await push_chapter_file_fn(umo, title, ch)
                        else:
                            await push_chapter_images_fn(umo, title, ch)
                        await asyncio.sleep(2)
                    except Exception as e:
                        logger.warning(
                            f"[{_PLUGIN_NAME}] 自动推送"
                            f"「{title}」{fmt_chapter_display(ch)}"
                            f"到{umo}失败: {e}"
                        )

        summary_lines = [f"✅ 发现 {len(updated_mangas)} 部漫画更新："]
        for _, title, ch_info, _, _ in updated_mangas:
            summary_lines.append(f"  • {title}: {', '.join(ch_info)}")
        return "\n".join(summary_lines)


async def run_update_loop(
    interval: float,
    check_fn: Callable,
):
    logger.info(f"[{_PLUGIN_NAME}] 后台更新循环已启动，间隔 {interval}s")
    try:
        while True:
            await asyncio.sleep(interval)
            try:
                logger.debug(f"[{_PLUGIN_NAME}] 后台更新检查触发")
                await check_fn(force=True)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(
                    f"[{_PLUGIN_NAME}] 后台更新检查失败: {type(e).__name__}: {e}"
                )
    except asyncio.CancelledError:
        logger.info(f"[{_PLUGIN_NAME}] 后台更新循环已取消")
