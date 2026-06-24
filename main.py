from __future__ import annotations

import asyncio
import math
import time

import astrbot.api.message_components as Comp
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.star import Context, Star

from .suwayomi.client import SuwayomiClient, SuwayomiError
from .suwayomi.models import Manga, SearchResult
from .utils.subscription import SubscriptionManager

PLUGIN_NAME = "astrbot_suwayomi_server"

# Search cache TTL in seconds
_CACHE_TTL = 600  # 10 minutes


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
        self.sub_mgr = SubscriptionManager(self.context.get_kv_storage())
        self._search_cache: dict[str, tuple[float, dict[str, Manga]]] = {}
        self._update_lock = asyncio.Lock()
        self._bg_task: asyncio.Task | None = None

        logger.info(f"[{PLUGIN_NAME}] 插件已加载，服务器: {config.get('server_url')}")

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
                    await self._check_updates()
                except Exception as e:
                    logger.error(f"[{PLUGIN_NAME}] 后台更新检查失败: {e}")
        except asyncio.CancelledError:
            pass

    # ── Command Group ──────────────────────────────────────────────

    @filter.command_group("漫画")
    def manga_group(self):
        pass

    # ── 漫画源 ────────────────────────────────────────────────────

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

    # ── 漫画搜索 ──────────────────────────────────────────────────

    @manga_group.command("搜索")
    async def search_manga(self, event: AstrMessageEvent, keyword: str):
        '''搜索漫画。用法: 漫画搜索 <关键词> [源名]'''
        try:
            sources = await self.client.get_sources()
            if not sources:
                yield event.plain_result("未找到已安装的漫画源。")
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

            lines.append("\n回复「漫画订阅 <编号>」订阅，如「漫画订阅 1」")
            self._set_search_cache(event.unified_msg_origin, cache)
            yield event.plain_result("\n".join(lines))

        except SuwayomiError as e:
            yield event.plain_result(f"搜索失败: {e}")
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] search error: {e}")
            yield event.plain_result("搜索失败，漫画服务暂时不可用。")

    # ── 订阅管理 ──────────────────────────────────────────────────

    @manga_group.command("订阅")
    async def subscribe_manga(self, event: AstrMessageEvent, index: int):
        '''订阅漫画。用法: 漫画订阅 <搜索结果编号>'''
        try:
            manga = self._get_cached_manga(event.unified_msg_origin, str(index))

            if manga is None:
                yield event.plain_result("未找到该编号的漫画，请先使用「漫画搜索」。")
                return

            await self.sub_mgr.subscribe(manga.id, manga.title, manga.source_id, event.unified_msg_origin)
            yield event.plain_result(f"✅ 已订阅「{manga.title}」，有新章节时会推送。")

        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] subscribe error: {e}")
            yield event.plain_result("订阅失败，请稍后重试。")

    @manga_group.command("取消订阅")
    async def unsubscribe_manga(self, event: AstrMessageEvent, manga_id_or_name: str):
        '''取消订阅。用法: 漫画取消订阅 <漫画ID或名称>'''
        try:
            umo = event.unified_msg_origin
            manga_id = None

            try:
                manga_id = int(manga_id_or_name)
            except ValueError:
                subs = await self.sub_mgr.get_subscriptions(umo)
                for s in subs:
                    if manga_id_or_name in s["title"]:
                        manga_id = s["manga_id"]
                        break

            if manga_id is None:
                yield event.plain_result("未找到匹配的订阅，请使用漫画 ID 或名称。")
                return

            await self.sub_mgr.unsubscribe(manga_id, umo)
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
                yield event.plain_result("📭 你还没有订阅任何漫画。使用「漫画搜索」来查找并订阅。")
                return
            lines = ["📋 你的订阅列表:"]
            for s in subs:
                lines.append(f"  • {s['title']} (ID: {s['manga_id']})")
            yield event.plain_result("\n".join(lines))
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] my_subscriptions error: {e}")
            yield event.plain_result("获取订阅列表失败。")

    # ── 漫画名解析 ────────────────────────────────────────────────

    async def _resolve_manga(self, event: AstrMessageEvent, name_or_id: str) -> tuple[Manga | None, str | None]:
        """Resolve manga by ID or name. Returns (Manga, None) on success or (None, error_msg) on failure."""
        try:
            manga_id = int(name_or_id)
            manga = await self.client.get_manga(manga_id)
            return manga, None
        except (ValueError, SuwayomiError):
            pass

        subs = await self.sub_mgr.get_subscriptions(event.unified_msg_origin)
        for s in subs:
            if name_or_id in s["title"]:
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
            lines = ["找到多个结果，请使用 ID 指定:"]
            for m in mangas:
                lines.append(f"  ID {m.id}: {m.title}")
            return None, "\n".join(lines)
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] resolve_manga error: {e}")
            return None, "查找漫画失败。"

    # ── 章节列表 ──────────────────────────────────────────────────

    @manga_group.command("章节")
    async def list_chapters(self, event: AstrMessageEvent, manga_name_or_id: str):
        '''查看漫画章节列表。用法: 漫画章节 <漫画名或ID>'''
        try:
            manga, err = await self._resolve_manga(event, manga_name_or_id)
            if err or manga is None:
                yield event.plain_result(err or "未找到该漫画。")
                return

            chapters = await self.client.get_chapters(manga.id)
            if not chapters:
                yield event.plain_result(f"「{manga.title}」暂无章节。")
                return

            display = chapters[:20]
            lines = [f"📖「{manga.title}」章节列表（共 {len(chapters)} 话）:"]
            for ch in display:
                read_mark = "✅" if ch.is_read else "⬜"
                dl_mark = " 📥" if ch.is_downloaded else ""
                lines.append(f"  {read_mark} #{_fmt_chapter_num(ch.chapter_number)} {ch.name}{dl_mark}")

            if len(chapters) > 20:
                lines.append(f"  ... 还有 {len(chapters) - 20} 话，请到 WebUI 查看")

            yield event.plain_result("\n".join(lines))

        except SuwayomiError as e:
            yield event.plain_result(f"获取章节失败: {e}")
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] list_chapters error: {e}")
            yield event.plain_result("获取章节列表失败。")

    # ── 章节阅读 ──────────────────────────────────────────────────

    @manga_group.command("阅读")
    async def read_chapter(self, event: AstrMessageEvent, manga_name_or_id: str, chapter_num: float):
        '''阅读漫画章节。用法: 漫画阅读 <漫画名或ID> <章节号>'''
        try:
            manga, err = await self._resolve_manga(event, manga_name_or_id)
            if err or manga is None:
                yield event.plain_result(err or "未找到该漫画。")
                return

            chapters = await self.client.get_chapters(manga.id)
            target = None
            for ch in chapters:
                if abs(ch.chapter_number - chapter_num) < 0.01:
                    target = ch
                    break

            if target is None:
                yield event.plain_result(f"未找到「{manga.title}」第 {_fmt_chapter_num(chapter_num)} 话。")
                return

            pages = await self.client.fetch_chapter_pages(target.id)
            if not pages:
                yield event.plain_result(f"第 {_fmt_chapter_num(chapter_num)} 话暂无可用页面。")
                return

            max_pages = self.config.get("max_pages", 30)
            send_mode = self.config.get("send_mode", "image")

            if send_mode == "forward" and event.get_platform_name() == "aiocqhttp":
                nodes = []
                for i, page_path in enumerate(pages[:max_pages]):
                    url = self.client.build_image_url(page_path)
                    nodes.append(Comp.Node(
                        uin=event.get_sender_id(),
                        name=f"第 {_fmt_chapter_num(chapter_num)} 话 - 第 {i + 1} 页",
                        content=[Comp.Image.fromURL(url)],
                    ))
                if len(pages) > max_pages:
                    nodes.append(Comp.Node(
                        uin=event.get_sender_id(),
                        name="提示",
                        content=[Comp.Plain(f"... 还有 {len(pages) - max_pages} 页，请到 WebUI 查看")],
                    ))
                yield event.chain_result(nodes)
            else:
                chain = []
                for i, page_path in enumerate(pages[:max_pages]):
                    url = self.client.build_image_url(page_path)
                    chain.append(Comp.Image.fromURL(url))
                if len(pages) > max_pages:
                    chain.append(Comp.Plain(f"... 还有 {len(pages) - max_pages} 页，请到 WebUI 查看"))
                yield event.chain_result(chain)

        except SuwayomiError as e:
            yield event.plain_result(f"阅读失败: {e}")
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] read_chapter error: {e}")
            yield event.plain_result("阅读章节失败。")

    # ── 章节下载 ──────────────────────────────────────────────────

    @manga_group.command("下载")
    async def download_chapter(self, event: AstrMessageEvent, manga_name_or_id: str, chapter_num: float):
        '''下载漫画章节。用法: 漫画下载 <漫画名或ID> <章节号>'''
        try:
            manga, err = await self._resolve_manga(event, manga_name_or_id)
            if err or manga is None:
                yield event.plain_result(err or "未找到该漫画。")
                return

            chapters = await self.client.get_chapters(manga.id)
            target = None
            for ch in chapters:
                if abs(ch.chapter_number - chapter_num) < 0.01:
                    target = ch
                    break

            if target is None:
                yield event.plain_result(f"未找到「{manga.title}」第 {_fmt_chapter_num(chapter_num)} 话。")
                return

            await self.client.enqueue_download([target.id])
            yield event.plain_result(f"✅ 已将「{manga.title} #{_fmt_chapter_num(chapter_num)}」加入下载队列，可在 WebUI 查看进度。")

        except SuwayomiError as e:
            yield event.plain_result(f"下载失败: {e}")
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] download error: {e}")
            yield event.plain_result("下载失败。")

    # ── 更新检查 ──────────────────────────────────────────────────

    async def _check_updates(self) -> str:
        """Check for manga updates. Returns a summary string. Pushes to subscribers if updates found."""
        async with self._update_lock:
            all_subs = await self.sub_mgr.get_all_subscriptions()
            if not all_subs:
                return "📭 没有订阅的漫画，无需检查更新。"

            try:
                await self.client.update_library()
            except Exception as e:
                logger.warning(f"[{PLUGIN_NAME}] 触发书库更新失败: {e}")

            updated_mangas: list[tuple[str, list[str], list[str]]] = []

            for manga_id_str, info in all_subs.items():
                manga_id = int(manga_id_str)
                title = info.get("title", f"ID:{manga_id}")
                latest_stored = info.get("latest_chapter_id", 0)
                subscribers = info.get("subscribers", [])

                if not subscribers:
                    continue

                try:
                    chapters = await self.client.get_chapters(manga_id)
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
                        ch_names = [f"#{_fmt_chapter_num(ch.chapter_number)}" for ch in new_chapters]
                        updated_mangas.append((title, ch_names, subscribers))

                except Exception as e:
                    logger.warning(f"[{PLUGIN_NAME}] 检查漫画 {title} (ID:{manga_id}) 更新失败: {e}")
                    continue

            if not updated_mangas:
                return "✅ 所有订阅的漫画暂无更新。"

            sent_umo: set[str] = set()
            for title, ch_names, subscribers in updated_mangas:
                msg = f"📢「{title}」更新了！\n新增章节：{', '.join(ch_names)}\n发送「漫画阅读 {title} {_fmt_chapter_num(float(ch_names[-1].lstrip('#')))}」开始阅读"
                chain = MessageChain().message(msg)
                for umo in subscribers:
                    if umo not in sent_umo:
                        try:
                            await self.context.send_message(umo, chain)
                            sent_umo.add(umo)
                        except Exception as e:
                            logger.warning(f"[{PLUGIN_NAME}] 推送到 {umo} 失败: {e}")

            summary_lines = [f"✅ 发现 {len(updated_mangas)} 部漫画更新："]
            for title, ch_names, _ in updated_mangas:
                summary_lines.append(f"  • {title}: {', '.join(ch_names)}")
            return "\n".join(summary_lines)

    @manga_group.command("更新")
    async def manual_update(self, event: AstrMessageEvent):
        '''手动检查漫画更新'''
        try:
            summary = await self._check_updates()
            yield event.plain_result(summary)
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] manual_update error: {e}")
            yield event.plain_result("更新检查失败。")
