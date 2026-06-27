from __future__ import annotations

import asyncio
import math
import shutil
import tempfile
import time
from pathlib import Path

import aiohttp
import opencc

import astrbot.api.message_components as Comp
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.star import Context, Star

from .suwayomi.client import SuwayomiClient, SuwayomiError
from .suwayomi.models import Chapter, Manga, SearchResult
from .utils.pack import pack_cbz, pack_pdf, pack_zip, parse_download_args
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

PLUGIN_NAME = "astrbot_plugin_suwayomi_server"

# Search cache TTL in seconds
_CACHE_TTL = 600  # 10 minutes

_t2s = opencc.OpenCC("t2s")


def _normalize_zh(text: str) -> str:
    """Normalize Chinese text to simplified for comparison."""
    return _t2s.convert(text)


def _fmt_chapter_num(num: float) -> int | float | str:
    """Format chapter number: return int if it's a whole number, else float. Returns '?' for NaN/Inf."""
    try:
        if math.isnan(num) or math.isinf(num):
            return "?"
        return int(num) if num == int(num) else num
    except (ValueError, OverflowError):
        return "?"


STATUS_EMOJI = {
    "ONGOING": "连载中",
    "COMPLETED": "已完结",
    "LICENSED": "已授权",
    "PUBLISHING_FINISHED": "已完结",
    "CANCELLED": "已停刊",
    "ON_HIATUS": "休刊中",
    "UNKNOWN": "未知",
}


class SuwayomiPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.client = SuwayomiClient(
            server_url=config.get("server_url", "http://localhost:9330"),
            auth_mode=config.get("auth_mode", "none"),
            username=config.get("username", ""),
            password=config.get("password", ""),
        )
        self.sub_mgr = SubscriptionManager(self)
        self._search_cache: dict[str, tuple[float, dict[str, Manga]]] = {}
        self._update_lock = asyncio.Lock()
        self._bg_task: asyncio.Task | None = None

        logger.info(f"[{PLUGIN_NAME}] 插件已加载 | 服务器: {config.get('server_url')} | 缓存: {config.get('chapter_cache_hours', 6)}h | 检查间隔: {config.get('check_interval', 60)}min")

        # Register WebUI API endpoints
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

    @filter.on_astrbot_loaded()
    async def on_loaded(self):
        """Start background update task after AstrBot event loop is running."""
        interval = self.config.get("check_interval", 60) * 60
        self._bg_task = asyncio.create_task(self._update_loop(interval))

    async def terminate(self):
        if self._bg_task and not self._bg_task.done():
            self._bg_task.cancel()
        await self.client.close()
        logger.info(f"[{PLUGIN_NAME}] 插件已卸载")

    def _get_cached_manga(self, umo: str, key: str) -> Manga | None:
        """Get manga from search cache, respecting TTL."""
        entry = self._search_cache.get(umo)
        if entry is None:
            return None
        ts, cache = entry
        if time.time() - ts > _CACHE_TTL:
            del self._search_cache[umo]
            return None
        return cache.get(key)

    def _set_search_cache(self, umo: str, cache: dict[str, Manga]):
        """Store search results in cache with timestamp."""
        self._search_cache[umo] = (time.time(), cache)

    async def _update_loop(self, interval: float):
        try:
            while True:
                await asyncio.sleep(interval)
                try:
                    await self._check_updates(force=True)
                except Exception as e:
                    logger.error(f"[{PLUGIN_NAME}] 后台更新检查失败: {e}")
        except asyncio.CancelledError:
            pass

    async def _download_one(
        self, session: aiohttp.ClientSession, url: str, dest: Path
    ) -> bool:
        """Download a single image with exponential backoff retry."""
        retries = self.config.get("download_retries", 3)
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
                        logger.warning(f"[{PLUGIN_NAME}] 图片下载失败 HTTP {resp.status}: {url}")
                        return False
                    # 5xx: retryable
                    logger.warning(f"[{PLUGIN_NAME}] 图片下载 HTTP {resp.status}，重试 {attempt + 1}/{retries}: {url}")
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                logger.warning(f"[{PLUGIN_NAME}] 图片下载超时/网络错误，重试 {attempt + 1}/{retries}: {e}")
            except Exception as e:
                logger.warning(f"[{PLUGIN_NAME}] 图片下载异常: {e}")
                return False
            if attempt < retries - 1:
                await asyncio.sleep(0.5 * (2 ** attempt))
        return False

    async def _download_images(self, urls: list[str]) -> list[str]:
        """Download images in parallel with retry. Returns list of local file paths (empty string for failures)."""
        concurrency = self.config.get("download_concurrency", 6)
        custom_tmp = self.config.get("temp_dir", "").strip()
        tmp_dir = Path(tempfile.mkdtemp(prefix="suwayomi_", dir=custom_tmp or None))
        try:
            connector = aiohttp.TCPConnector(limit=concurrency)
            async with aiohttp.ClientSession(connector=connector) as session:
                tasks = []
                for i, url in enumerate(urls):
                    dest = tmp_dir / f"{i:04d}.jpg"
                    tasks.append(self._download_one(session, url, dest))
                results = await asyncio.gather(*tasks, return_exceptions=True)

            paths = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.warning(f"[{PLUGIN_NAME}] 图片 {i + 1} 下载异常: {result}")
                    paths.append("")
                elif result:
                    matches = sorted(tmp_dir.glob(f"{i:04d}.*"))
                    paths.append(str(matches[-1]) if matches else "")
                else:
                    paths.append("")
            return paths
        except Exception:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise

    # ── Command Group ──────────────────────────────────────────────

    @filter.command_group("漫画")
    def manga_group(self):
        pass

    @manga_group.command("帮助", alias={"help"})
    async def help_cmd(self, event: AstrMessageEvent):
        '''显示漫画助手使用帮助'''
        text = """📖 Suwayomi 漫画助手

🔍 搜索与订阅
  /漫画 搜索 <关键词> [源名]  — 搜索漫画
  /漫画 订阅 <编号>            — 订阅搜索结果
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

    # ── 漫画 源 ────────────────────────────────────────────────────

    @manga_group.command("源")
    async def list_sources(self, event: AstrMessageEvent):
        '''列出所有已安装的漫画 源'''
        try:
            sources = await self.client.get_sources()
            if not sources:
                yield event.plain_result("未找到已安装的漫画 源，请在 Suwayomi WebUI 中安装扩展。")
                return
            lines = ["📚 已安装的漫画 源:"]
            for i, src in enumerate(sources, 1):
                lines.append(f"  [{i}] {src.display_name} ({src.lang})")
            yield event.plain_result("\n".join(lines))
        except SuwayomiError as e:
            yield event.plain_result(f"获取源列表失败: {e}")
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] list_sources error: {e}")
            yield event.plain_result("漫画服务暂时不可用，请稍后重试。")

    # ── 漫画搜索 ──────────────────────────────────────────────────

    @manga_group.command("搜索")
    async def search_manga(self, event: AstrMessageEvent, keyword: str):
        '''搜索漫画。用法: /漫画 搜索 <关键词> [源名]'''
        try:
            keyword = keyword.strip()
            if not keyword:
                yield event.plain_result("用法: /漫画 搜索 <关键词> [源名]")
                return

            sources = await self.client.get_sources()
            if not sources:
                yield event.plain_result("未找到已安装的漫画 源。")
                return

            source_filter = None
            search_query = keyword
            words = keyword.rsplit(" ", 1)
            if len(words) == 2:
                potential_source = words[1].lower()
                for src in sources:
                    if potential_source in (src.name.lower(), src.display_name.lower(), src.lang.lower()):
                        source_filter = src
                        search_query = words[0]
                        break

            default_sid = self.config.get("default_source_id", 0)
            if source_filter:
                target_sources = [source_filter]
            elif default_sid:
                target_sources = [s for s in sources if s.id == default_sid]
                if not target_sources:
                    target_sources = sources[:3]
            else:
                target_sources = sources[:5]

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
            for source_name, result in all_results:
                if result.mangas:
                    lines.append(f"\n🔍 搜索结果（源: {source_name}）:")
                    for m in result.mangas:
                        status = STATUS_EMOJI.get(m.status, "未知")
                        lines.append(f"  [{idx}] {m.title} - {status}")
                        cache[str(idx)] = m
                        idx += 1

            if idx == 1:
                yield event.plain_result("未找到相关漫画，请确认关键词。")
                return

            lines.append("\n回复「漫画 订阅 <编号>」订阅，如「漫画 订阅 1」")
            self._set_search_cache(event.unified_msg_origin, cache)
            yield event.plain_result("\n".join(lines))

        except SuwayomiError as e:
            yield event.plain_result(f"搜索失败: {e}")
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] search error: {e}")
            yield event.plain_result("搜索失败，漫画服务暂时不可用。")

    # ── 订阅管理 ──────────────────────────────────────────────────

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
                chapters = await self._get_or_fetch_chapters(manga.id)
                if chapters:
                    max_id = max(ch.id for ch in chapters)
                    await self.sub_mgr.update_latest_chapter(manga.id, max_id)
            except Exception as e:
                logger.warning(f"[{PLUGIN_NAME}] 拉取「{manga.title}」章节失败: {e}")
            yield event.plain_result(f"✅ 已订阅「{manga.title}」，有新章节时会推送。")

        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] subscribe error: {e}")
            yield event.plain_result("订阅失败，请稍后重试。")

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
                norm_input = _normalize_zh(manga_id_or_name)
                subs = await self.sub_mgr.get_subscriptions(umo)
                for s in subs:
                    if norm_input in _normalize_zh(s["title"]):
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
            lines = ["📋 你的订阅列表:"]
            for s in subs:
                lines.append(f"  • {s['title']} (ID: {s['manga_id']})")
            yield event.plain_result("\n".join(lines))
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] my_subscriptions error: {e}")
            yield event.plain_result("获取订阅列表失败。")

    # ── 自动推送 ──────────────────────────────────────────────────

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

    # ── 漫画名解析 ────────────────────────────────────────────────

    async def _resolve_manga(self, event: AstrMessageEvent, name_or_id: str, cmd: str) -> tuple[Manga | None, str | None]:
        """Resolve manga by ID or name. Returns (Manga, None) on success or (None, error_msg) on failure."""
        try:
            manga_id = int(name_or_id)
            manga = await self.client.get_manga(manga_id)
            return manga, None
        except (ValueError, SuwayomiError):
            pass

        norm_input = _normalize_zh(name_or_id)
        subs = await self.sub_mgr.get_subscriptions(event.unified_msg_origin)
        for s in subs:
            if norm_input in _normalize_zh(s["title"]):
                try:
                    manga = await self.client.get_manga(s["manga_id"])
                    return manga, None
                except SuwayomiError:
                    continue

        try:
            mangas = await self.client.search_manga_by_title(name_or_id)
            if len(mangas) == 0:
                return None, "未找到该漫画。"
            if len(mangas) == 1:
                return mangas[0], None

            # Build source ID -> display name map
            try:
                sources = await self.client.get_sources()
                src_map = {str(s.id): s.display_name for s in sources}
            except Exception:
                src_map = {}

            lines = [f"找到多个结果，请使用 ID 指定。例如: /漫画 {cmd} {mangas[0].id}"]
            for m in mangas:
                status = STATUS_EMOJI.get(m.status, "未知")
                src_name = src_map.get(str(m.source_id), f"源{m.source_id}")
                lines.append(f"  ID {m.id}: {m.title} [{status}] ({src_name})")
            return None, "\n".join(lines)
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] resolve_manga error: {e}")
            return None, "查找漫画失败。"

    # ── 章节格式化 ────────────────────────────────────────────────

    @staticmethod
    def _fmt_chapter_label(ch: Chapter, num_counts: dict[float, int]) -> str:
        """Format a chapter label: '#num name (ID:xxx)' if duplicate, '#num name' otherwise."""
        num = _fmt_chapter_num(ch.chapter_number)
        dup_tag = f" (ID:{ch.id})" if num_counts.get(ch.chapter_number, 0) > 1 else ""
        if ch.name:
            return f"#{num} {ch.name}{dup_tag}"
        return f"#{num}{dup_tag}"

    # ── 章节获取 ────────────────────────────────────────────────────

    KV_CHAPTER_TS = "suwayomi_chapter_timestamps"

    async def _get_chapter_timestamp(self, manga_id: int) -> float:
        """Get the timestamp of last chapter fetch for a manga."""
        data = await self.get_kv_data(self.KV_CHAPTER_TS, {})
        return data.get(str(manga_id), 0)

    async def _set_chapter_timestamp(self, manga_id: int):
        """Record current time as last chapter fetch time for a manga."""
        data = await self.get_kv_data(self.KV_CHAPTER_TS, {})
        data[str(manga_id)] = time.time()
        await self.put_kv_data(self.KV_CHAPTER_TS, data)

    async def _get_or_fetch_chapters(self, manga_id: int, force: bool = False) -> list:
        """Get chapters from DB. If empty or stale, fetch from source.

        Args:
            manga_id: The manga ID.
            force: If True, always fetch from source regardless of cache.
        """
        cache_hours = self.config.get("chapter_cache_hours", 6)
        if cache_hours < -1:
            cache_hours = 0

        logger.debug(f"[{PLUGIN_NAME}] _get_or_fetch_chapters(manga_id={manga_id}, force={force}, cache_hours={cache_hours})")

        # -1 means always refresh
        if cache_hours == -1:
            try:
                chapters = await self.client.fetch_chapters(manga_id)
                if chapters:
                    await self._set_chapter_timestamp(manga_id)
                logger.debug(f"[{PLUGIN_NAME}] 从源拉取章节(always): manga_id={manga_id}, {len(chapters) if chapters else 0} 章节")
                return chapters
            except SuwayomiError:
                logger.debug(f"[{PLUGIN_NAME}] 源拉取失败，回退DB: manga_id={manga_id}")
                return await self.client.get_chapters(manga_id)

        should_fetch = force

        if not should_fetch and cache_hours > 0:
            last_ts = await self._get_chapter_timestamp(manga_id)
            if last_ts == 0 or (time.time() - last_ts) > cache_hours * 3600:
                should_fetch = True
                logger.debug(f"[{PLUGIN_NAME}] 缓存过期或无记录: manga_id={manga_id}, last_ts={last_ts}")

        if not should_fetch:
            chapters = await self.client.get_chapters(manga_id)
            if chapters:
                logger.debug(f"[{PLUGIN_NAME}] 缓存命中: manga_id={manga_id}, {len(chapters)} 章节")
                return chapters
            should_fetch = True
            logger.debug(f"[{PLUGIN_NAME}] DB为空，触发源拉取: manga_id={manga_id}")

        chapters = await self.client.fetch_chapters(manga_id)
        if chapters:
            await self._set_chapter_timestamp(manga_id)
        logger.debug(f"[{PLUGIN_NAME}] 从源拉取章节: manga_id={manga_id}, {len(chapters) if chapters else 0} 章节")
        return chapters

    # ── 章节列表 ──────────────────────────────────────────────────

    @manga_group.command("章节")
    async def list_chapters(self, event: AstrMessageEvent, manga_name_or_id: str):
        '''查看漫画章节列表。用法: /漫画 章节 <漫画名或ID> [--刷新]'''
        try:
            # Parse from raw message (AstrBot may split args incorrectly)
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

            manga, err = await self._resolve_manga(event, manga_name_or_id, "章节")
            if err or manga is None:
                yield event.plain_result(err or "未找到该漫画。")
                return

            chapters = await self._get_or_fetch_chapters(manga.id, force=force)
            if not chapters:
                yield event.plain_result(f"「{manga.title}」暂无章节。")
                return

            chapters.sort(key=lambda ch: ch.source_order)

            # Detect duplicate chapter numbers
            num_count: dict[float, int] = {}
            for ch in chapters:
                num_count[ch.chapter_number] = num_count.get(ch.chapter_number, 0) + 1

            # Resolve source name
            try:
                sources = await self.client.get_sources()
                src_name = next((s.display_name for s in sources if str(s.id) == str(manga.source_id)), None)
            except Exception:
                src_name = None
            src_tag = f" [{src_name}]" if src_name else ""

            header = f"📖「{manga.title}」{src_tag}章节列表（共 {len(chapters)} 话）:"
            chunks: list[list[str]] = [[]]
            for ch in chapters:
                read_mark = "✅" if ch.is_read else "⬜"
                dl_mark = " 📥" if ch.is_downloaded else ""
                line = f"  {read_mark} {self._fmt_chapter_label(ch, num_count)}{dl_mark}"
                # ~1500 chars per message to stay within platform limits
                current_len = sum(len(l) for l in chunks[-1]) + len(header)
                if current_len + len(line) > 1500 and chunks[-1]:
                    chunks.append([])
                chunks[-1].append(line)

            for i, chunk in enumerate(chunks):
                prefix = header if i == 0 else f"📖「{manga.title}」{src_tag}章节续 ({i + 1}/{len(chunks)}):"
                msg = prefix + "\n" + "\n".join(chunk)
                if i == 0:
                    yield event.plain_result(msg)
                else:
                    await event.send(event.plain_result(msg))

        except SuwayomiError as e:
            yield event.plain_result(f"获取章节失败: {e}")
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] list_chapters error: {e}")
            yield event.plain_result("获取章节列表失败。")

    def _find_chapters_by_num(self, chapters: list, chapter_num_f: float):
        """Find all chapters matching a chapter number. Returns list of matching chapters."""
        return [ch for ch in chapters if abs(ch.chapter_number - chapter_num_f) < 0.01]

    def _find_chapter_by_id(self, chapters: list, chapter_id: int):
        """Find a chapter by its ID."""
        for ch in chapters:
            if ch.id == chapter_id:
                return ch
        return None

    def _resolve_chapter(
        self, chapters: list[Chapter], chapter_num: str, manga_name_or_id: str, cmd: str
    ) -> tuple[Chapter | None, str | None]:
        """Resolve chapter by ID or number string.

        Args:
            chapters: List of chapters.
            chapter_num: User input like "1", "38.5", or "id:123".
            manga_name_or_id: Original manga arg (for disambiguation hint).
            cmd: Command name for hint text ("阅读" or "下载").

        Returns:
            (Chapter, None) on success, (None, error_msg) on failure.
        """
        if chapter_num.lower().startswith("id:"):
            try:
                cid = int(chapter_num[3:])
                target = self._find_chapter_by_id(chapters, cid)
                if target:
                    return target, None
            except ValueError:
                pass
            return None, f"未找到 ID 为 {chapter_num[3:]} 的章节。"

        try:
            chapter_num_f = float(chapter_num)
        except ValueError:
            return None, "章节号格式不正确。"

        matches = self._find_chapters_by_num(chapters, chapter_num_f)
        if len(matches) == 1:
            return matches[0], None
        if len(matches) > 1:
            lines = [f"找到多个第 {_fmt_chapter_num(chapter_num_f)} 话，请使用 ID 指定:"]
            for ch in matches:
                lines.append(f"  ID:{ch.id} - {ch.name}")
            lines.append(f"\n发送「漫画 {cmd} {manga_name_or_id} ID:<ID>」选择")
            return None, "\n".join(lines)
        return None, None

    async def _fetch_pages_local(
        self, chapter_id: int, max_pages: int = 0
    ) -> tuple[int, list[str], list[str]]:
        """Fetch chapter pages and download images to local temp dir.

        Args:
            chapter_id: The chapter ID.
            max_pages: Max pages to fetch (0 = all).

        Returns:
            (total_pages, page_urls, local_paths) — total_pages is the untruncated count.
        """
        pages = await self.client.fetch_chapter_pages(chapter_id)
        if not pages:
            return 0, [], []
        total_pages = len(pages)
        if max_pages > 0:
            pages = pages[:max_pages]
        page_urls = [self.client.build_image_url(p) for p in pages]
        local_paths = await self._download_images(page_urls)
        return total_pages, page_urls, local_paths

    async def _push_chapter_images(self, umo: str, title: str, chapter: Chapter):
        """Push a chapter as inline images to a conversation (reuses read logic)."""
        num_label = _fmt_chapter_num(chapter.chapter_number)
        max_pages = self.config.get("max_pages", 30)
        fetch_mode = self.config.get("image_fetch_mode", "url")

        local_paths: list[str] = []
        try:
            if fetch_mode == "download":
                total_pages, page_urls, local_paths = await self._fetch_pages_local(chapter.id, max_pages)
            else:
                pages = await self.client.fetch_chapter_pages(chapter.id)
                if not pages:
                    return
                total_pages = len(pages)
                page_urls = [self.client.build_image_url(p) for p in pages[:max_pages]]

            if not page_urls:
                return

            def _img(idx: int) -> Comp.Image:
                if fetch_mode == "download" and idx < len(local_paths) and local_paths[idx]:
                    return Comp.Image.fromFileSystem(local_paths[idx])
                return Comp.Image.fromURL(page_urls[idx])

            chain = [Comp.Plain(f"📖「{title}」第 {num_label} 话")]
            chain.extend(_img(i) for i in range(len(page_urls)))
            if total_pages > max_pages:
                chain.append(Comp.Plain(f"... 还有 {total_pages - max_pages} 页，请使用「漫画 阅读」查看"))

            try:
                await self.context.send_message(umo, MessageChain().chain(chain))
            except Exception as e:
                logger.warning(f"[{PLUGIN_NAME}] 图片推送到{umo}失败: {e}")
                await self.context.send_message(umo, MessageChain().message(
                    f"📖「{title}」第 {num_label} 话已更新，但图片发送失败，请使用「漫画 阅读」查看"
                ))
        finally:
            if local_paths:
                valid_paths = [p for p in local_paths if p]
                if valid_paths:
                    parent = Path(valid_paths[0]).parent
                    async def _img_cleanup():
                        await asyncio.sleep(60)
                        try:
                            await asyncio.get_running_loop().run_in_executor(
                                None, lambda: shutil.rmtree(parent, ignore_errors=True)
                            )
                        except Exception:
                            pass
                    asyncio.create_task(_img_cleanup())

    async def _push_chapter_file(self, umo: str, title: str, chapter: Chapter):
        """Push a chapter as a packaged file to a conversation (reuses download logic)."""
        num_label = _fmt_chapter_num(chapter.chapter_number)
        fmt = self.config.get("download_format", "zip")

        _, page_urls, local_paths = await self._fetch_pages_local(chapter.id)
        if not page_urls:
            return

        valid_paths = [p for p in local_paths if p]
        if not valid_paths:
            return

        tmp_dir = Path(valid_paths[0]).parent
        try:
            safe_title = "".join(c for c in title if c not in r'<>:"/\|?*')[:50]
            safe_label = "".join(c for c in str(num_label) if c not in r'<>:"/\|?*')
            ext_map = {"zip": "zip", "pdf": "pdf", "cbz": "cbz"}
            file_ext = ext_map.get(fmt, "zip")
            output_path = tmp_dir / f"{safe_title}_第{safe_label}话.{file_ext}"

            try:
                loop = asyncio.get_running_loop()
                if fmt == "pdf":
                    await loop.run_in_executor(None, pack_pdf, valid_paths, output_path)
                elif fmt == "cbz":
                    await loop.run_in_executor(None, pack_cbz, valid_paths, output_path)
                else:
                    await loop.run_in_executor(None, pack_zip, valid_paths, output_path)
            except Exception as e:
                logger.error(f"[{PLUGIN_NAME}] 自动推送打包失败: {e}")
                return

            filename = f"{safe_title}_第{safe_label}话.{file_ext}"
            chain = [Comp.File(file=str(output_path), name=filename)]
            try:
                await self.context.send_message(umo, MessageChain().chain(chain))
            except Exception as e:
                logger.warning(f"[{PLUGIN_NAME}] 文件推送到{umo}失败: {e}")
                await self.context.send_message(umo, MessageChain().message(
                    f"📖「{title}」第 {num_label} 话已更新，但文件发送失败，请使用「漫画 下载」获取"
                ))
        finally:
            async def _file_cleanup():
                await asyncio.sleep(120)
                try:
                    await asyncio.get_running_loop().run_in_executor(
                        None, lambda: shutil.rmtree(tmp_dir, ignore_errors=True)
                    )
                except Exception:
                    pass
            asyncio.create_task(_file_cleanup())

    # ── 章节阅读 ──────────────────────────────────────────────────

    @manga_group.command("阅读")
    async def read_chapter(self, event: AstrMessageEvent, manga_name_or_id: str, chapter_num: str = ""):
        '''阅读漫画章节。用法: /漫画 阅读 <漫画名或ID> <章节号或ID:数字>'''
        if not chapter_num:
            yield event.plain_result("用法: /漫画 阅读 <漫画名或ID> <章节号>\n示例: /漫画 阅读 一拳超人 1\n指定章节 ID: /漫画 阅读 一拳超人 ID:123")
            return
        try:
            manga, err = await self._resolve_manga(event, manga_name_or_id, "阅读")
            if err or manga is None:
                yield event.plain_result(err or "未找到该漫画。")
                return

            chapters = await self._get_or_fetch_chapters(manga.id)

            target, err_msg = self._resolve_chapter(chapters, chapter_num, manga_name_or_id, "阅读")
            if err_msg:
                yield event.plain_result(err_msg)
                return
            if target is None:
                yield event.plain_result(f"未找到「{manga.title}」指定的章节。")
                return

            try:
                await event.send(event.plain_result(f"📖 正在加载「{manga.title}」第 {_fmt_chapter_num(target.chapter_number)} 话，请稍后..."))
            except Exception:
                pass

            max_pages = self.config.get("max_pages", 30)
            send_mode = self.config.get("send_mode", "image")
            fetch_mode = self.config.get("image_fetch_mode", "url")

            if fetch_mode == "download":
                total_pages, page_urls, local_paths = await self._fetch_pages_local(target.id, max_pages)
            else:
                pages = await self.client.fetch_chapter_pages(target.id)
                if not pages:
                    yield event.plain_result(f"第 {_fmt_chapter_num(target.chapter_number)} 话暂无可用页面。")
                    return
                total_pages = len(pages)
                page_urls = [self.client.build_image_url(p) for p in pages[:max_pages]]
                local_paths = []

            if not page_urls:
                yield event.plain_result(f"第 {_fmt_chapter_num(target.chapter_number)} 话暂无可用页面。")
                return

            def _img(idx: int) -> Comp.Image:
                if fetch_mode == "download" and idx < len(local_paths) and local_paths[idx]:
                    return Comp.Image.fromFileSystem(local_paths[idx])
                if fetch_mode == "download":
                    logger.warning(f"[{PLUGIN_NAME}] 图片 {idx + 1} 下载失败，回退为 URL 模式")
                return Comp.Image.fromURL(page_urls[idx])

            try:
                if send_mode == "forward" and event.get_platform_name() == "aiocqhttp":
                    nodes = []
                    for i in range(len(page_urls)):
                        nodes.append(Comp.Node(
                            uin=event.get_sender_id(),
                            name=f"第 {_fmt_chapter_num(target.chapter_number)} 话 - 第 {i + 1} 页",
                            content=[_img(i)],
                        ))
                    if total_pages > max_pages:
                        nodes.append(Comp.Node(
                            uin=event.get_sender_id(),
                            name="提示",
                            content=[Comp.Plain(f"... 还有 {total_pages - max_pages} 页，请到 WebUI 查看")],
                        ))
                    yield event.chain_result([Comp.Nodes(nodes)])
                else:
                    chain = [_img(i) for i in range(len(page_urls))]
                    if total_pages > max_pages:
                        chain.append(Comp.Plain(f"... 还有 {total_pages - max_pages} 页，请到 WebUI 查看"))
                    yield event.chain_result(chain)
            finally:
                if local_paths:
                    valid_paths = [p for p in local_paths if p]
                    if valid_paths:
                        parent = Path(valid_paths[0]).parent
                        async def _read_cleanup():
                            await asyncio.sleep(60)
                            try:
                                await asyncio.get_running_loop().run_in_executor(
                                    None, lambda: shutil.rmtree(parent, ignore_errors=True)
                                )
                            except Exception:
                                pass
                        asyncio.create_task(_read_cleanup())

        except SuwayomiError as e:
            yield event.plain_result(f"阅读失败: {e}")
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] read_chapter error: {e}")
            yield event.plain_result("阅读章节失败。")

    # ── 章节下载 ──────────────────────────────────────────────────

    @manga_group.command("下载")
    async def download_chapter(self, event: AstrMessageEvent, manga_name_or_id: str, chapter_num: str = ""):
        '''下载漫画章节并打包发送。用法: /漫画 下载 <漫画名或ID> <章节号或ID:数字> [zip/pdf/cbz]'''
        # Parse from raw message (AstrBot may not pass trailing args to handler)
        default_fmt = self.config.get("download_format", "zip")
        manga_name_or_id, chapter_num, fmt = parse_download_args(
            event.message_str, default_fmt
        )

        if not manga_name_or_id or not chapter_num:
            yield event.plain_result(
                "用法: /漫画 下载 <漫画名或ID> <章节号> [格式]\n"
                "示例: /漫画 下载 一拳超人 1\n"
                "指定格式: /漫画 下载 一拳超人 1 pdf\n"
                "指定章节 ID: /漫画 下载 一拳超人 ID:123"
            )
            return

        try:
            manga, err = await self._resolve_manga(event, manga_name_or_id, "下载")
            if err or manga is None:
                yield event.plain_result(err or "未找到该漫画。")
                return

            chapters = await self._get_or_fetch_chapters(manga.id)

            target, err_msg = self._resolve_chapter(chapters, chapter_num, manga_name_or_id, "下载")
            if err_msg:
                yield event.plain_result(err_msg)
                return
            if target is None:
                yield event.plain_result(f"未找到「{manga.title}」指定的章节。")
                return

            num_label = _fmt_chapter_num(target.chapter_number)
            await event.send(event.plain_result(
                f"⏳ 正在下载「{manga.title}」第 {num_label} 话，请稍候..."
            ))

            # Fetch page URLs and download images locally
            _, page_urls, local_paths = await self._fetch_pages_local(target.id)

            if not page_urls:
                yield event.plain_result(f"第 {num_label} 话暂无可用页面。")
                return

            valid_paths = [p for p in local_paths if p]
            if not valid_paths:
                yield event.plain_result("所有页面下载失败，无法打包。")
                return

            if len(valid_paths) < len(page_urls):
                logger.warning(f"[{PLUGIN_NAME}] {len(page_urls) - len(valid_paths)} 页下载失败，将用已有页面打包")

            # Step 4: Pack
            tmp_dir = Path(valid_paths[0]).parent
            safe_title = "".join(c for c in manga.title if c not in r'<>:"/\|?*')[:50]
            safe_label = "".join(c for c in str(num_label) if c not in r'<>:"/\|?*')
            ext_map = {"zip": "zip", "pdf": "pdf", "cbz": "cbz"}
            file_ext = ext_map.get(fmt, "zip")
            output_path = tmp_dir / f"{safe_title}_第{safe_label}话.{file_ext}"

            try:
                loop = asyncio.get_running_loop()
                if fmt == "pdf":
                    await loop.run_in_executor(None, pack_pdf, valid_paths, output_path)
                elif fmt == "cbz":
                    await loop.run_in_executor(None, pack_cbz, valid_paths, output_path)
                else:
                    await loop.run_in_executor(None, pack_zip, valid_paths, output_path)
            except Exception as e:
                logger.error(f"[{PLUGIN_NAME}] 打包失败: {e}")
                yield event.plain_result(f"打包失败: {e}")
                return

            # Step 5: Send file
            filename = f"{safe_title}_第{safe_label}话.{file_ext}"
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

            # Step 6: Cleanup after delay
            async def _cleanup():
                await asyncio.sleep(120)
                try:
                    await asyncio.get_running_loop().run_in_executor(
                        None, lambda: shutil.rmtree(tmp_dir, ignore_errors=True)
                    )
                except Exception:
                    pass
            asyncio.create_task(_cleanup())

        except SuwayomiError as e:
            yield event.plain_result(f"下载失败: {e}")
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] download error: {e}")
            yield event.plain_result("下载失败。")

    # ── 更新检查 ──────────────────────────────────────────────────

    async def _check_updates(self, force: bool = False) -> str:
        """Check for manga updates. Returns a summary string. Pushes to subscribers if updates found.

        Args:
            force: If True, bypass chapter cache and always sync title from source.
        """
        async with self._update_lock:
            all_subs = await self.sub_mgr.get_all_subscriptions()
            if not all_subs:
                return "📭 没有订阅的漫画，无需检查更新。"

            try:
                await self.client.update_library()
            except Exception as e:
                logger.warning(f"[{PLUGIN_NAME}] 触发书库更新失败: {e}")

            updated_mangas: list[tuple[int, str, list[str], list[Chapter], list[str]]] = []

            cache_hours = self.config.get("chapter_cache_hours", 6)
            if cache_hours < -1:
                cache_hours = 0

            for manga_id_str, info in all_subs.items():
                manga_id = int(manga_id_str)
                title = info.get("title", f"ID:{manga_id}")
                latest_stored = info.get("latest_chapter_id", 0)
                subscribers = info.get("subscribers", [])

                if not subscribers:
                    continue

                try:
                    # Sync title when forced or chapter cache is stale
                    if force or cache_hours != 0:
                        last_ts = await self._get_chapter_timestamp(manga_id)
                        if force or last_ts == 0 or cache_hours == -1 or (time.time() - last_ts) > cache_hours * 3600:
                            try:
                                manga = await self.client.get_manga(manga_id)
                                if await self.sub_mgr.update_title(manga_id, manga.title):
                                    logger.info(f"[{PLUGIN_NAME}] 漫画标题已更新: 「{title}」->「{manga.title}」(ID:{manga_id})")
                                    title = manga.title
                            except Exception:
                                pass

                    chapters = await self._get_or_fetch_chapters(manga_id, force=force)
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
                        await self.sub_mgr.update_latest_chapter(manga_id, max_id)
                        logger.info(f"[{PLUGIN_NAME}] 发现更新: 「{title}」新增 {len(new_chapters)} 章节")
                        # Detect duplicate chapter numbers (same logic as list_chapters)
                        num_count: dict[float, int] = {}
                        for ch in chapters:
                            num_count[ch.chapter_number] = num_count.get(ch.chapter_number, 0) + 1

                        new_chapters.sort(key=lambda ch: ch.source_order)
                        ch_info = [self._fmt_chapter_label(ch, num_count) for ch in new_chapters]
                        updated_mangas.append((manga_id, title, ch_info, new_chapters, subscribers))

                except Exception as e:
                    logger.warning(f"[{PLUGIN_NAME}] 检查漫画 {title} (ID:{manga_id}) 更新失败: {e}")
                    continue

            if not updated_mangas:
                logger.info(f"[{PLUGIN_NAME}] 更新检查完成: 检查 {len(all_subs)} 部漫画，暂无更新")
                return "✅ 所有订阅的漫画暂无更新。"

            logger.info(f"[{PLUGIN_NAME}] 更新检查完成: 检查 {len(all_subs)} 部漫画，发现 {len(updated_mangas)} 部有更新")

            user_msgs: dict[str, list[str]] = {}
            for manga_id, title, ch_info, new_chapters, subscribers in updated_mangas:
                latest_num = _fmt_chapter_num(new_chapters[-1].chapter_number)
                msg = f"📢「{title}」更新了！\n新增章节：{', '.join(ch_info)}\n发送「漫画 阅读 {title} {latest_num}」开始阅读"
                for umo in subscribers:
                    user_msgs.setdefault(umo, []).append(msg)

            for umo, msgs in user_msgs.items():
                try:
                    chain = MessageChain().message("\n---\n".join(msgs))
                    await self.context.send_message(umo, chain)
                except Exception as e:
                    logger.warning(f"[{PLUGIN_NAME}] 推送到 {umo} 失败: {e}")

            logger.info(f"[{PLUGIN_NAME}] 更新推送到 {len(user_msgs)} 个会话")

            # Auto-push content for enabled subscribers
            auto_push_mode = self.config.get("auto_push_mode", "image")
            for manga_id, title, ch_info, new_chapters, subscribers in updated_mangas:
                for umo in subscribers:
                    if not self.sub_mgr.is_auto_push_enabled(all_subs, manga_id, umo):
                        continue
                    for ch in new_chapters:
                        try:
                            if auto_push_mode == "file":
                                await self._push_chapter_file(umo, title, ch)
                            else:
                                await self._push_chapter_images(umo, title, ch)
                            await asyncio.sleep(2)
                        except Exception as e:
                            logger.warning(f"[{PLUGIN_NAME}] 自动推送「{title}」第{_fmt_chapter_num(ch.chapter_number)}话到{umo}失败: {e}")

            summary_lines = [f"✅ 发现 {len(updated_mangas)} 部漫画更新："]
            for _, title, ch_info, _, _ in updated_mangas:
                summary_lines.append(f"  • {title}: {', '.join(ch_info)}")
            return "\n".join(summary_lines)

    @manga_group.command("更新")
    async def manual_update(self, event: AstrMessageEvent):
        '''手动检查漫画更新'''
        try:
            summary = await self._check_updates(force=True)
            yield event.plain_result(summary)
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] manual_update error: {e}")
            yield event.plain_result("更新检查失败。")

    # ── WebUI API delegates ────────────────────────────────────────

    @staticmethod
    def _json_response(result):
        """Convert handler result to (jsonify, status) tuple.

        Handler may return dict (200) or (dict, int) tuple (error with status code).
        """
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
                server_url=cfg.get("server_url", "http://localhost:9330"),
                auth_mode=cfg.get("auth_mode", "none"),
                username=cfg.get("username", ""),
                password=cfg.get("password", ""),
            )

        result = await api_config_post(self.config, data, rebuild_client)
        return self._json_response(result)

    async def _api_sources(self):
        result = await api_sources_handler(self.client)
        return self._json_response(result)

    async def _api_update(self):
        result = await api_update_handler(self._check_updates, self.put_kv_data)
        return self._json_response(result)
