from __future__ import annotations

import asyncio
import math
import re
import time
from typing import TYPE_CHECKING, Any, Callable

import opencc

from astrbot.api import logger

from . import PLUGIN_NAME
from .client import SuwayomiError
from .models import Chapter, Manga, Source

if TYPE_CHECKING:
    from ..utils.subscription import SubscriptionManager
    from .client import SuwayomiClient

_PLUGIN_NAME = PLUGIN_NAME

_t2s = opencc.OpenCC("t2s")

STATUS_EMOJI: dict[str, str] = {
    "ONGOING": "连载中",
    "COMPLETED": "已完结",
    "LICENSED": "已授权",
    "PUBLISHING_FINISHED": "已完结",
    "CANCELLED": "已停刊",
    "ON_HIATUS": "休刊中",
    "UNKNOWN": "未知",
}

KV_CHAPTER_TS = "suwayomi_chapter_timestamps"

_ts_lock = asyncio.Lock()

_CHAPTER_NUM_SUFFIX_RE = re.compile(r"(?:话|話|章)$")


def parse_chapter_number_text(text: str) -> float | None:
    """Parse user input like '5', '第5话', '第38.5話' into a chapter number."""
    cleaned = str(text or "").strip()
    if cleaned.startswith("第"):
        cleaned = cleaned[1:]
    cleaned = _CHAPTER_NUM_SUFFIX_RE.sub("", cleaned).strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def normalize_zh(text: str) -> str:
    return _t2s.convert(text)


def fmt_chapter_num(num: float) -> int | float | str:
    try:
        if math.isnan(num) or math.isinf(num):
            return "?"
        return int(num) if num == int(num) else num
    except (ValueError, OverflowError):
        return "?"


def fmt_chapter_display(ch: Chapter) -> str:
    """Return the human-readable chapter name for display in messages.
    Uses chapter.name if non-empty, otherwise falls back to 第X话.
    """
    name = (ch.name or "").strip()
    if name:
        return name
    return f"第{fmt_chapter_num(ch.chapter_number)}话"


def fmt_chapter_label(ch: Chapter, num_counts: dict[float, int]) -> str:
    num = fmt_chapter_num(ch.chapter_number)
    dup_tag = f" (ID:{ch.id})" if num_counts.get(ch.chapter_number, 0) > 1 else ""
    if ch.name:
        return f"#{num} {ch.name}{dup_tag}"
    return f"#{num}{dup_tag}"


def fmt_delivery_failure_message(total_pages: int, fetch_mode: str, auth_mode: str) -> str:
    """Explain why chapter delivery failed, distinguishing real causes."""
    if total_pages <= 0:
        return "该章节暂无可用页面。"
    if fetch_mode == "download":
        if auth_mode and auth_mode != "none":
            return (
                f"所有 {total_pages} 页图片下载失败。当前 Suwayomi 开启了 "
                f"{auth_mode} 认证，请检查认证用户名/密码是否正确。"
            )
        return (
            f"所有 {total_pages} 页图片下载失败，"
            "请检查 Suwayomi 服务是否正常运行，或尝试更换图片获取方式。"
        )
    if auth_mode and auth_mode != "none":
        return "图片 URL 模式不兼容带认证的 Suwayomi 服务器，请改用下载模式。"
    return "图片加载失败，请稍后重试。"


def find_chapters_by_num(chapters: list[Chapter], chapter_num_f: float) -> list[Chapter]:
    return [ch for ch in chapters if abs(ch.chapter_number - chapter_num_f) < 0.01]


def find_chapter_by_id(chapters: list[Chapter], chapter_id: int) -> Chapter | None:
    for ch in chapters:
        if ch.id == chapter_id:
            return ch
    return None


def resolve_chapter(
    chapters: list[Chapter], chapter_num: str, manga_name_or_id: str, cmd: str
) -> tuple[Chapter | None, str | None]:
    norm = chapter_num.replace("：", ":").lower()
    if norm.startswith("id:"):
        try:
            cid = int(norm[3:])
        except ValueError:
            return None, "章节 ID 格式无效。示例: ID:123"
        target = find_chapter_by_id(chapters, cid)
        if target:
            return target, None
        return None, f"未找到 ID 为 {cid} 的章节。"
    chapter_num_f = parse_chapter_number_text(chapter_num)
    if chapter_num_f is None:
        return None, "章节号无效。示例: 1, 38.5, 第5话 或 ID:123"
    matches = find_chapters_by_num(chapters, chapter_num_f)
    if len(matches) == 0:
        return None, f"未找到第 {fmt_chapter_num(chapter_num_f)} 话。"
    if len(matches) == 1:
        return matches[0], None
    ids = " 或 ".join(f"ID:{m.id}" for m in matches)
    return None, (
        f"第 {chapter_num} 话存在多个章节（可能为附录/番外），"
        f"请使用 ID 指定: /漫画 {cmd} {manga_name_or_id} {ids}"
    )


def split_search_query(message_str: str, keyword: str) -> tuple[str, str]:
    """Split a search command message into (keyword, source_hint).

    AstrBot's command handler splits arguments by spaces, so a trailing source
    name like "/漫画 搜索 安达与岛村 再漫画" is lost from the keyword param.
    Parse the full message instead, falling back to the keyword param.
    """
    raw = (message_str or "").strip()
    tokens = raw.split()
    args = ""
    try:
        idx = tokens.index("搜索")
        args = " ".join(tokens[idx + 1:]).strip()
    except ValueError:
        pass
    if not args:
        args = (keyword or "").strip()

    words = args.rsplit(" ", 1)
    if len(words) == 2:
        return words[0].strip(), words[1].strip()
    return args, ""


def match_source_hint(sources: list[Source], hint: str) -> Source | None:
    """Match a user-provided source hint to a source.

    Matches when the hint is a prefix of the source's name or display name,
    or equals its language code. The local source (id "0") is excluded — it
    crashes searches. A hint that does not match any source is treated as part
    of the manga keyword by the caller.
    """
    hint = (hint or "").strip().casefold()
    if not hint:
        return None
    for src in sources:
        if str(src.id) == "0":
            continue
        display_core = src.display_name.split(" (")[0].casefold()
        if (
            hint == src.name.casefold()
            or src.name.casefold().startswith(hint)
            or hint == display_core
            or display_core.startswith(hint)
            or hint == src.lang.casefold()
        ):
            return src
    return None


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def select_search_sources(
    sources: list[Source],
    source_hint: str,
    default_source_id: Any,
    max_sources: int,
) -> list[Source]:
    usable = [source for source in sources if str(source.id) != "0"]
    limit = _bounded_int(max_sources, 5, 1, 10)

    hint = source_hint.strip().casefold()
    if hint:
        matches = [
            source
            for source in usable
            if hint in source.name.casefold()
            or hint in source.display_name.casefold()
            or hint == source.lang.casefold()
        ]
        return matches[:limit]

    default_sid = str(default_source_id or "0")
    if default_sid != "0":
        matches = [source for source in usable if str(source.id) == default_sid]
        if matches:
            return matches

    # Prefer different extensions before additional language variants of the
    # same extension, so a small limit is not monopolized by MangaDex variants.
    primary: list[Source] = []
    variants: list[Source] = []
    seen_names: set[str] = set()
    for source in usable:
        key = source.name.strip().casefold() or source.display_name.strip().casefold()
        if key in seen_names:
            variants.append(source)
            continue
        seen_names.add(key)
        primary.append(source)
    return (primary + variants)[:limit]


def ttl_cache_store(
    cache: dict[str, tuple[float, Any]],
    key: str,
    value: Any,
    max_entries: int,
    now: float | None = None,
) -> None:
    """Store an entry; evict the oldest entry when over the cap.

    TTL is enforced on lookup via `ttl_cache_lookup`, not at write time.
    """
    cache[key] = (now if now is not None else time.time(), value)
    if len(cache) > max_entries:
        oldest = min(cache, key=lambda k: cache[k][0])
        del cache[oldest]


def ttl_cache_lookup(
    cache: dict[str, tuple[float, Any]],
    key: str,
    ttl: float,
    now: float | None = None,
) -> Any:
    """Return a non-expired entry or None (expired entries are removed)."""
    entry = cache.get(key)
    if entry is None:
        return None
    ts, value = entry
    if (now if now is not None else time.time()) - ts > ttl:
        cache.pop(key, None)
        return None
    return value


async def get_chapter_timestamp(
    get_kv_data: Callable, manga_id: int
) -> float:
    async with _ts_lock:
        data = await get_kv_data(KV_CHAPTER_TS, {})
        return data.get(str(manga_id), 0)


async def set_chapter_timestamp(
    get_kv_data: Callable,
    put_kv_data: Callable,
    manga_id: int,
):
    async with _ts_lock:
        data = await get_kv_data(KV_CHAPTER_TS, {})
        data[str(manga_id)] = time.time()
        await put_kv_data(KV_CHAPTER_TS, data)


async def get_or_fetch_chapters(
    client: SuwayomiClient,
    get_kv_data: Callable,
    put_kv_data: Callable,
    config: dict,
    manga_id: int,
    force: bool = False,
) -> list[Chapter] | None:
    cache_hours = config.get("chapter_cache_hours", 6)
    if cache_hours < -1:
        cache_hours = 0

    logger.debug(
        f"[{_PLUGIN_NAME}] get_or_fetch_chapters(manga_id={manga_id}, "
        f"force={force}, cache_hours={cache_hours})"
    )

    if cache_hours == -1:
        try:
            chapters = await client.fetch_chapters(manga_id)
            if chapters:
                await set_chapter_timestamp(get_kv_data, put_kv_data, manga_id)
            logger.debug(
                f"[{_PLUGIN_NAME}] 从源拉取章节(always): manga_id={manga_id}, "
                f"{len(chapters) if chapters else 0} 章节"
            )
            return chapters
        except SuwayomiError:
            logger.debug(
                f"[{_PLUGIN_NAME}] 源拉取失败，回退DB: manga_id={manga_id}"
            )
            return await client.get_chapters(manga_id)

    should_fetch = force

    if not should_fetch and cache_hours > 0:
        last_ts = await get_chapter_timestamp(get_kv_data, manga_id)
        if last_ts == 0 or (time.time() - last_ts) > cache_hours * 3600:
            should_fetch = True
            logger.debug(
                f"[{_PLUGIN_NAME}] 缓存过期或无记录: manga_id={manga_id}, "
                f"last_ts={last_ts}"
            )

    if not should_fetch:
        chapters = await client.get_chapters(manga_id)
        if chapters:
            logger.debug(
                f"[{_PLUGIN_NAME}] 缓存命中: manga_id={manga_id}, "
                f"{len(chapters)} 章节"
            )
            return chapters
        should_fetch = True
        logger.debug(
            f"[{_PLUGIN_NAME}] DB为空，触发源拉取: manga_id={manga_id}"
        )

    chapters = await client.fetch_chapters(manga_id)
    if chapters:
        await set_chapter_timestamp(get_kv_data, put_kv_data, manga_id)
    logger.debug(
        f"[{_PLUGIN_NAME}] 从源拉取章节: manga_id={manga_id}, "
        f"{len(chapters) if chapters else 0} 章节"
    )
    return chapters


async def resolve_manga(
    client: SuwayomiClient,
    sub_mgr: SubscriptionManager,
    umo: str,
    name_or_id: str,
    cmd: str,
) -> tuple[Manga | None, str | None]:
    try:
        manga_id = int(name_or_id)
        manga = await client.get_manga(manga_id)
        return manga, None
    except (ValueError, SuwayomiError):
        pass

    norm_input = normalize_zh(name_or_id)
    subs = await sub_mgr.get_subscriptions(umo)
    for s in subs:
        if norm_input in normalize_zh(s["title"]):
            try:
                manga = await client.get_manga(s["manga_id"])
                return manga, None
            except SuwayomiError:
                continue

    try:
        mangas = await client.search_manga_by_title(name_or_id)
        if len(mangas) == 0:
            return None, "未找到该漫画。"
        if len(mangas) == 1:
            return mangas[0], None

        src_map: dict[str, str] = {}
        try:
            sources = await client.get_sources()
            src_map = {str(s.id): s.display_name for s in sources}
        except Exception:
            pass

        lines = [f"找到多个结果，请使用 ID 指定。例如: /漫画 {cmd} {mangas[0].id}"]
        for m in mangas:
            status = STATUS_EMOJI.get(m.status, "未知")
            src_name = src_map.get(str(m.source_id), f"源{m.source_id}")
            lines.append(f"  ID {m.id}: {m.title} [{status}] ({src_name})")
        return None, "\n".join(lines)
    except Exception as e:
        logger.error(f"[{_PLUGIN_NAME}] resolve_manga error: {e}")
        return None, "查找漫画失败。"


async def search_best_match(
    client: SuwayomiClient,
    config: dict,
    name: str,
    source_filter: Source | None = None,
) -> tuple[Manga | None, str | None]:
    sources = await client.get_sources()
    if not sources:
        return None, "未找到已安装的漫画源"

    if source_filter:
        target_sources = [source_filter]
    else:
        # Same selection as the AI tool path: skip the local source and prefer
        # distinct extensions before language variants (MangaDex has 60+).
        target_sources = select_search_sources(
            sources,
            "",
            config.get("default_source_id", 0),
            max_sources=3,
        )

    for src in target_sources:
        try:
            result = await client.search_manga(src.id, name)
            if result.mangas:
                return result.mangas[0], None
        except Exception as e:
            logger.warning(
                f"[{_PLUGIN_NAME}] 批量订阅搜索源 {src.name} 失败: {e}"
            )

    return None, "未找到匹配结果"
