from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from .models import Chapter, Manga, Source
from .service import fmt_chapter_display, get_or_fetch_chapters


_LATEST_SELECTORS = {"latest", "newest", "最新", "最新一话", "最新一話"}
_LIST_SELECTORS = {"", "list", "all", "列表", "全部"}
_CHAPTER_ID_RE = re.compile(r"^id\s*[:：]\s*(\d+)$", re.IGNORECASE)
_RESET_SUCCESS_TEXT = "✅ Conversation reset successfully."


def is_successful_conversation_reset(event: Any) -> bool:
    """Return whether AstrBot has successfully handled a conversation reset."""
    try:
        if event.get_extra("_clean_group_context_session", False):
            return True
    except Exception:
        pass

    try:
        result = event.get_result()
    except Exception:
        return False
    if result is None:
        return False
    return any(
        _RESET_SUCCESS_TEXT in str(getattr(component, "text", ""))
        for component in getattr(result, "chain", ())
    )


class AiInteractionState:
    """Short-lived per-sender candidates plus per-turn send receipts."""

    def __init__(self, ttl: int = 600):
        self.ttl = max(1, int(ttl))
        self._chapters: dict[
            tuple[str, str], tuple[float, set[tuple[int, int]]]
        ] = {}
        self._send_receipts: dict[
            tuple[tuple[str, str], int, int, int], float
        ] = {}

    def clear(self):
        self._chapters.clear()
        self._send_receipts.clear()

    def clear_origin(self, unified_msg_origin: str):
        """Clear transient manga state for one AstrBot conversation origin."""
        origin = str(unified_msg_origin)
        self._chapters = {
            scope: entry
            for scope, entry in self._chapters.items()
            if scope[0] != origin
        }
        self._send_receipts = {
            receipt: sent_at
            for receipt, sent_at in self._send_receipts.items()
            if receipt[0][0] != origin
        }

    def remember_chapters(
        self,
        scope: tuple[str, str],
        manga_id: int,
        chapter_ids: set[int],
        now: float | None = None,
    ):
        if not chapter_ids:
            return
        timestamp = time.time() if now is None else now
        entry = self._chapters.get(scope)
        known: set[tuple[int, int]] = set()
        if entry and timestamp - entry[0] <= self.ttl:
            known.update(entry[1])
        known.update((int(manga_id), int(chapter_id)) for chapter_id in chapter_ids)
        self._chapters[scope] = (timestamp, known)

    def was_chapter_exposed(
        self,
        scope: tuple[str, str],
        manga_id: int,
        chapter_id: int,
        now: float | None = None,
    ) -> bool:
        timestamp = time.time() if now is None else now
        entry = self._chapters.get(scope)
        if entry is None:
            return False
        if timestamp - entry[0] > self.ttl:
            del self._chapters[scope]
            return False
        return (int(manga_id), int(chapter_id)) in entry[1]

    def already_sent(
        self,
        receipt: tuple[tuple[str, str], int, int, int],
        now: float | None = None,
    ) -> bool:
        timestamp = time.time() if now is None else now
        self._send_receipts = {
            key: sent_at
            for key, sent_at in self._send_receipts.items()
            if timestamp - sent_at <= self.ttl
        }
        return receipt in self._send_receipts

    def mark_sent(
        self,
        receipt: tuple[tuple[str, str], int, int, int],
        now: float | None = None,
    ):
        self._send_receipts[receipt] = time.time() if now is None else now


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def manga_to_agent_dict(manga: Manga, source_name: str | None = None) -> dict:
    description = (manga.description or "").strip()
    return {
        "manga_id": manga.id,
        "source_id": manga.source_id,
        "source_name": source_name or f"源{manga.source_id}",
        "title": manga.title,
        "status": manga.status,
        "author": manga.author or "",
        "artist": manga.artist or "",
        "description": description[:500],
        "genres": list(manga.genre[:20]),
        "in_library": manga.in_library,
    }


def chapter_to_agent_dict(chapter: Chapter) -> dict:
    return {
        "chapter_id": chapter.id,
        "chapter_number": chapter.chapter_number,
        "name": fmt_chapter_display(chapter),
        "upload_date": chapter.upload_date,
        "page_count": chapter.page_count,
        "source_order": chapter.source_order,
        "is_read": chapter.is_read,
        "is_downloaded": chapter.is_downloaded,
    }


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

    return usable[:limit]


async def search_manga_for_agent(
    client: Any,
    config: Any,
    query: str,
    source_hint: str = "",
) -> dict:
    query = str(query or "").strip()
    source_hint = str(source_hint or "").strip()
    if not query:
        return {"success": False, "error": "query 不能为空", "results": []}

    sources = await client.get_sources()
    max_sources = _bounded_int(config.get("ai_max_sources", 5), 5, 1, 10)
    per_source_limit = _bounded_int(
        config.get("ai_results_per_source", 5), 5, 1, 20
    )
    target_sources = select_search_sources(
        sources,
        source_hint,
        config.get("default_source_id", 0),
        max_sources,
    )
    if not target_sources:
        return {
            "success": False,
            "error": "没有匹配的可用漫画源",
            "query": query,
            "source_hint": source_hint,
            "available_sources": [
                {"source_id": source.id, "name": source.display_name, "lang": source.lang}
                for source in sources
                if str(source.id) != "0"
            ][:20],
            "results": [],
        }

    async def _search(source: Source):
        try:
            result = await client.search_manga(source.id, query)
            return source, result, None
        except Exception as exc:  # one broken source must not fail the whole search
            return source, None, str(exc)

    responses = await asyncio.gather(*(_search(source) for source in target_sources))
    results: list[dict] = []
    errors: list[dict] = []
    seen_ids: set[int] = set()
    successful_sources = 0

    for source, search_result, error in responses:
        if error is not None:
            errors.append({"source": source.display_name, "error": error})
            continue
        successful_sources += 1
        for manga in search_result.mangas[:per_source_limit]:
            if manga.id in seen_ids:
                continue
            seen_ids.add(manga.id)
            results.append(manga_to_agent_dict(manga, source.display_name))

    return {
        "success": successful_sources > 0,
        "query": query,
        "source_hint": source_hint,
        "searched_sources": [source.display_name for source in target_sources],
        "result_count": len(results),
        "results": results,
        "source_errors": errors,
        "instruction": (
            "使用 manga_id 继续查询章节；如果多个结果都可能匹配，先让用户确认，"
            "不要按列表位置猜测。"
        ),
    }


def _select_chapter_candidates(
    chapters: list[Chapter], selector: str
) -> tuple[Chapter | None, list[Chapter], str | None]:
    normalized = selector.strip().casefold()
    ordered = sorted(chapters, key=lambda chapter: chapter.source_order)

    if normalized in _LATEST_SELECTORS:
        return (ordered[0] if ordered else None), ordered[:1], None

    match = _CHAPTER_ID_RE.fullmatch(normalized)
    if match:
        chapter_id = int(match.group(1))
        candidates = [chapter for chapter in chapters if chapter.id == chapter_id]
        if not candidates:
            return None, [], f"未找到章节 ID {chapter_id}"
        return candidates[0], candidates, None

    cleaned = normalized
    if cleaned.startswith("第"):
        cleaned = cleaned[1:]
    cleaned = re.sub(r"(?:话|話|章)$", "", cleaned).strip()
    try:
        number = float(cleaned)
    except ValueError:
        return None, [], (
            "selector 应为 latest、list、章节号或 ID:数字；"
            f"当前值为 {selector!r}"
        )

    candidates = [chapter for chapter in chapters if chapter.chapter_number == number]
    if not candidates:
        return None, [], f"未找到第 {cleaned} 话"
    if len(candidates) > 1:
        return None, candidates, "同一章节号存在多个结果，需要使用 chapter_id 明确选择"
    return candidates[0], candidates, None


async def get_chapters_for_agent(
    client: Any,
    get_kv_data: Any,
    put_kv_data: Any,
    config: Any,
    manga_id: int,
    selector: str = "latest",
    refresh: bool = False,
    limit: int = 20,
) -> dict:
    try:
        manga_id = int(manga_id)
    except (TypeError, ValueError):
        return {"success": False, "error": "manga_id 必须是整数"}

    selector = str(selector or "latest").strip()
    limit = _bounded_int(limit, 20, 1, 50)
    manga = await client.get_manga(manga_id)
    chapters = await get_or_fetch_chapters(
        client,
        get_kv_data,
        put_kv_data,
        config,
        manga_id,
        force=bool(refresh),
    )
    ordered = sorted(chapters, key=lambda chapter: chapter.source_order)
    if not ordered:
        return {
            "success": True,
            "manga": manga_to_agent_dict(manga),
            "selector": selector,
            "selected_chapter": None,
            "chapters": [],
            "message": "该漫画暂无章节",
        }

    if selector.casefold() in _LIST_SELECTORS:
        candidates = ordered[:limit]
        selected = None
        selection_error = None
    else:
        selected, candidates, selection_error = _select_chapter_candidates(
            ordered, selector
        )

    return {
        "success": selection_error is None,
        "manga": manga_to_agent_dict(manga),
        "selector": selector,
        "chapter_count": len(ordered),
        "selected_chapter": (
            chapter_to_agent_dict(selected) if selected is not None else None
        ),
        "chapters": [chapter_to_agent_dict(chapter) for chapter in candidates[:limit]],
        "error": selection_error,
        "instruction": (
            "发送章节时必须使用这里返回的 manga_id 和 chapter_id。"
            if selection_error is None
            else "先让用户根据候选 chapter_id 确认具体章节。"
        ),
    }
