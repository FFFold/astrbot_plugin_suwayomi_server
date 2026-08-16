from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import astrbot.api.message_components as Comp
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star

from .suwayomi import PLUGIN_NAME
from .suwayomi.ai_service import (
    AiInteractionState,
    get_chapters_for_agent,
    get_subscriptions_for_agent,
    is_successful_conversation_reset,
    search_manga_for_agent,
    subscribe_manga_for_agent,
    unsubscribe_manga_for_agent,
)
from .suwayomi.ai_tools import AI_TOOL_NAMES, build_ai_tools, effective_tool_timeout
from .suwayomi.cards import (
    CardCache,
    build_batch_card,
    build_chapter_cards,
    build_search_card,
    build_subscribe_confirm_card,
    build_subscriptions_card,
    build_update_card,
    embed_covers,
    render_card_cached,
)
from .suwayomi.client import SuwayomiClient, SuwayomiError
from .suwayomi.models import Manga, SearchResult
from .suwayomi.service import (
    STATUS_EMOJI,
    fmt_chapter_display,
    fmt_chapter_label,
    fmt_chapter_num,
    fmt_delivery_failure_message,
    get_or_fetch_chapters,
    match_source_hint,
    normalize_zh,
    resolve_chapter,
    resolve_manga,
    search_best_match,
    select_search_sources,
    split_search_query,
    ttl_cache_lookup,
    ttl_cache_store,
)
from .suwayomi.updater import check_updates as _check_updates, run_update_loop
from .utils.downloader import download_cover, fetch_pages_local
from .utils.pack import (
    build_chapter_output_path,
    normalize_pack_format,
    pack_images,
    parse_download_args,
)
from .utils.pusher import (
    build_image_chain,
    cancel_pending_cleanups,
    push_chapter_file,
    push_chapter_images,
    schedule_cleanup,
    schedule_cleanup_file,
)
from .utils.subscription import SubscriptionManager
from .web.api import (
    api_config_get,
    api_config_post,
    api_sources as api_sources_handler,
    api_status,
    api_subscription_delete,
    api_subscription_push,
    api_subscriptions,
    api_update as api_update_handler,
)

_CACHE_TTL = 600
_SEARCH_CACHE_MAX_ENTRIES = 64
_AI_TOOL_REPAIR_KEY = "suwayomi_ai_tool_activation_repaired_v1"
CARD_CACHE_TTL = 600


class SuwayomiPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.client = SuwayomiClient(
            server_url=config.get("server_url", "http://localhost:4567"),
            auth_mode=config.get("auth_mode", "none"),
            username=config.get("username", ""),
            password=config.get("password", ""),
        )
        self.sub_mgr = SubscriptionManager(self)
        self._search_cache: dict[str, tuple[float, dict[str, Manga]]] = {}
        self._ai_state = AiInteractionState(ttl=_CACHE_TTL)
        self._ai_send_locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._card_cache = CardCache(ttl=CARD_CACHE_TTL)
        self._update_lock = asyncio.Lock()
        self._bg_task: asyncio.Task | None = None
        self._check_updates_fn = None
        self._build_check_updates_fn()
        self._try_start_bg_loop()
        logger.info(
            f"[{PLUGIN_NAME}] 插件已加载 | 服务器: {config.get('server_url')} | "
            f"缓存: {config.get('chapter_cache_hours', 6)}h | "
            f"检查间隔: {config.get('check_interval', 60)}min"
        )

        context.register_web_api(
            f"/{PLUGIN_NAME}/status", self._api_status, ["GET"], "获取服务器状态",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/subscriptions", self._api_subscriptions, ["GET"], "获取全部订阅",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/subscription/delete", self._api_subscription_delete, ["POST"], "删除订阅",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/subscription/push", self._api_subscription_push, ["POST"], "切换推送",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/config", self._api_config, ["GET", "POST"], "插件配置",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/sources", self._api_sources, ["GET"], "获取源列表",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/update", self._api_update, ["POST"], "手动更新",
        )
        self._sync_ai_tools()

    # ── AI tools ───────────────────────────────────────────────────

    @staticmethod
    def _config_bool(value, default: bool = False) -> bool:
        if value is None:
            return default
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on", "开启"}
        return bool(value)

    def _sync_ai_tools(self):
        enabled = self._config_bool(self.config.get("enable_ai_tools", True), True)
        previous_enabled = getattr(self, "_ai_tools_config_enabled", None)
        if enabled:
            self.context.add_llm_tools(*build_ai_tools(self))
            if previous_enabled is False:
                for name in AI_TOOL_NAMES:
                    try:
                        self.context.activate_llm_tool(name)
                    except Exception as exc:
                        logger.warning(f"[{PLUGIN_NAME}] 重新启用 AI Tool {name} 失败: {exc}")
            self._ai_tools_config_enabled = True
            logger.info(f"[{PLUGIN_NAME}] AI 漫画工具已注册: {', '.join(AI_TOOL_NAMES)}")
            return

        for name in AI_TOOL_NAMES:
            try:
                self.context.deactivate_llm_tool(name)
            except Exception:
                pass
        self._ai_tools_config_enabled = False
        logger.info(f"[{PLUGIN_NAME}] AI 漫画工具已关闭")

    def _ai_timeout(
        self,
        astrbot_tool_timeout: int | float | None = None,
        preferred_minimum: int | float = 0,
    ) -> float:
        try:
            value = int(self.config.get("ai_tool_timeout_sec", 60))
        except (TypeError, ValueError):
            value = 60
        configured_timeout = max(10, min(value, 300))
        return effective_tool_timeout(
            configured_timeout,
            astrbot_tool_timeout,
            preferred_minimum,
        )

    @staticmethod
    def _ai_scope_key(event: AstrMessageEvent) -> tuple[str, str]:
        try:
            sender_id = str(event.get_sender_id() or "")
        except Exception:
            sender_id = ""
        return event.unified_msg_origin, sender_id

    def _remember_ai_chapters(
        self,
        event: AstrMessageEvent,
        manga_id: int,
        chapter_ids: set[int],
    ):
        if not chapter_ids:
            return
        key = self._ai_scope_key(event)
        self._ai_state.remember_chapters(key, manga_id, chapter_ids)

    def _was_ai_chapter_exposed(
        self, event: AstrMessageEvent, manga_id: int, chapter_id: int
    ) -> bool:
        return self._ai_state.was_chapter_exposed(
            self._ai_scope_key(event), manga_id, chapter_id
        )

    def _clear_manga_memory(self, unified_msg_origin: str):
        """Clear only transient manga state belonging to one AstrBot session."""
        origin = str(unified_msg_origin)
        self._search_cache.pop(origin, None)
        self._ai_state.clear_origin(origin)
        for scope in tuple(self._ai_send_locks):
            if scope[0] == origin:
                self._ai_send_locks.pop(scope, None)

    @filter.after_message_sent()
    async def _clear_manga_memory_after_reset(self, event: AstrMessageEvent):
        """Keep plugin-side manga context in sync with AstrBot's /reset."""
        if not is_successful_conversation_reset(event):
            return
        origin = str(event.unified_msg_origin or "")
        if not origin:
            return
        self._clear_manga_memory(origin)
        logger.info(f"[{PLUGIN_NAME}] /reset 已清理漫画会话记忆: {origin}")

    @staticmethod
    def _tool_json(data: dict) -> str:
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    async def _ai_search_manga_tool(
        self,
        event: AstrMessageEvent,
        query: str,
        source_hint: str = "",
        search_all_sources: bool = False,
        *,
        _astrbot_tool_timeout: int | float | None = None,
    ) -> str:
        if not self._config_bool(self.config.get("enable_ai_tools", True), True):
            return self._tool_json({"success": False, "error": "AI 漫画工具已关闭"})
        try:
            async with asyncio.timeout(self._ai_timeout(_astrbot_tool_timeout)):
                result = await search_manga_for_agent(
                    self.client,
                    self.config,
                    query,
                    source_hint,
                    self._config_bool(search_all_sources),
                )
            return self._tool_json(result)
        except TimeoutError:
            return self._tool_json({"success": False, "error": "搜索漫画超时，请缩小漫画源范围或稍后重试"})
        except Exception as exc:
            logger.error(f"[{PLUGIN_NAME}] AI search tool error: {exc}")
            return self._tool_json({"success": False, "error": "漫画搜索失败，服务暂时不可用"})

    async def _ai_get_chapters_tool(
        self,
        event: AstrMessageEvent,
        manga_id: int,
        selector: str = "latest",
        refresh: bool = False,
        limit: int = 20,
        *,
        _astrbot_tool_timeout: int | float | None = None,
    ) -> str:
        if not self._config_bool(self.config.get("enable_ai_tools", True), True):
            return self._tool_json({"success": False, "error": "AI 漫画工具已关闭"})
        try:
            async with asyncio.timeout(self._ai_timeout(_astrbot_tool_timeout)):
                result = await get_chapters_for_agent(
                    self.client,
                    self.get_kv_data,
                    self.put_kv_data,
                    self.config,
                    manga_id,
                    selector,
                    refresh,
                    limit,
                )
            if result.get("success"):
                resolved_manga_id = int(result["manga"]["manga_id"])
                chapter_ids = {
                    int(chapter["chapter_id"])
                    for chapter in result.get("chapters", [])
                    if chapter.get("chapter_id") is not None
                }
                selected = result.get("selected_chapter")
                if selected and selected.get("chapter_id") is not None:
                    chapter_ids.add(int(selected["chapter_id"]))
                self._remember_ai_chapters(event, resolved_manga_id, chapter_ids)
            return self._tool_json(result)
        except TimeoutError:
            return self._tool_json({"success": False, "error": "获取漫画章节超时，请稍后重试"})
        except Exception as exc:
            logger.error(f"[{PLUGIN_NAME}] AI chapters tool error: {exc}")
            return self._tool_json({"success": False, "error": "获取漫画章节失败"})

    async def _ai_send_chapter_tool(
        self,
        event: AstrMessageEvent,
        manga_id: int,
        chapter_id: int,
        confirmed_user_intent: bool,
        format: str = "pdf",
        *,
        _astrbot_tool_timeout: int | float | None = None,
    ) -> str:
        if not self._config_bool(self.config.get("enable_ai_tools", True), True):
            return self._tool_json({"success": False, "sent": False, "error": "AI 漫画工具已关闭"})
        if not self._config_bool(self.config.get("allow_ai_send", True), True):
            return self._tool_json({"success": False, "sent": False, "error": "管理员已禁止 AI 直接发送漫画"})
        if not self._config_bool(confirmed_user_intent):
            return self._tool_json({"success": False, "sent": False, "error": "用户尚未明确要求阅读或发送漫画，不能主动发送"})

        try:
            manga_id = int(manga_id)
            chapter_id = int(chapter_id)
        except (TypeError, ValueError):
            return self._tool_json({"success": False, "sent": False, "error": "manga_id 和 chapter_id 必须是整数"})

        if not self._was_ai_chapter_exposed(event, manga_id, chapter_id):
            return self._tool_json({
                "success": False,
                "sent": False,
                "error": "该章节不在当前用户最近的章节查询结果中；请先调用 suwayomi_get_chapters 明确章节",
            })

        send_format = str(format or "pdf").strip().lower()
        if send_format not in {"pdf", "zip", "cbz", "image"}:
            return self._tool_json({
                "success": False,
                "sent": False,
                "error": "format 仅支持 pdf、zip、cbz 或 image；默认应使用 pdf",
            })
        send_timeout = self._ai_timeout(
            _astrbot_tool_timeout,
            preferred_minimum=110 if send_format != "image" else 0,
        )

        scope_key = self._ai_scope_key(event)
        lock = self._ai_send_locks.setdefault(scope_key, asyncio.Lock())
        async with lock:
            tmp_dir: Path | None = None
            try:
                async with asyncio.timeout(send_timeout):
                    manga = await self.client.get_manga(manga_id)
                    chapters = await get_or_fetch_chapters(
                        self.client,
                        self.get_kv_data,
                        self.put_kv_data,
                        self.config,
                        manga_id,
                    )
                    target = next((ch for ch in chapters if ch.id == chapter_id), None)
                    if target is None:
                        return self._tool_json({"success": False, "sent": False, "error": "指定章节不属于该漫画或已经失效"})
                    filename = None
                    if send_format == "image":
                        result, total_pages, delivered_pages, tmp_dir = (
                            await self._prepare_chapter_delivery(event, target)
                        )
                    else:
                        (
                            result,
                            total_pages,
                            delivered_pages,
                            tmp_dir,
                            filename,
                        ) = await self._prepare_chapter_file_delivery(
                            event, manga, target, send_format
                        )
                    if result is None:
                        return self._tool_json({"success": False, "sent": False, "error": "该章节没有成功下载的页面，无法发送"})
                    await event.send(result)
                return self._tool_json({
                    "success": True,
                    "sent": True,
                    "title": manga.title,
                    "chapter_id": target.id,
                    "chapter": fmt_chapter_display(target),
                    "format": send_format,
                    "filename": filename,
                    "total_pages": total_pages,
                    "pages_delivered": delivered_pages,
                    "instruction": "章节已成功发送给用户，请确认发送格式，请勿重复发送。",
                })
            except TimeoutError:
                return self._tool_json({"success": False, "sent": False, "error": "加载或发送章节超时"})
            except Exception as exc:
                logger.error(f"[{PLUGIN_NAME}] AI send chapter tool error: {exc}")
                return self._tool_json({"success": False, "sent": False, "error": "发送漫画章节失败"})
            finally:
                schedule_cleanup(tmp_dir, delay=120 if send_format != "image" else 60)

    async def _ai_subscribe_manga_tool(
        self,
        event: AstrMessageEvent,
        manga_id: int,
        confirmed_user_intent: bool,
        push_enabled: bool | None = None,
        *,
        _astrbot_tool_timeout: int | float | None = None,
    ) -> str:
        if not self._config_bool(self.config.get("enable_ai_tools", True), True):
            return self._tool_json({"success": False, "error": "AI 漫画工具已关闭"})
        if not self._config_bool(confirmed_user_intent):
            return self._tool_json({"success": False, "error": "用户尚未明确要求订阅，不能自动订阅"})
        try:
            async with asyncio.timeout(self._ai_timeout(_astrbot_tool_timeout)):
                result = await subscribe_manga_for_agent(
                    self.client,
                    self.sub_mgr,
                    self.get_kv_data,
                    self.put_kv_data,
                    self.config,
                    event.unified_msg_origin,
                    manga_id,
                    push_enabled,
                )
            return self._tool_json(result)
        except TimeoutError:
            return self._tool_json({"success": False, "error": "订阅漫画超时，请稍后重试"})
        except Exception as exc:
            logger.error(f"[{PLUGIN_NAME}] AI subscribe tool error: {exc}")
            return self._tool_json({"success": False, "error": "订阅漫画失败，服务暂时不可用"})

    async def _ai_get_subscriptions_tool(
        self,
        event: AstrMessageEvent,
        *,
        _astrbot_tool_timeout: int | float | None = None,
    ) -> str:
        if not self._config_bool(self.config.get("enable_ai_tools", True), True):
            return self._tool_json({"success": False, "error": "AI 漫画工具已关闭"})
        try:
            async with asyncio.timeout(self._ai_timeout(_astrbot_tool_timeout)):
                result = await get_subscriptions_for_agent(
                    self.sub_mgr,
                    event.unified_msg_origin,
                )
            return self._tool_json(result)
        except TimeoutError:
            return self._tool_json({"success": False, "error": "获取订阅列表超时"})
        except Exception as exc:
            logger.error(f"[{PLUGIN_NAME}] AI get subscriptions tool error: {exc}")
            return self._tool_json({"success": False, "error": "获取订阅列表失败"})

    async def _ai_unsubscribe_manga_tool(
        self,
        event: AstrMessageEvent,
        manga_id: int,
        confirmed_user_intent: bool,
        *,
        _astrbot_tool_timeout: int | float | None = None,
    ) -> str:
        if not self._config_bool(self.config.get("enable_ai_tools", True), True):
            return self._tool_json({"success": False, "error": "AI 漫画工具已关闭"})
        if not self._config_bool(confirmed_user_intent):
            return self._tool_json({"success": False, "error": "用户尚未明确要求取消订阅，不能自动取消"})
        try:
            async with asyncio.timeout(self._ai_timeout(_astrbot_tool_timeout)):
                result = await unsubscribe_manga_for_agent(
                    self.sub_mgr,
                    event.unified_msg_origin,
                    manga_id,
                )
            return self._tool_json(result)
        except TimeoutError:
            return self._tool_json({"success": False, "error": "取消订阅超时，请稍后重试"})
        except Exception as exc:
            logger.error(f"[{PLUGIN_NAME}] AI unsubscribe tool error: {exc}")
            return self._tool_json({"success": False, "error": "取消订阅失败，服务暂时不可用"})

    # ── Lifecycle ──────────────────────────────────────────────────

    def _try_start_bg_loop(self):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._bg_task is not None:
            return
        interval = float(self.config.get("check_interval", 60)) * 60
        logger.info(
            f"[{PLUGIN_NAME}] 启动后台更新循环 | "
            f"间隔: {interval / 60:.0f}min ({interval}s)"
        )
        self._start_bg_task(interval)

    def _start_bg_task(self, interval: float):
        async def _check_wrapper(force=False):
            fn = self._check_updates_fn
            if fn is None:
                logger.warning(
                    f"[{PLUGIN_NAME}] 检查更新: _check_updates_fn 未就绪，跳过"
                )
                return
            return await fn(force=force)

        self._bg_task = asyncio.create_task(
            run_update_loop(interval, _check_wrapper)
        )

        def _on_task_done(task: asyncio.Task):
            if not task.cancelled():
                exc = task.exception()
                if exc:
                    logger.error(
                        f"[{PLUGIN_NAME}] 后台更新循环异常退出: {exc}"
                    )

        self._bg_task.add_done_callback(_on_task_done)

    @filter.on_astrbot_loaded()
    async def on_loaded(self):
        try:
            await self.sub_mgr.run_migration()
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] 订阅数据迁移失败: {e}")
        if self._config_bool(self.config.get("enable_ai_tools", True), True):
            repaired = await self.get_kv_data(_AI_TOOL_REPAIR_KEY, False)
            if not repaired:
                repair_ok = True
                for name in AI_TOOL_NAMES:
                    try:
                        if not self.context.activate_llm_tool(name):
                            repair_ok = False
                    except Exception as exc:
                        repair_ok = False
                        logger.warning(f"[{PLUGIN_NAME}] 修复 AI Tool 激活状态失败 {name}: {exc}")
                if repair_ok:
                    await self.put_kv_data(_AI_TOOL_REPAIR_KEY, True)
                    logger.info(f"[{PLUGIN_NAME}] 已完成 AI Tool 激活状态一次性修复")
        if self._bg_task is None:
            interval = float(self.config.get("check_interval", 60)) * 60
            self._start_bg_task(interval)

    async def terminate(self):
        if self._bg_task and not self._bg_task.done():
            self._bg_task.cancel()
        cancel_pending_cleanups()
        self._ai_state.clear()
        self._ai_send_locks.clear()
        await self.client.close()
        logger.info(f"[{PLUGIN_NAME}] 插件已卸载")

    # ── Push callbacks builder ─────────────────────────────────────

    def _build_check_updates_fn(self):
        client = self.client
        context = self.context
        config = self.config

        async def _push_images(umo, title, chapter):
            return await push_chapter_images(
                client, context, config,
                umo, title, chapter,
                lambda cid, mp=0: fetch_pages_local(
                    client, cid, max_pages=mp,
                    concurrency=config.get("download_concurrency", 6),
                    custom_tmp=config.get("temp_dir", "").strip(),
                    retries=config.get("download_retries", 3),
                    headers=client.auth_headers,
                ),
            )

        async def _push_file(umo, title, chapter):
            return await push_chapter_file(
                context, config,
                umo, title, chapter,
                lambda cid, mp=0: fetch_pages_local(
                    client, cid, max_pages=mp,
                    concurrency=config.get("download_concurrency", 6),
                    custom_tmp=config.get("temp_dir", "").strip(),
                    retries=config.get("download_retries", 3),
                    headers=client.auth_headers,
                ),
            )

        async def _render_update_card(umo, items, heading):
            try:
                tmpldata = build_update_card(items, heading)
                tmpldata["items"] = await embed_covers(
                    client, tmpldata["items"],
                    custom_tmp=config.get("temp_dir", "").strip(),
                    retries=config.get("download_retries", 3),
                    concurrency=config.get("download_concurrency", 6),
                )
                return await self._render_card_result(tmpldata)
            except Exception as e:
                logger.warning(f"[{PLUGIN_NAME}] 更新通知卡片渲染失败: {e}")
                return None

        async def _check(force=False):
            render_fn = _render_update_card if self._result_cards_enabled() else None
            return await _check_updates(
                client, self.sub_mgr, context, config,
                self.get_kv_data, self.put_kv_data,
                self._update_lock,
                _push_images, _push_file,
                force=force,
                render_update_card_fn=render_fn,
            )
        self._check_updates_fn = _check

    # ── Search cache ───────────────────────────────────────────────

    def _get_cached_manga(self, umo: str, key: str) -> Manga | None:
        cache = ttl_cache_lookup(self._search_cache, umo, _CACHE_TTL)
        if cache is None:
            return None
        return cache.get(key)

    def _set_search_cache(self, umo: str, cache: dict[str, Manga]):
        ttl_cache_store(
            self._search_cache, umo, cache, _SEARCH_CACHE_MAX_ENTRIES
        )

    def _result_cards_enabled(self) -> bool:
        return self._config_bool(self.config.get("result_cards_enabled", True), True)

    async def _render_card_result(self, tmpldata: dict) -> str | None:
        """Render one card to a local file; return path or None on failure."""
        try:
            timeout = float(self.config.get("card_render_timeout_sec", 30))
        except (TypeError, ValueError):
            timeout = 30.0
        timeout = max(5.0, min(timeout, 120.0))
        path = await render_card_cached(
            self._card_cache, self.html_render, tmpldata, timeout=timeout
        )
        if path:
            schedule_cleanup_file(path, delay=CARD_CACHE_TTL + 60)
        return path

    async def _prepare_chapter_delivery(self, event: AstrMessageEvent, target):
        """Build one chapter result for command yield or direct AI-tool sending."""
        max_pages = self.config.get("max_pages", 30)
        send_mode = self.config.get("send_mode", "image")
        fetch_mode = self.config.get("image_fetch_mode", "download")
        concurrency = self.config.get("download_concurrency", 6)
        custom_tmp = self.config.get("temp_dir", "").strip()
        retries = self.config.get("download_retries", 3)

        local_paths: list[str] = []
        tmp_dir: Path | None = None
        if fetch_mode == "download":
            total_pages, page_urls, local_paths, tmp_dir = await fetch_pages_local(
                self.client, target.id, max_pages, concurrency, custom_tmp, retries,
                headers=self.client.auth_headers,
            )
            if page_urls and not any(local_paths):
                logger.error(
                    f"[{PLUGIN_NAME}] 所有 {len(page_urls)} 张图片下载均失败，"
                    "请检查 Suwayomi 是否开启了认证，以及插件的认证配置是否正确"
                )
                return None, total_pages, 0, tmp_dir
        else:
            pages = await self.client.fetch_chapter_pages(target.id)
            if not pages:
                return None, 0, 0, None
            total_pages = len(pages)
            page_urls = [self.client.build_image_url(page) for page in pages[:max_pages]]
            if self.client.auth_mode != "none":
                logger.warning(
                    f"[{PLUGIN_NAME}] 图片获取方式为 URL 模式，但 Suwayomi 开启了 "
                    f"{self.client.auth_mode} 认证，图片可能无法加载，请在配置中改用下载模式"
                )

        if not page_urls:
            return None, total_pages, 0, tmp_dir

        chain = build_image_chain(
            page_urls, local_paths, fetch_mode,
            send_mode=send_mode,
            forward_platform=event.get_platform_name() == "aiocqhttp",
            page_label=fmt_chapter_display(target),
            header=None,
            total_pages=total_pages,
            max_pages=max_pages,
            tail_text=f"... 还有 {total_pages - max_pages} 页，请到 WebUI 查看",
        )
        result = event.chain_result(chain)

        return result, total_pages, len(page_urls), tmp_dir

    async def _prepare_chapter_file_delivery(
        self,
        event: AstrMessageEvent,
        manga: Manga,
        target,
        fmt: str,
    ):
        """Download all chapter pages and build a PDF/ZIP/CBZ file result."""
        concurrency = self.config.get("download_concurrency", 6)
        custom_tmp = self.config.get("temp_dir", "").strip()
        retries = self.config.get("download_retries", 3)
        total_pages, page_urls, local_paths, tmp_dir = await fetch_pages_local(
            self.client,
            target.id,
            concurrency=concurrency,
            custom_tmp=custom_tmp,
            retries=retries,
            headers=self.client.auth_headers,
        )
        if not page_urls:
            return None, total_pages, 0, tmp_dir, None

        valid_paths = [path for path in local_paths if path]
        if not valid_paths:
            return None, total_pages, 0, tmp_dir, None
        if len(valid_paths) < len(page_urls):
            logger.warning(
                f"[{PLUGIN_NAME}] {len(page_urls) - len(valid_paths)} 页下载失败，"
                f"AI 将用已有页面打包 {fmt.upper()}"
            )

        label = fmt_chapter_display(target)
        file_ext = normalize_pack_format(fmt)
        output_path = build_chapter_output_path(
            Path(valid_paths[0]).parent, manga.title, str(label), file_ext
        )

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, pack_images, valid_paths, output_path, fmt)

        filename = output_path.name
        result = event.chain_result([Comp.File(file=str(output_path), name=filename)])
        return result, total_pages, len(valid_paths), tmp_dir, filename

    # ── Commands ───────────────────────────────────────────────────

    @filter.command_group("漫画")
    def manga_group(self):
        pass

    @manga_group.command("帮助", alias={"help"})
    async def help_cmd(self, event: AstrMessageEvent):
        '''显示漫画助手使用帮助'''
        text = """📖 Suwayomi 漫画助手

🔍 搜索与订阅
  /漫画 搜索 <关键词> [源名]  — 搜索漫画（多词用 + 连接）
  /漫画 订阅 <编号>            — 订阅搜索结果
  /漫画 批量订阅 <名称1>, <名称2>, ... [源名] — 批量订阅多部漫画
  /漫画 取消订阅 <ID或名称>    — 取消订阅
  /漫画 我的订阅               — 查看订阅列表

📚 阅读与下载
  /漫画 章节 <漫画名或ID>               — 查看章节列表
  /漫画 阅读 <漫画名或ID> <章节号>      — 阅读章节
  /漫画 下载 <漫画名或ID> <章节号> [格式]  — 下载并打包发送（格式: zip/pdf/cbz）

  添加 --刷新 强制从源更新章节数据：
  /漫画 章节 <漫画名> --刷新

  重复编号章节可用 ID: 指定：
  /漫画 阅读 <漫画名> ID:123

🔄 更新
  /漫画 更新  — 手动检查更新并推送（全局，所有订阅者都会收到通知）

📡 自动推送
  /漫画 推送 开    — 开启自动推送（有更新时自动发送漫画内容）
  /漫画 推送 关    — 关闭自动推送
  /漫画 推送 状态  — 查看推送状态

📋 其他
  /漫画 源    — 查看已安装的漫画源
  /漫画 帮助  — 显示本帮助"""
        yield event.plain_result(text)

    @manga_group.command("源")
    async def list_sources(self, event: AstrMessageEvent):
        '''列出所有已安装的漫画源'''
        try:
            sources = await self.client.get_sources()
            if not sources:
                yield event.plain_result("未找到已安装的漫画源，请在 Suwayomi WebUI 中安装扩展。")
                return
            lines = ["📚 已安装的漫画源:"]
            for i, src in enumerate(sources, 1):
                lines.append(f"  [{i}] {src.display_name} ({src.lang})")
            yield event.plain_result("\n".join(lines))
        except SuwayomiError as e:
            yield event.plain_result(f"获取源列表失败: {e}")
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] list_sources error: {e}")
            yield event.plain_result("漫画服务暂时不可用，请稍后重试。")

    @manga_group.command("搜索")
    async def search_manga(self, event: AstrMessageEvent, keyword: str):
        '''搜索漫画。用法: /漫画 搜索 <关键词> [源名]'''
        try:
            # AstrBot splits args by spaces, so the trailing source name is lost
            # from the keyword param — parse it from the full message instead.
            keyword, source_hint = split_search_query(event.message_str, keyword)
            if not keyword:
                yield event.plain_result(
                    "用法: /漫画 搜索 <关键词> [源名]（多词标题用 + 连接）"
                )
                return

            sources = await self.client.get_sources()
            if not sources:
                yield event.plain_result("未找到已安装的漫画源。")
                return

            search_query = keyword
            target_sources: list = []
            if source_hint:
                hinted = match_source_hint(sources, source_hint)
                if hinted:
                    target_sources = [hinted]
                else:
                    # Not a source name — treat it as part of the manga keyword.
                    search_query = f"{keyword} {source_hint}".strip()
                    yield event.plain_result(
                        f"未找到名为「{source_hint}」的漫画源，已将其作为关键词继续搜索。"
                        "可用「漫画 源」查看全部源。"
                    )
            if not target_sources:
                # Same selection as the AI tool path: skip the local source and
                # prefer distinct extensions before language variants.
                target_sources = select_search_sources(
                    sources,
                    "",
                    self.config.get("default_source_id", 0),
                    max_sources=5,
                )

            all_results: list[tuple[str, SearchResult]] = []
            for src in target_sources:
                try:
                    result = await self.client.search_manga(src.id, search_query)
                    all_results.append((src.display_name, result))
                except Exception as e:
                    logger.warning(f"[{PLUGIN_NAME}] 搜索源 {src.name} 失败: {e}")

            if not all_results:
                yield event.plain_result("未找到相关漫画，请确认关键词。")
                return

            lines = []
            idx = 1
            cache: dict[str, Manga] = {}
            card_rows: list[dict] = []
            for source_name, result in all_results:
                if result.mangas:
                    lines.append(f"\n🔍 搜索结果（源: {source_name}）:")
                    for m in result.mangas:
                        status = STATUS_EMOJI.get(m.status, "未知")
                        lines.append(f"  [{idx}] {m.title} - {status}")
                        cache[str(idx)] = m
                        card_rows.append({
                            "index": idx,
                            "title": m.title,
                            "status": m.status,
                            "source": source_name,
                            "thumbnail_url": m.thumbnail_url,
                        })
                        idx += 1

            if idx == 1:
                yield event.plain_result("未找到相关漫画，请确认关键词。")
                return

            lines.append("\n回复「漫画 订阅 <编号>」订阅，如「漫画 订阅 1」")
            text = "\n".join(lines)
            self._set_search_cache(event.unified_msg_origin, cache)

            if self._result_cards_enabled():
                try:
                    subtitle = (
                        f"{' · '.join(dict.fromkeys(source_name for source_name, _ in all_results))}"
                        f" · {len(card_rows)} 条"
                    )
                    tmpldata = build_search_card(
                        card_rows,
                        subtitle,
                        "回复「漫画 订阅 编号」订阅，如「漫画 订阅 1」",
                    )
                    tmpldata["rows"] = await embed_covers(
                        self.client, tmpldata["rows"],
                        custom_tmp=self.config.get("temp_dir", "").strip(),
                        retries=self.config.get("download_retries", 3),
                        concurrency=self.config.get("download_concurrency", 6),
                    )
                    path = await self._render_card_result(tmpldata)
                    if path:
                        yield event.chain_result([Comp.Image.fromFileSystem(path)])
                        return
                except Exception as e:
                    logger.warning(f"[{PLUGIN_NAME}] 搜索卡片渲染失败，回退文本: {e}")

            yield event.plain_result(text)

        except SuwayomiError as e:
            yield event.plain_result(f"搜索失败: {e}")
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] search error: {e}")
            yield event.plain_result("搜索失败，漫画服务暂时不可用。")

    @manga_group.command("订阅")
    async def subscribe_manga(self, event: AstrMessageEvent, index: str):
        '''订阅漫画。用法: /漫画 订阅 <搜索结果编号>'''
        try:
            manga = self._get_cached_manga(event.unified_msg_origin, index)
            if manga is None:
                yield event.plain_result("未找到该编号的漫画，请先使用「漫画 搜索」。")
                return

            await self.sub_mgr.subscribe(manga.id, manga.title, manga.source_id, event.unified_msg_origin)
            logger.info(f"[{PLUGIN_NAME}] 用户订阅「{manga.title}」(ID:{manga.id})")
            try:
                chapters = await get_or_fetch_chapters(
                    self.client, self.get_kv_data, self.put_kv_data, self.config, manga.id
                )
                if chapters:
                    max_id = max(ch.id for ch in chapters)
                    await self.sub_mgr.update_latest_chapter(manga.id, max_id)
            except Exception as e:
                logger.warning(f"[{PLUGIN_NAME}] 拉取「{manga.title}」章节失败: {e}")

            if self._result_cards_enabled():
                try:
                    tmpldata = build_subscribe_confirm_card(
                        {"id": manga.id, "title": manga.title,
                         "status": manga.status, "thumbnail_url": manga.thumbnail_url},
                        source_name="",
                        footer="有新章节时会推送通知",
                    )
                    card = (await embed_covers(
                        self.client, [tmpldata],
                        custom_tmp=self.config.get("temp_dir", "").strip(),
                        retries=self.config.get("download_retries", 3),
                        concurrency=self.config.get("download_concurrency", 6),
                    ))[0]
                    path = await self._render_card_result(card)
                    if path:
                        yield event.chain_result([Comp.Image.fromFileSystem(path)])
                        return
                except Exception as e:
                    logger.warning(f"[{PLUGIN_NAME}] 订阅确认卡片渲染失败，回退文本: {e}")
            yield event.plain_result(f"✅ 已订阅「{manga.title}」，有新章节时会推送。")
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] subscribe error: {e}")
            yield event.plain_result("订阅失败，请稍后重试。")

    @manga_group.command("批量订阅")
    async def batch_subscribe(self, event: AstrMessageEvent):
        '''批量订阅漫画。用法: /漫画 批量订阅 <名称1>, <名称2>, ... [源名]'''
        try:
            raw = event.message_str.strip()
            prefix = "漫画 批量订阅"
            if not raw.startswith(prefix):
                yield event.plain_result("用法: 漫画 批量订阅 <名称1>, <名称2>, ... [源名]")
                return
            args_str = raw[len(prefix):].strip()
            if not args_str:
                yield event.plain_result("用法: 漫画 批量订阅 <名称1>, <名称2>, ... [源名]\n名称用逗号分隔，如: 漫画 批量订阅 咒术回战, 鬼灭之刃")
                return

            sources = await self.client.get_sources()
            src_map = {str(s.id): s.display_name for s in sources}
            source_filter = None
            search_str = args_str

            last_space = args_str.rfind(" ")
            if last_space > 0:
                potential_source = args_str[last_space + 1:].lower()
                for src in sources:
                    if potential_source in (src.name.lower(), src.display_name.lower(), src.lang.lower()):
                        source_filter = src
                        search_str = args_str[:last_space]
                        break

            raw_names = [n.strip() for n in re.split(r'[,，;；]', search_str) if n.strip()]
            if not raw_names:
                yield event.plain_result("请提供漫画名称，用逗号分隔。")
                return
            if len(raw_names) > 20:
                yield event.plain_result("一次最多批量订阅 20 部漫画。")
                return

            await event.send(event.plain_result(f"📚 开始批量订阅 {len(raw_names)} 部漫画..."))

            umo = event.unified_msg_origin
            existing_subs = await self.sub_mgr.get_subscriptions(umo)
            existing_ids = {s["manga_id"] for s in existing_subs}

            results: list[tuple[str, str, str]] = []
            card_rows: list[dict] = []
            for i, name in enumerate(raw_names, 1):
                await event.send(event.plain_result(f"正在处理 [{i}/{len(raw_names)}] {name}..."))
                manga, error = await search_best_match(self.client, self.config, name, source_filter)
                if error or manga is None:
                    results.append((name, "fail", error or "未找到匹配结果"))
                    card_rows.append({"status": "fail", "title": name,
                                      "detail": error or "未找到匹配结果", "thumbnail_url": None})
                    continue

                if manga.id in existing_ids:
                    status_text = STATUS_EMOJI.get(manga.status, "未知")
                    source_name = src_map.get(str(manga.source_id), "")
                    results.append((name, "exists", f"{manga.title} - {status_text} - {source_name}"))
                    card_rows.append({"status": "exists", "title": manga.title,
                                      "detail": f"{status_text} - {source_name}（已订阅）",
                                      "thumbnail_url": manga.thumbnail_url})
                    continue

                await self.sub_mgr.subscribe(manga.id, manga.title, manga.source_id, umo)
                existing_ids.add(manga.id)
                try:
                    chapters = await get_or_fetch_chapters(
                        self.client, self.get_kv_data, self.put_kv_data, self.config, manga.id
                    )
                    if chapters:
                        max_id = max(ch.id for ch in chapters)
                        await self.sub_mgr.update_latest_chapter(manga.id, max_id)
                except Exception as e:
                    logger.warning(f"[{PLUGIN_NAME}] 批量订阅拉取「{manga.title}」章节失败: {e}")

                status_text = STATUS_EMOJI.get(manga.status, "未知")
                source_name = src_map.get(str(manga.source_id), "")
                results.append((name, "ok", f"{manga.title} - {status_text} - {source_name}"))
                card_rows.append({"status": "ok", "title": manga.title,
                                  "detail": f"{status_text} - {source_name}",
                                  "thumbnail_url": manga.thumbnail_url})

            ok_count = sum(1 for _, s, _ in results if s == "ok")
            exist_count = sum(1 for _, s, _ in results if s == "exists")
            fail_count = sum(1 for _, s, _ in results if s == "fail")

            lines = [f"📚 批量订阅完成 ({ok_count} 新增, {exist_count} 已存在, {fail_count} 失败):"]
            for name, status, info in results:
                if status == "ok":
                    lines.append(f"  ✅ {info}")
                elif status == "exists":
                    lines.append(f"  ⏭ {info} (已订阅)")
                else:
                    lines.append(f"  ❌ {name} - {info}")
            summary_text = "\n".join(lines)

            if self._result_cards_enabled():
                try:
                    tmpldata = build_batch_card(
                        card_rows,
                        f"{ok_count} 新增, {exist_count} 已存在, {fail_count} 失败",
                    )
                    tmpldata["rows"] = await embed_covers(
                        self.client, tmpldata["rows"],
                        custom_tmp=self.config.get("temp_dir", "").strip(),
                        retries=self.config.get("download_retries", 3),
                        concurrency=self.config.get("download_concurrency", 6),
                    )
                    path = await self._render_card_result(tmpldata)
                    if path:
                        yield event.chain_result([Comp.Image.fromFileSystem(path)])
                        return
                except Exception as e:
                    logger.warning(f"[{PLUGIN_NAME}] 批量订阅卡片渲染失败，回退文本: {e}")

            yield event.plain_result(summary_text)

        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] batch_subscribe error: {e}")
            yield event.plain_result("批量订阅失败，请稍后重试。")

    @manga_group.command("取消订阅")
    async def unsubscribe_manga(self, event: AstrMessageEvent, manga_id_or_name: str):
        '''取消订阅。用法: /漫画 取消订阅 <漫画ID或名称>'''
        try:
            umo = event.unified_msg_origin
            manga_id = None
            manga_title = manga_id_or_name
            try:
                manga_id = int(manga_id_or_name)
            except ValueError:
                norm_input = normalize_zh(manga_id_or_name)
                subs = await self.sub_mgr.get_subscriptions(umo)
                for s in subs:
                    if norm_input in normalize_zh(s["title"]):
                        manga_id = s["manga_id"]
                        manga_title = s["title"]
                        break

            if manga_id is None:
                yield event.plain_result("未找到匹配的订阅，请使用漫画 ID 或名称。")
                return
            await self.sub_mgr.unsubscribe(manga_id, umo)
            logger.info(f"[{PLUGIN_NAME}] 用户取消订阅「{manga_title}」(ID:{manga_id})")
            yield event.plain_result(f"✅ 已取消订阅（漫画 ID: {manga_id}）。")
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] unsubscribe error: {e}")
            yield event.plain_result("取消订阅失败，请稍后重试。")

    @manga_group.command("我的订阅")
    async def my_subscriptions(self, event: AstrMessageEvent):
        '''查看当前会话的订阅列表'''
        try:
            subs = await self.sub_mgr.get_subscriptions(event.unified_msg_origin)
            if not subs:
                yield event.plain_result("📭 你还没有订阅任何漫画。使用「漫画 搜索」来查找并订阅。")
                return
            sources = await self.client.get_sources()
            src_map = {str(s.id): s.display_name for s in sources}

            if self._result_cards_enabled():
                try:
                    metadatas = await asyncio.gather(
                        *(self.client.get_manga(s["manga_id"]) for s in subs),
                        return_exceptions=True,
                    )
                    card_rows = []
                    for s, meta in zip(subs, metadatas):
                        thumbnail = meta.thumbnail_url if not isinstance(meta, Exception) else None
                        status = meta.status if not isinstance(meta, Exception) else "UNKNOWN"
                        src_name = src_map.get(str(s["source_id"]), "")
                        push = "🔔 推送开" if s.get("push_enabled") else "🔕 推送关"
                        tag = f" - {src_name}" if src_name else ""
                        card_rows.append({
                            "title": s["title"],
                            "detail": f"{STATUS_EMOJI.get(status, '未知')}{tag} · {push} · ID: {s['manga_id']}",
                            "thumbnail_url": thumbnail,
                        })
                    tmpldata = build_subscriptions_card(card_rows)
                    tmpldata["rows"] = await embed_covers(
                        self.client, tmpldata["rows"],
                        custom_tmp=self.config.get("temp_dir", "").strip(),
                        retries=self.config.get("download_retries", 3),
                        concurrency=self.config.get("download_concurrency", 6),
                    )
                    path = await self._render_card_result(tmpldata)
                    if path:
                        yield event.chain_result([Comp.Image.fromFileSystem(path)])
                        return
                except Exception as e:
                    logger.warning(f"[{PLUGIN_NAME}] 订阅列表卡片渲染失败，回退文本: {e}")

            lines = ["📋 你的订阅列表:"]
            for s in subs:
                source_name = src_map.get(str(s["source_id"]), "")
                tag = f" - {source_name}" if source_name else ""
                lines.append(f"  • {s['title']}{tag} - ID: {s['manga_id']}")
            yield event.plain_result("\n".join(lines))
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] my_subscriptions error: {e}")
            yield event.plain_result("获取订阅列表失败。")

    # ── Push sub-commands ──────────────────────────────────────────

    @manga_group.group("推送")
    def push_group(self):
        pass

    @push_group.command("开")
    async def push_enable(self, event: AstrMessageEvent):
        '''开启当前会话的漫画自动推送'''
        try:
            umo = event.unified_msg_origin
            subs = await self.sub_mgr.get_subscriptions(umo)
            if not subs:
                yield event.plain_result("📭 你还没有订阅任何漫画，请先使用「漫画 搜索」订阅。")
                return
            await self.sub_mgr.set_auto_push_all(umo, True)
            await self.sub_mgr.set_push_default(umo, True)
            yield event.plain_result(f"✅ 已开启自动推送，共 {len(subs)} 部漫画。有更新时将自动推送内容。")
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] push_enable error: {e}")
            yield event.plain_result("开启自动推送失败。")

    @push_group.command("关")
    async def push_disable(self, event: AstrMessageEvent):
        '''关闭当前会话的漫画自动推送'''
        try:
            umo = event.unified_msg_origin
            subs = await self.sub_mgr.get_subscriptions(umo)
            if not subs:
                yield event.plain_result("📭 你还没有订阅任何漫画。")
                return
            await self.sub_mgr.set_auto_push_all(umo, False)
            await self.sub_mgr.clear_push_default(umo)
            yield event.plain_result("✅ 已关闭自动推送。有更新时将只发送文本通知。")
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] push_disable error: {e}")
            yield event.plain_result("关闭自动推送失败。")

    @push_group.command("状态")
    async def push_status(self, event: AstrMessageEvent):
        '''查看当前会话的自动推送状态'''
        try:
            umo = event.unified_msg_origin
            subs = await self.sub_mgr.get_subscriptions(umo)
            if not subs:
                yield event.plain_result("📭 你还没有订阅任何漫画。")
                return
            lines = ["📡 自动推送状态:"]
            all_subs = await self.sub_mgr.get_all_subscriptions()
            for s in subs:
                enabled = self.sub_mgr.is_auto_push_enabled(all_subs, s["manga_id"], umo)
                status = "✅ 开启" if enabled else "❌ 关闭"
                lines.append(f"  • {s['title']} — {status}")
            yield event.plain_result("\n".join(lines))
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] push_status error: {e}")
            yield event.plain_result("获取推送状态失败。")

    # ── Chapter list ───────────────────────────────────────────────

    @manga_group.command("章节")
    async def list_chapters(self, event: AstrMessageEvent, manga_name_or_id: str):
        '''查看漫画章节列表。用法: /漫画 章节 <漫画名或ID> [--刷新]'''
        try:
            tokens = event.message_str.strip().split()
            try:
                cmd_idx = tokens.index("章节")
                args = tokens[cmd_idx + 1:]
            except ValueError:
                args = []

            force = "--刷新" in args
            manga_name_or_id = " ".join(a for a in args if a != "--刷新").strip()
            if not manga_name_or_id:
                yield event.plain_result("用法: /漫画 章节 <漫画名或ID> [--刷新]")
                return

            manga, err = await resolve_manga(self.client, self.sub_mgr, event.unified_msg_origin, manga_name_or_id, "章节")
            if err or manga is None:
                yield event.plain_result(err or "未找到该漫画。")
                return

            show_cover = self.config.get("chapter_list_show_cover", True)
            cover_path: str | None = None
            cover_tmp: Path | None = None

            if show_cover and manga.thumbnail_url:
                chapters_result, cover_result = await asyncio.gather(
                    get_or_fetch_chapters(
                        self.client, self.get_kv_data, self.put_kv_data, self.config, manga.id, force=force
                    ),
                    download_cover(
                        self.client,
                        manga.thumbnail_url,
                        custom_tmp=self.config.get("temp_dir", "").strip(),
                        retries=self.config.get("download_retries", 3),
                        headers=self.client.auth_headers,
                    ),
                    return_exceptions=True,
                )
                if isinstance(chapters_result, Exception):
                    # If the cover was already downloaded, do not leak its temp dir.
                    if isinstance(cover_result, tuple) and cover_result[0]:
                        schedule_cleanup(cover_result[1], delay=60)
                    raise chapters_result
                chapters = chapters_result
                if not isinstance(cover_result, Exception):
                    cover_path, cover_tmp = cover_result
            else:
                chapters = await get_or_fetch_chapters(
                    self.client, self.get_kv_data, self.put_kv_data, self.config, manga.id, force=force
                )

            if not chapters:
                if cover_path:
                    msg = f"「{manga.title}」暂无章节。"
                    schedule_cleanup(cover_tmp, delay=60)
                    yield event.chain_result([Comp.Image.fromFileSystem(cover_path), Comp.Plain(msg)])
                else:
                    yield event.plain_result(f"「{manga.title}」暂无章节。")
                return

            chapters.sort(key=lambda ch: ch.source_order)
            num_count: dict[float, int] = {}
            for ch in chapters:
                num_count[ch.chapter_number] = num_count.get(ch.chapter_number, 0) + 1

            try:
                sources = await self.client.get_sources()
                src_name = next((s.display_name for s in sources if str(s.id) == str(manga.source_id)), None)
            except Exception:
                src_name = None
            src_tag = f" - {src_name}" if src_name else ""

            if self._result_cards_enabled() and show_cover:
                try:
                    lines_card: list[str] = []
                    dl_count = 0
                    for ch in chapters:
                        dl_mark = " 📥" if ch.is_downloaded else ""
                        if ch.is_downloaded:
                            dl_count += 1
                        lines_card.append(f"{fmt_chapter_label(ch, num_count)}{dl_mark}")

                    latest = fmt_chapter_num(chapters[-1].chapter_number) if chapters else "?"
                    meta = f"{src_name or '未知源'} · 共 {len(chapters)} 话"
                    if dl_count:
                        meta += f" · 本地 {dl_count}"
                    card_base = {
                        "title": manga.title,
                        "thumbnail_url": manga.thumbnail_url,
                        "meta": meta,
                        "tags": [{"text": f"最近更新 #{latest}"}],
                        "hint": f"「漫画 章节 {manga.title} --刷新」强制刷新",
                    }
                    (card_base,) = await embed_covers(
                        self.client, [card_base],
                        custom_tmp=self.config.get("temp_dir", "").strip(),
                        retries=self.config.get("download_retries", 3),
                        concurrency=self.config.get("download_concurrency", 6),
                    )
                    cards_tmpldata, tail_lines = build_chapter_cards(card_base, lines_card)
                    rendered: list[str] = []
                    for card_data in cards_tmpldata:
                        path = await self._render_card_result(card_data)
                        if path is None:
                            rendered = []
                            break
                        rendered.append(path)
                    if rendered:
                        yield event.chain_result([Comp.Image.fromFileSystem(rendered[0])])
                        for path in rendered[1:]:
                            await event.send(event.chain_result([Comp.Image.fromFileSystem(path)]))
                        if tail_lines:
                            tail_text = "\n".join(tail_lines)
                            for i in range(0, len(tail_text), 1500):
                                chunk = tail_text[i:i + 1500]
                                if i == 0:
                                    yield event.plain_result(chunk)
                                else:
                                    await event.send(event.plain_result(chunk))
                        return
                except Exception as e:
                    logger.warning(f"[{PLUGIN_NAME}] 章节卡片渲染失败，回退旧路径: {e}")

            header = f"📖「{manga.title}」{src_tag} 章节列表（共 {len(chapters)} 话）:"
            chunks: list[list[str]] = [[]]
            for ch in chapters:
                dl_mark = " 📥" if ch.is_downloaded else ""
                line = f"  {fmt_chapter_label(ch, num_count)}{dl_mark}"
                current_len = sum(len(item) for item in chunks[-1]) + len(header)
                if current_len + len(line) > 1500 and chunks[-1]:
                    chunks.append([])
                chunks[-1].append(line)

            for i, chunk in enumerate(chunks):
                prefix = header if i == 0 else f"📖「{manga.title}」{src_tag} 章节续 ({i + 1}/{len(chunks)}):"
                msg = prefix + "\n" + "\n".join(chunk)
                if i == 0 and cover_path:
                    schedule_cleanup(cover_tmp, delay=60)
                    yield event.chain_result([Comp.Image.fromFileSystem(cover_path), Comp.Plain(msg)])
                elif i == 0:
                    yield event.plain_result(msg)
                else:
                    await event.send(event.plain_result(msg))

        except SuwayomiError as e:
            yield event.plain_result(f"获取章节失败: {e}")
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] list_chapters error: {e}")
            yield event.plain_result("获取章节列表失败。")

    # ── Read chapter ───────────────────────────────────────────────

    @manga_group.command("阅读")
    async def read_chapter(self, event: AstrMessageEvent, manga_name_or_id: str, chapter_num: str = ""):
        '''阅读漫画章节。用法: /漫画 阅读 <漫画名或ID> <章节号或ID:数字>'''
        if not chapter_num:
            yield event.plain_result("用法: /漫画 阅读 <漫画名或ID> <章节号>\n示例: /漫画 阅读 一拳超人 1\n指定章节 ID: /漫画 阅读 一拳超人 ID:123")
            return

        try:
            manga, err = await resolve_manga(self.client, self.sub_mgr, event.unified_msg_origin, manga_name_or_id, "阅读")
            if err or manga is None:
                yield event.plain_result(err or "未找到该漫画。")
                return

            chapters = await get_or_fetch_chapters(
                self.client, self.get_kv_data, self.put_kv_data, self.config, manga.id
            )

            target, err_msg = resolve_chapter(chapters, chapter_num, manga_name_or_id, "阅读")
            if err_msg:
                yield event.plain_result(err_msg)
                return
            if target is None:
                yield event.plain_result(f"未找到「{manga.title}」指定的章节。")
                return

            try:
                await event.send(event.plain_result(f"📖 正在加载「{manga.title}」{fmt_chapter_display(target)}，请稍后..."))
            except Exception:
                pass

            tmp_dir: Path | None = None
            try:
                result, total_pages, _, tmp_dir = await self._prepare_chapter_delivery(event, target)
                if result is None:
                    fetch_mode = self.config.get("image_fetch_mode", "download")
                    yield event.plain_result(
                        fmt_delivery_failure_message(
                            total_pages, fetch_mode, self.client.auth_mode
                        )
                    )
                    return
                yield result
            finally:
                schedule_cleanup(tmp_dir, delay=60)

        except SuwayomiError as e:
            yield event.plain_result(f"阅读失败: {e}")
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] read_chapter error: {e}")
            yield event.plain_result("阅读章节失败。")

    # ── Download chapter ───────────────────────────────────────────

    @manga_group.command("下载")
    async def download_chapter(self, event: AstrMessageEvent, manga_name_or_id: str, chapter_num: str = ""):
        '''下载漫画章节并打包发送。用法: /漫画 下载 <漫画名或ID> <章节号或ID:数字> [zip/pdf/cbz]'''
        default_fmt = self.config.get("download_format", "pdf")
        manga_name_or_id, chapter_num, fmt = parse_download_args(event.message_str, default_fmt)

        if not manga_name_or_id or not chapter_num:
            yield event.plain_result(
                "用法: /漫画 下载 <漫画名或ID> <章节号> [格式]\n"
                "示例: /漫画 下载 一拳超人 1\n"
                "指定格式: /漫画 下载 一拳超人 1 pdf\n"
                "指定章节 ID: /漫画 下载 一拳超人 ID:123"
            )
            return

        tmp_dir: Path | None = None
        try:
            manga, err = await resolve_manga(self.client, self.sub_mgr, event.unified_msg_origin, manga_name_or_id, "下载")
            if err or manga is None:
                yield event.plain_result(err or "未找到该漫画。")
                return

            chapters = await get_or_fetch_chapters(
                self.client, self.get_kv_data, self.put_kv_data, self.config, manga.id
            )

            target, err_msg = resolve_chapter(chapters, chapter_num, manga_name_or_id, "下载")
            if err_msg:
                yield event.plain_result(err_msg)
                return
            if target is None:
                yield event.plain_result(f"未找到「{manga.title}」指定的章节。")
                return

            num_label = fmt_chapter_display(target)
            await event.send(event.plain_result(f"⏳ 正在下载「{manga.title}」{num_label}，请稍候..."))

            concurrency = self.config.get("download_concurrency", 6)
            custom_tmp = self.config.get("temp_dir", "").strip()
            retries = self.config.get("download_retries", 3)
            _, page_urls, local_paths, tmp_dir = await fetch_pages_local(
                self.client, target.id, concurrency=concurrency, custom_tmp=custom_tmp, retries=retries,
                headers=self.client.auth_headers,
            )

            if not page_urls:
                yield event.plain_result(f"{num_label}暂无可用页面。")
                return

            valid_paths = [p for p in local_paths if p]
            if not valid_paths:
                yield event.plain_result("所有页面下载失败，无法打包。")
                return

            if len(valid_paths) < len(page_urls):
                logger.warning(f"[{PLUGIN_NAME}] {len(page_urls) - len(valid_paths)} 页下载失败，将用已有页面打包")

            file_ext = normalize_pack_format(fmt)
            output_path = build_chapter_output_path(
                Path(valid_paths[0]).parent, manga.title, str(num_label), file_ext
            )

            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, pack_images, valid_paths, output_path, fmt)
            except Exception as e:
                logger.error(f"[{PLUGIN_NAME}] 打包失败: {e}")
                yield event.plain_result(f"打包失败: {e}")
                return

            filename = output_path.name
            try:
                chain = [Comp.File(file=str(output_path), name=filename)]
                yield event.chain_result(chain)
            except Exception as e:
                logger.warning(f"[{PLUGIN_NAME}] 发送文件失败，回退为图片预览: {e}")
                preview_count = min(3, len(valid_paths))
                chain = [Comp.Plain(f"📄 {filename}（{len(valid_paths)} 页，文件发送不支持，以下为预览）")]
                for i in range(preview_count):
                    chain.append(Comp.Image.fromFileSystem(valid_paths[i]))
                yield event.chain_result(chain)

        except SuwayomiError as e:
            yield event.plain_result(f"下载失败: {e}")
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] download error: {e}")
            yield event.plain_result("下载失败。")
        finally:
            schedule_cleanup(tmp_dir, delay=120)

    # ── Manual update ──────────────────────────────────────────────

    @manga_group.command("更新")
    async def manual_update(self, event: AstrMessageEvent):
        '''手动检查漫画更新'''
        if not self._check_updates_fn:
            yield event.plain_result("⏳ 更新引擎尚未就绪，请稍后重试。")
            return
        try:
            summary = await self._check_updates_fn(force=True)
            yield event.plain_result(summary)
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] manual_update error: {e}")
            yield event.plain_result("更新检查失败。")

    # ── WebUI API delegates ────────────────────────────────────────

    @staticmethod
    def _json_response(result):
        from quart import jsonify
        if isinstance(result, tuple):
            return jsonify(result[0]), result[1]
        return jsonify(result)

    async def _api_status(self):
        result = await api_status(self.client, self.sub_mgr, self.get_kv_data)
        return self._json_response(result)

    async def _api_subscriptions(self):
        result = await api_subscriptions(self.client, self.sub_mgr)
        return self._json_response(result)

    async def _api_subscription_delete(self):
        from quart import request
        data = await request.get_json()
        if data is None:
            return self._json_response(({"success": False, "message": "Invalid JSON"}, 400))
        result = await api_subscription_delete(self.sub_mgr, data)
        return self._json_response(result)

    async def _api_subscription_push(self):
        from quart import request
        data = await request.get_json()
        if data is None:
            return self._json_response(({"success": False, "message": "Invalid JSON"}, 400))
        result = await api_subscription_push(self.sub_mgr, data)
        return self._json_response(result)

    async def _api_config(self):
        from quart import request
        if request.method == "GET":
            return self._json_response(api_config_get(self.config))

        data = await request.get_json()
        if data is None:
            return self._json_response(({"success": False, "message": "Invalid JSON"}, 400))

        async def rebuild_client(cfg):
            try:
                await self.client.close()
            except Exception:
                pass
            self.client = SuwayomiClient(
                server_url=cfg.get("server_url", "http://localhost:4567"),
                auth_mode=cfg.get("auth_mode", "none"),
                username=cfg.get("username", ""),
                password=cfg.get("password", ""),
            )
            self._build_check_updates_fn()
            self._search_cache.clear()
            self._ai_state.clear()
            self._ai_send_locks.clear()
            self._sync_ai_tools()
            if self._bg_task and not self._bg_task.done():
                self._bg_task.cancel()
                try:
                    await self._bg_task
                except asyncio.CancelledError:
                    pass
                self._bg_task = None
            self._try_start_bg_loop()

        result = await api_config_post(self.config, data, rebuild_client)
        return self._json_response(result)

    async def _api_sources(self):
        result = await api_sources_handler(self.client)
        return self._json_response(result)

    async def _api_update(self):
        if not self._check_updates_fn:
            return self._json_response(({"success": False, "message": "更新引擎尚未就绪。"}, 503))
        result = await api_update_handler(self._check_updates_fn, self.put_kv_data)
        return self._json_response(result)
