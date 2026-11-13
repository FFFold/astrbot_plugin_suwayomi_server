from __future__ import annotations

import asyncio
import math
import re
import time
import unicodedata
from typing import TYPE_CHECKING, Any, Callable

import opencc

from astrbot.api import logger

from . import PLUGIN_NAME
from .config import get_config_value
from .client import SuwayomiError
from .models import Chapter, Manga, Source
from .ranking import looks_truncated, rank_items

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

_CHAPTER_UNIT_MARKS = "话話章回集"
_VOLUME_UNIT_MARKS = "卷冊册"
_ALL_UNIT_MARKS = _CHAPTER_UNIT_MARKS + _VOLUME_UNIT_MARKS

_CHAPTER_NUM_SUFFIX_RE = re.compile(rf"[{_ALL_UNIT_MARKS}]$")
# 只删装饰性分隔符，保留 "." 与 "-"：否则 "第3.8话"/"第38话"、"第1-2话"/"第12话" 会互相粘连
_NAME_SEPARATOR_RE = re.compile(r"[\s:：·・、,，。~()\[\]【】{}!?！？\"'“”‘’#*_]+")
_LEADING_ZERO_RE = re.compile(r"(?<![\d.])0+(?=\d)")
_DIGIT_RUN_RE = re.compile(r"\d+(?:\.\d+)?")
_BARE_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_UNIT_NUMBER_RE = re.compile(rf"(?<!\d)(\d+(?:\.\d+)?)([{_ALL_UNIT_MARKS}])")


def parse_chapter_number_text(text: str) -> float | None:
    """Parse user input like '5', '第5话', '第38.5話', '第01卷' into a chapter number."""
    cleaned = unicodedata.normalize("NFKC", str(text or "")).strip()
    if cleaned.startswith("#"):
        cleaned = cleaned[1:].strip()
    if cleaned.startswith("第"):
        cleaned = cleaned[1:].strip()
    cleaned = _CHAPTER_NUM_SUFFIX_RE.sub("", cleaned).strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def chapter_name_key(text: str) -> str:
    """Normalize a chapter name or user input into a comparison key.

    NFKC (full-width -> ASCII) -> t2s (traditional -> simplified) -> casefold ->
    drop decorative separators -> strip leading zeros from digit runs.
    Leading-zero stripping lets "第1话" match "第01话"; "." and "-" survive so
    different numbers never collapse into one another.
    """
    cleaned = unicodedata.normalize("NFKC", str(text or ""))
    cleaned = normalize_zh(cleaned).casefold()
    cleaned = _NAME_SEPARATOR_RE.sub("", cleaned)
    return _LEADING_ZERO_RE.sub("", cleaned)


def _digit_runs(key: str) -> tuple[str, ...]:
    return tuple(_DIGIT_RUN_RE.findall(key))


def _name_key_matches(chapter: Chapter, key: str) -> bool:
    name_key = chapter_name_key(chapter.name)
    return name_key == key and _digit_runs(name_key) == _digit_runs(key)


def _unit_after_number(key: str, num: float) -> str | None:
    """Return the unit right after this number in `key`: "chapter", "volume" or None.

    Numbers are compared by value, so "38.50话" still marks chapter 38.5. Only
    an immediately adjacent unit counts: "07卷附录" is a volume for 7, while
    "第15话" is not a chapter for 5 (no digit lookbehind would misread it).
    """
    try:
        target = float(num)
    except (TypeError, ValueError):
        return None
    if math.isnan(target) or math.isinf(target):
        return None
    for value, mark in _UNIT_NUMBER_RE.findall(key):
        if abs(float(value) - target) < 0.01:
            return "chapter" if mark in _CHAPTER_UNIT_MARKS else "volume"
    return None


def _chapter_name_unit(chapter: Chapter, num: float) -> str | None:
    return _unit_after_number(chapter_name_key(chapter.name), num)


def _name_has_other_number(chapter: Chapter, num: float, unit: str) -> bool:
    """True when the name spells a *different* number with the same unit.

    Catches sources that renumber chapters: chapterNumber 5 but the name says
    "第15话"; a bare "5" still works, "第5话" asks for confirmation instead of
    silently reading the wrong chapter.
    """
    marks = _CHAPTER_UNIT_MARKS if unit == "chapter" else _VOLUME_UNIT_MARKS
    found = re.findall(rf"(?<!\d)(\d+(?:\.\d+)?)[{marks}]", chapter_name_key(chapter.name))
    if not found:
        return False
    return all(abs(float(value) - num) >= 0.01 for value in found)


def _substring_pattern(key: str) -> re.Pattern[str]:
    prefix = r"(?<![\d.\-]\d)(?<!\d)" if key[:1].isdigit() else ""
    suffix = r"(?!\d)(?![.\-]\d)" if key[-1:].isdigit() else ""
    return re.compile(prefix + re.escape(key) + suffix)


def match_chapters(chapters: list[Chapter], text: str) -> tuple[list[Chapter], str]:
    """Resolve user input to candidate chapters.

    Returns (candidates, kind) where kind is one of "matched", "ambiguous",
    "unit_mismatch", "name_conflict" or "not_found". Never picks silently when
    more than one chapter fits.
    """
    raw = unicodedata.normalize("NFKC", str(text or "")).strip()
    if not raw:
        return [], "not_found"
    key = chapter_name_key(raw)
    if not key:
        return [], "not_found"

    # A displayed name beats its own source number: a chapter titled "第5话"
    # stays selectable even when the source numbers it 12. Bare numbers ("5")
    # still mean the #N column, so they skip this step.
    if not _BARE_NUMBER_RE.fullmatch(key):
        exact = [ch for ch in chapters if _name_key_matches(ch, key)]
        if len(exact) == 1:
            return exact, "matched"
        if exact:
            return exact, "ambiguous"

    number = parse_chapter_number_text(raw)
    if number is not None:
        candidates = find_chapters_by_num(chapters, number)
        if not candidates:
            return [], "not_found"
        unit = _unit_after_number(key, number)
        guard_other_unit = False
        if unit:
            preferred = [ch for ch in candidates if _chapter_name_unit(ch, number) == unit]
            if preferred:
                candidates = preferred
            elif any(_chapter_name_unit(ch, number) for ch in candidates):
                return candidates, "unit_mismatch"
            else:
                guard_other_unit = True
        exact = [ch for ch in candidates if _name_key_matches(ch, key)]
        if len(exact) == 1:
            return exact, "matched"
        if len(candidates) == 1:
            chapter = candidates[0]
            conflict = unit and _name_has_other_number(chapter, number, unit)
            if guard_other_unit and unit:
                other_unit = "volume" if unit == "chapter" else "chapter"
                conflict = conflict or _name_has_other_number(chapter, number, other_unit)
            if conflict:
                return candidates, "name_conflict"
            return candidates, "matched"
        return candidates, "ambiguous"

    if len(key) >= 2:
        pattern = _substring_pattern(key)
        contained = [ch for ch in chapters if pattern.search(chapter_name_key(ch.name))]
        if len(contained) == 1:
            return contained, "matched"
        if contained:
            return contained, "ambiguous"
    return [], "not_found"



def normalize_zh(text: str) -> str:
    return _t2s.convert(text)


def fmt_chapter_num(num: float) -> int | float | str:
    try:
        if math.isnan(num) or math.isinf(num):
            return "?"
        return int(num) if num == int(num) else num
    except (ValueError, OverflowError):
        return "?"


# 控制字符/行分隔符/RTL 方向控制符 → 替换为空格；再加零宽字符（ZWSP/BOM）删除
_CONTROL_CHARS_RE = re.compile(
    "[\r\n\t\x0b\x0c\x1b\x85\u2028\u2029"
    + chr(0x202A) + "-" + chr(0x202E)
    + chr(0x2066) + "-" + chr(0x2069) + "]+"
)
_INVISIBLE_CHARS_RE = re.compile("[\u200b\ufeff]+")


def sanitize_for_message(text: str, limit: int = 50) -> str:
    """第三方文本（源站标题/章节名/来源名、Bangumi 别名）进入消息前的最小清洗。

    剥离换行/制表/垂直制表/换页/ESC/NEL/行分隔/RTL 控制符（防止伪造
    系统提示行与终端转义序列），删除零宽空格与 BOM，限长防爆屏。
    """
    cleaned = _CONTROL_CHARS_RE.sub(" ", str(text or ""))
    cleaned = _INVISIBLE_CHARS_RE.sub("", cleaned)
    return cleaned.strip()[:limit]


def fmt_chapter_display(ch: Chapter) -> str:
    """Return the human-readable chapter name for display in messages.
    Uses chapter.name if non-empty, otherwise falls back to 第X话.
    """
    name = (ch.name or "").strip()
    if name:
        return sanitize_for_message(name, limit=80)
    return f"第{fmt_chapter_num(ch.chapter_number)}话"


def fmt_chapter_label(ch: Chapter, num_counts: dict[float, int]) -> str:
    num = fmt_chapter_num(ch.chapter_number)
    dup_tag = f" (ID:{ch.id})" if num_counts.get(ch.chapter_number, 0) > 1 else ""
    if ch.name:
        return f"#{num} {sanitize_for_message(ch.name, limit=80)}{dup_tag}"
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


def _usage_line(cmd: str, manga_name_or_id: str, tail: str) -> str:
    manga = sanitize_for_message(manga_name_or_id, limit=80)
    return f"用法: /漫画 {cmd} {manga} {tail}"


def _chapter_choice_line(chapter: Chapter) -> str:
    name = sanitize_for_message(chapter.name, limit=80)
    head = f"#{fmt_chapter_num(chapter.chapter_number)} {name}".strip()
    return f"  {head} (ID:{chapter.id})"


def _choice_block(
    chapters: list[Chapter], cmd: str, manga_name_or_id: str, limit: int = 10
) -> list[str]:
    lines = [_chapter_choice_line(ch) for ch in chapters[:limit]]
    if len(chapters) > limit:
        lines.append(f"  … 共 {len(chapters)} 个")
    lines.append(_usage_line(cmd, manga_name_or_id, f"ID:{chapters[0].id}"))
    return lines


def _selector_text(chapter_num: str) -> str:
    return sanitize_for_message(chapter_num, limit=40) or "（空）"


def resolve_chapter(
    chapters: list[Chapter], chapter_num: str, manga_name_or_id: str, cmd: str
) -> tuple[Chapter | None, str | None]:
    norm = unicodedata.normalize("NFKC", str(chapter_num or "")).strip().casefold()
    norm = norm.replace("：", ":")
    if norm.startswith("id:"):
        try:
            cid = int(norm[3:])
        except ValueError:
            return None, "章节 ID 格式无效。示例: ID:123"
        target = find_chapter_by_id(chapters, cid)
        if target:
            return target, None
        return None, f"未找到 ID 为 {cid} 的章节。"

    input_text = _selector_text(chapter_num)
    matches, kind = match_chapters(chapters, chapter_num)
    if kind == "matched":
        return matches[0], None

    if kind == "not_found":
        return None, (
            f"未找到「{input_text}」对应的章节。"
            "可用：1、38.5、第5话、第1卷、章节名，或 ID:123；\n"
            f"也可先 /漫画 章节 {sanitize_for_message(manga_name_or_id, limit=80)} 查看列表。"
        )

    number = parse_chapter_number_text(chapter_num)
    number_text = fmt_chapter_num(number) if number is not None else input_text

    if kind == "unit_mismatch":
        unit = _unit_after_number(chapter_name_key(chapter_num), number)
        unit_label = "卷" if unit == "volume" else "话"
        return None, "\n".join(
            [f"「{input_text}」未匹配到{unit_label}，编号 {number_text} 只有："]
            + _choice_block(matches, cmd, manga_name_or_id)
        )

    if kind == "name_conflict":
        chapter = matches[0]
        name = sanitize_for_message(chapter.name, limit=80)
        return None, "\n".join(
            [
                f"编号 {number_text} 的章节名是「{name}」，与输入「{input_text}」不一致：",
                _chapter_choice_line(chapter).strip(),
                _usage_line(
                    cmd, manga_name_or_id, f"{number_text}  或  ID:{chapter.id}"
                ),
            ]
        )

    return None, "\n".join(
        [f"「{input_text}」匹配到 {len(matches)} 个章节，请用 ID 指定："]
        + _choice_block(matches, cmd, manga_name_or_id)
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
    cache_hours = get_config_value(config, "chapter_cache_hours", 6)
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
            src_map = {
                str(s.id): sanitize_for_message(s.display_name, limit=40)
                for s in sources
            }
        except Exception as exc:
            logger.debug(f"[{_PLUGIN_NAME}] 多结果引导获取源名失败: {exc}")

        lines = [f"找到多个结果，请使用 ID 指定。例如: /漫画 {cmd} {mangas[0].id}"]
        for m in mangas:
            status = STATUS_EMOJI.get(m.status, "未知")
            src_name = src_map.get(str(m.source_id), f"源{m.source_id}")
            lines.append(
                f"  ID {m.id}: {sanitize_for_message(m.title, limit=80)} [{status}] ({src_name})"
            )
        return None, "\n".join(lines)
    except Exception as e:
        logger.error(f"[{_PLUGIN_NAME}] resolve_manga error: {e}")
        return None, "查找漫画失败。"


async def refresh_truncated_titles(
    client: SuwayomiClient,
    mangas: list[Manga],
    limit: int = 5,
    timeout: float = 10.0,
) -> int:
    """并发刷新疑似被源站截断的标题（原地替换 manga.title），返回刷新成功数。

    只处理以 .. / 。。 / … 结尾的标题；刷新失败或结果仍疑似截断则保留原标题，
    后续排序走反向包含兜底。
    """
    targets = [m for m in mangas if looks_truncated(m.title)][: max(0, limit)]
    if not targets:
        return 0

    async def _refresh(manga: Manga) -> bool:
        try:
            fresh = await asyncio.wait_for(
                client.fetch_manga_details(manga.id), timeout
            )
        except Exception as exc:
            logger.debug(
                f"[{_PLUGIN_NAME}] 截断标题刷新失败(manga={manga.id}): {exc}"
            )
            return False
        if fresh and fresh.title and not looks_truncated(fresh.title):
            manga.title = fresh.title
            return True
        return False

    results = await asyncio.gather(*(_refresh(m) for m in targets))
    refreshed = sum(1 for ok in results if ok)
    logger.debug(
        f"[{_PLUGIN_NAME}] 截断标题刷新: 尝试 {len(targets)} 条, 成功 {refreshed} 条"
    )
    return refreshed


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
            get_config_value(config, "default_source_id", 0),
            max_sources=3,
        )

    for src in target_sources:
        try:
            result = await client.search_manga(src.id, name)
        except Exception as e:
            logger.warning(
                f"[{_PLUGIN_NAME}] 批量订阅搜索源 {src.name} 失败: {e}"
            )
            continue
        if result.mangas:
            # 源内按标题相关度选优，不再盲取第一条
            ranked, _ = rank_items(name, result.mangas, title_of=lambda m: m.title)
            return ranked[0], None

    return None, "未找到匹配结果"
