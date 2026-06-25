from __future__ import annotations

import asyncio
import math
import shutil
import tempfile
import time
from pathlib import Path

import aiohttp

import astrbot.api.message_components as Comp
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.star import Context, Star

from .suwayomi.client import SuwayomiClient, SuwayomiError
from .suwayomi.models import Chapter, Manga, SearchResult
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
        self.sub_mgr = SubscriptionManager(self)
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
        tmp_dir = Path(tempfile.mkdtemp(prefix="suwayomi_"))
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
  /漫画 下载 <漫画名或ID> <章节号>      — 下载章节

  重复编号章节可用 id: 指定：
  /漫画 阅读 <漫画名> id:123

🔄 更新
  /漫画 更新  — 手动检查更新（自动推送默认每小时一次）

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
            try:
                await self._get_or_fetch_chapters(manga.id)
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
                yield event.plain_result("📭 你还没有订阅任何漫画。使用「漫画 搜索」来查找并订阅。")
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

            # Build source ID -> display name map
            try:
                sources = await self.client.get_sources()
                src_map = {s.id: s.display_name for s in sources}
            except Exception:
                src_map = {}

            lines = ["找到多个结果，请使用 ID 指定:"]
            for m in mangas:
                status = STATUS_EMOJI.get(m.status, "未知")
                src_name = src_map.get(m.source_id, f"源{m.source_id}")
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

    async def _get_or_fetch_chapters(self, manga_id: int) -> list:
        """Get chapters from DB. If empty, fetch from source. Raises on network errors."""
        chapters = await self.client.get_chapters(manga_id)
        if not chapters:
            chapters = await self.client.fetch_chapters(manga_id)
        return chapters

    # ── 章节列表 ──────────────────────────────────────────────────

    @manga_group.command("章节")
    async def list_chapters(self, event: AstrMessageEvent, manga_name_or_id: str):
        '''查看漫画章节列表。用法: /漫画 章节 <漫画名或ID>'''
        try:
            manga, err = await self._resolve_manga(event, manga_name_or_id)
            if err or manga is None:
                yield event.plain_result(err or "未找到该漫画。")
                return

            chapters = await self._get_or_fetch_chapters(manga.id)
            if not chapters:
                yield event.plain_result(f"「{manga.title}」暂无章节。")
                return

            # Detect duplicate chapter numbers
            num_count: dict[float, int] = {}
            for ch in chapters:
                num_count[ch.chapter_number] = num_count.get(ch.chapter_number, 0) + 1

            display = chapters[:20]
            lines = [f"📖「{manga.title}」章节列表（共 {len(chapters)} 话）:"]
            for ch in display:
                read_mark = "✅" if ch.is_read else "⬜"
                dl_mark = " 📥" if ch.is_downloaded else ""
                lines.append(f"  {read_mark} {self._fmt_chapter_label(ch, num_count)}{dl_mark}")

            if len(chapters) > 20:
                lines.append(f"  ... 还有 {len(chapters) - 20} 话，请到 WebUI 查看")

            yield event.plain_result("\n".join(lines))

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

    # ── 章节阅读 ──────────────────────────────────────────────────

    @manga_group.command("阅读")
    async def read_chapter(self, event: AstrMessageEvent, manga_name_or_id: str, chapter_num: str):
        '''阅读漫画章节。用法: /漫画 阅读 <漫画名或ID> <章节号或ID:数字>'''
        try:
            manga, err = await self._resolve_manga(event, manga_name_or_id)
            if err or manga is None:
                yield event.plain_result(err or "未找到该漫画。")
                return

            chapters = await self._get_or_fetch_chapters(manga.id)

            # Support "id:123" syntax to select chapter by ID
            target = None
            if chapter_num.startswith("id:"):
                try:
                    cid = int(chapter_num[3:])
                    target = self._find_chapter_by_id(chapters, cid)
                except ValueError:
                    pass
            else:
                chapter_num_f = float(chapter_num)
                matches = self._find_chapters_by_num(chapters, chapter_num_f)
                if len(matches) == 1:
                    target = matches[0]
                elif len(matches) > 1:
                    lines = [f"找到多个第 {_fmt_chapter_num(chapter_num_f)} 话，请使用 ID 指定:"]
                    for ch in matches:
                        lines.append(f"  ID:{ch.id} - {ch.name}")
                    lines.append(f"\n发送「漫画 阅读 {manga_name_or_id} id:<ID>」选择")
                    yield event.plain_result("\n".join(lines))
                    return

            if target is None:
                yield event.plain_result(f"未找到「{manga.title}」指定的章节。")
                return

            try:
                await event.send(event.plain_result(f"📖 正在加载「{manga.title}」第 {_fmt_chapter_num(target.chapter_number)} 话，请稍后..."))
            except Exception:
                pass
            pages = await self.client.fetch_chapter_pages(target.id)
            if not pages:
                yield event.plain_result(f"第 {_fmt_chapter_num(target.chapter_number)} 话暂无可用页面。")
                return

            max_pages = self.config.get("max_pages", 30)
            send_mode = self.config.get("send_mode", "image")
            fetch_mode = self.config.get("image_fetch_mode", "url")

            page_urls = [self.client.build_image_url(p) for p in pages[:max_pages]]
            local_paths: list[str] = []

            if fetch_mode == "download":
                local_paths = await self._download_images(page_urls)

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
                    if len(pages) > max_pages:
                        nodes.append(Comp.Node(
                            uin=event.get_sender_id(),
                            name="提示",
                            content=[Comp.Plain(f"... 还有 {len(pages) - max_pages} 页，请到 WebUI 查看")],
                        ))
                    yield event.chain_result([Comp.Nodes(nodes)])
                else:
                    chain = [_img(i) for i in range(len(page_urls))]
                    if len(pages) > max_pages:
                        chain.append(Comp.Plain(f"... 还有 {len(pages) - max_pages} 页，请到 WebUI 查看"))
                    yield event.chain_result(chain)
            finally:
                if local_paths:
                    valid_paths = [p for p in local_paths if p]
                    if valid_paths:
                        parent = str(Path(valid_paths[0]).parent)
                        asyncio.get_event_loop().call_later(
                            60, lambda d=parent: shutil.rmtree(d, ignore_errors=True)
                        )

        except SuwayomiError as e:
            yield event.plain_result(f"阅读失败: {e}")
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] read_chapter error: {e}")
            yield event.plain_result("阅读章节失败。")

    # ── 章节下载 ──────────────────────────────────────────────────

    @manga_group.command("下载")
    async def download_chapter(self, event: AstrMessageEvent, manga_name_or_id: str, chapter_num: str):
        '''下载漫画章节。用法: /漫画 下载 <漫画名或ID> <章节号或ID:数字>'''
        try:
            manga, err = await self._resolve_manga(event, manga_name_or_id)
            if err or manga is None:
                yield event.plain_result(err or "未找到该漫画。")
                return

            chapters = await self._get_or_fetch_chapters(manga.id)

            target = None
            if chapter_num.startswith("id:"):
                try:
                    cid = int(chapter_num[3:])
                    target = self._find_chapter_by_id(chapters, cid)
                except ValueError:
                    pass
            else:
                chapter_num_f = float(chapter_num)
                matches = self._find_chapters_by_num(chapters, chapter_num_f)
                if len(matches) == 1:
                    target = matches[0]
                elif len(matches) > 1:
                    lines = [f"找到多个第 {_fmt_chapter_num(chapter_num_f)} 话，请使用 ID 指定:"]
                    for ch in matches:
                        lines.append(f"  ID:{ch.id} - {ch.name}")
                    lines.append(f"\n发送「漫画 下载 {manga_name_or_id} id:<ID>」选择")
                    yield event.plain_result("\n".join(lines))
                    return

            if target is None:
                yield event.plain_result(f"未找到「{manga.title}」指定的章节。")
                return

            await self.client.enqueue_download([target.id])
            yield event.plain_result(f"✅ 已将「{manga.title} #{_fmt_chapter_num(target.chapter_number)}」加入下载队列，可在 WebUI 查看进度。")

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

            updated_mangas: list[tuple[str, list[str], Chapter, list[str]]] = []

            for manga_id_str, info in all_subs.items():
                manga_id = int(manga_id_str)
                title = info.get("title", f"ID:{manga_id}")
                latest_stored = info.get("latest_chapter_id", 0)
                subscribers = info.get("subscribers", [])

                if not subscribers:
                    continue

                try:
                    chapters = await self._get_or_fetch_chapters(manga_id)
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
                        # Detect duplicate chapter numbers (same logic as list_chapters)
                        num_count: dict[float, int] = {}
                        for ch in chapters:
                            num_count[ch.chapter_number] = num_count.get(ch.chapter_number, 0) + 1

                        ch_info = [self._fmt_chapter_label(ch, num_count) for ch in new_chapters]
                        updated_mangas.append((title, ch_info, new_chapters[-1], subscribers))

                except Exception as e:
                    logger.warning(f"[{PLUGIN_NAME}] 检查漫画 {title} (ID:{manga_id}) 更新失败: {e}")
                    continue

            if not updated_mangas:
                return "✅ 所有订阅的漫画暂无更新。"

            sent_umo: set[str] = set()
            for title, ch_info, last_ch, subscribers in updated_mangas:
                latest_num = _fmt_chapter_num(last_ch.chapter_number)
                msg = f"📢「{title}」更新了！\n新增章节：{', '.join(ch_info)}\n发送「漫画 阅读 {title} {latest_num}」开始阅读"
                chain = MessageChain().message(msg)
                for umo in subscribers:
                    if umo not in sent_umo:
                        try:
                            await self.context.send_message(umo, chain)
                            sent_umo.add(umo)
                        except Exception as e:
                            logger.warning(f"[{PLUGIN_NAME}] 推送到 {umo} 失败: {e}")

            summary_lines = [f"✅ 发现 {len(updated_mangas)} 部漫画更新："]
            for title, ch_info, _, _ in updated_mangas:
                summary_lines.append(f"  • {title}: {', '.join(ch_info)}")
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
