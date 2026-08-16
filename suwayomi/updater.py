from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

import astrbot.api.message_components as Comp
from astrbot.api import logger
from astrbot.api.event import MessageChain

from . import PLUGIN_NAME
from .config import get_config_value
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
    from .models import Manga

_PLUGIN_NAME = PLUGIN_NAME

_UPDATE_CONCURRENCY = 5
_UPDATE_CARD_MAX_CHAPTERS = 24
LAST_CHECK_KV_KEY = "suwayomi_last_update_check"


async def _check_one_manga(
    client: SuwayomiClient,
    sub_mgr: SubscriptionManager,
    config: dict,
    get_kv_data: Callable,
    put_kv_data: Callable,
    force: bool,
    cache_hours: float,
    manga_id_str: str,
    info: dict,
):
    """Check one subscription for new chapters.

    Returns (update_tuple | None, is_error). None result means no update found;
    is_error=True means the check itself failed (server/source error).
    """
    if not isinstance(info, dict):
        logger.warning(
            f"[{_PLUGIN_NAME}] 订阅数据损坏: 忽略非法订阅条目 {manga_id_str!r}"
        )
        return None, False
    try:
        manga_id = int(manga_id_str)
    except (TypeError, ValueError):
        logger.warning(
            f"[{_PLUGIN_NAME}] 订阅数据损坏: 忽略非法漫画 ID {manga_id_str!r}"
        )
        return None, False
    title = info.get("title", f"ID:{manga_id}")
    latest_stored = info.get("latest_chapter_id", 0)
    subscribers = info.get("subscribers", {})

    if not subscribers:
        return None, False

    manga_obj = None
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
                    manga_obj = manga
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
            return None, False

        new_chapters = []
        max_id = latest_stored
        for ch in chapters:
            if ch.id > latest_stored:
                new_chapters.append(ch)
                if ch.id > max_id:
                    max_id = ch.id

        if not new_chapters:
            return None, False

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
        if manga_obj is None:
            # 标题同步被缓存跳过（如 WebUI 触发的 force=False 检查）时，
            # 尽力拉取元数据，保证更新卡片有封面与状态。
            try:
                manga_obj = await client.get_manga(manga_id)
            except Exception:
                pass
        return (manga_id, title, ch_info, new_chapters, subscribers, manga_obj), False
    except Exception as e:
        logger.warning(
            f"[{_PLUGIN_NAME}] 检查漫画 {title} "
            f"(ID:{manga_id}) 更新失败: {e}"
        )
        return None, True


# 更新卡片渲染回调：注入时被 check_updates await，返回卡片图片路径或 None（回退文本）。
RenderUpdateCardFn = Callable[[str, list[dict[str, Any]], str], Awaitable[str | None]]


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
    render_update_card_fn: RenderUpdateCardFn | None = None,
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

        updated_mangas: list[tuple[int, str, list[str], list, dict, Manga | None]] = []

        cache_hours = get_config_value(config, "chapter_cache_hours", 6)
        if cache_hours < -1:
            cache_hours = 0

        sem = asyncio.Semaphore(_UPDATE_CONCURRENCY)

        async def _run(item):
            async with sem:
                return await _check_one_manga(
                    client, sub_mgr, config, get_kv_data, put_kv_data,
                    force, cache_hours, item[0], item[1],
                )

        results = await asyncio.gather(
            *(_run(item) for item in all_subs.items())
        )
        updated_mangas = [
            r for r, _ in results if r is not None
        ]
        error_count = sum(1 for _, is_error in results if is_error)

        if not updated_mangas:
            if error_count and error_count == len(results):
                logger.error(
                    f"[{_PLUGIN_NAME}] 更新检查失败: "
                    f"{error_count} 部订阅漫画全部检查出错"
                )
                return (
                    "❌ 更新检查失败：所有订阅漫画均检查出错，"
                    "请检查 Suwayomi 服务与网络连接。"
                )
            logger.info(
                f"[{_PLUGIN_NAME}] 更新检查完成: 检查 {len(all_subs)} 部漫画，"
                f"暂无更新"
            )
            await put_kv_data(LAST_CHECK_KV_KEY, time.time())
            return "✅ 所有订阅的漫画暂无更新。"

        logger.info(
            f"[{_PLUGIN_NAME}] 更新检查完成: 检查 {len(all_subs)} 部漫画，"
            f"发现 {len(updated_mangas)} 部有更新"
        )

        user_msgs: dict[str, list[str]] = {}
        user_updates: dict[str, list[dict]] = {}
        for manga_id, title, ch_info, new_chapters, subscribers, manga_obj in updated_mangas:
            latest_num = fmt_chapter_num(new_chapters[-1].chapter_number)
            msg = (
                f"📢「{title}」更新了！\n"
                f"新增章节：{', '.join(ch_info)}\n"
                f"发送「漫画 阅读 {title} {latest_num}」开始阅读"
            )
            chapters_display = list(ch_info)
            if len(chapters_display) > _UPDATE_CARD_MAX_CHAPTERS:
                chapters_display = chapters_display[:_UPDATE_CARD_MAX_CHAPTERS] + [
                    f"+{len(ch_info) - _UPDATE_CARD_MAX_CHAPTERS} 话"
                ]
            item = {
                "title": title,
                "status": manga_obj.status if manga_obj else "UNKNOWN",
                "chapters": chapters_display,
                "read_hint": f"「漫画 阅读 {title} {latest_num}」",
                "thumbnail_url": manga_obj.thumbnail_url if manga_obj else None,
            }
            for umo in subscribers:
                user_msgs.setdefault(umo, []).append(msg)
                user_updates.setdefault(umo, []).append(item)

        for umo, msgs in user_msgs.items():
            try:
                if render_update_card_fn is not None:
                    heading = (
                        f"📢「{user_updates[umo][0]['title']}」更新了！"
                        if len(user_updates[umo]) == 1
                        else f"📢 {len(user_updates[umo])} 部漫画更新了"
                    )
                    try:
                        card_path = await render_update_card_fn(
                            umo, user_updates[umo], heading
                        )
                    except Exception as e:
                        logger.warning(
                            f"[{_PLUGIN_NAME}] 更新卡片渲染异常，回退文本: {e}"
                        )
                        card_path = None
                    if card_path:
                        chain = MessageChain(
                            chain=[Comp.Image.fromFileSystem(card_path)]
                        )
                        await context.send_message(umo, chain)
                        continue
                chain = MessageChain().message("\n---\n".join(msgs))
                await context.send_message(umo, chain)
            except Exception as e:
                logger.warning(
                    f"[{_PLUGIN_NAME}] 推送到 {umo} 失败: {e}"
                )

        logger.info(
            f"[{_PLUGIN_NAME}] 更新推送到 {len(user_msgs)} 个会话"
        )

        auto_push_mode = get_config_value(config, "auto_push_mode", "image")
        for manga_id, title, ch_info, new_chapters, subscribers, manga_obj in updated_mangas:
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
        for _, title, ch_info, _, _, _ in updated_mangas:
            summary_lines.append(f"  • {title}: {', '.join(ch_info)}")
        await put_kv_data(LAST_CHECK_KV_KEY, time.time())
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
