"""Tests for auto-push (_push_chapter_images, _is_aiocqhttp_target).

Uses a PushTester class that replicates the push logic.
CompSpy tracks what Comp types were created to avoid MagicMock ambiguity.
"""

import asyncio
from dataclasses import dataclass, field
import pytest
from unittest.mock import AsyncMock, MagicMock
from suwayomi.models import Chapter

import plugin_pkg.utils.pusher as pusher_module
from plugin_pkg.utils.pusher import build_image_chain
from astrbot.api import message_components as Comp


@dataclass
class CompSpy:
    """Records all Comp.* calls made during a test."""
    created: list[dict] = field(default_factory=list)

    def Plain(self, text=""):
        self.created.append({"type": "Plain", "text": text})
        return MagicMock()

    def Image_fromURL(self, url=""):
        self.created.append({"type": "Image", "url": url})
        return MagicMock()

    def Node(self, uin="0", name="", content=None):
        self.created.append({"type": "Node", "uin": uin, "name": name, "content_count": len(content or [])})
        return MagicMock()

    def Nodes(self, nodes=None):
        self.created.append({"type": "Nodes", "count": len(nodes or [])})
        return MagicMock()


class FakeConfig:
    def __init__(self, **kwargs):
        self._data = dict(kwargs)
    def get(self, key, default=None):
        return self._data.get(key, default)


def _fmt_chapter_num(num):
    import math
    try:
        if math.isnan(num) or math.isinf(num):
            return "?"
        return int(num) if num == int(num) else num
    except (ValueError, OverflowError):
        return "?"


class PushTester:
    """Minimal plugin replica — same push logic as SuwayomiPlugin."""
    def __init__(self, context, config, comp_spy):
        self.context = context
        self.config = config
        self.c = comp_spy  # Comp-like spy

    def _is_aiocqhttp_target(self, umo: str) -> bool:
        pid = umo.split(":", 1)[0]
        platform = self.context.get_platform_inst(pid)
        return platform is not None and platform.meta().name == "aiocqhttp"

    async def _push_chapter_images(self, umo, title, chapter, pages):
        num_label = _fmt_chapter_num(chapter.chapter_number)
        max_pages = self.config.get("max_pages", 30)
        send_mode = self.config.get("send_mode", "image")

        if not pages:
            return

        page_urls = [f"http://test/page{i}" for i, _ in enumerate(pages[:max_pages])]
        total_pages = len(pages)

        def _img(idx):
            return self.c.Image_fromURL(page_urls[idx])

        try:
            if send_mode == "forward" and self._is_aiocqhttp_target(umo):
                nodes = [self.c.Node(
                    uin="0",
                    name=f"「{title}」第 {num_label} 话",
                    content=[self.c.Plain(f"\U0001f4d6「{title}」第 {num_label} 话")],
                )]
                for i in range(len(page_urls)):
                    nodes.append(self.c.Node(
                        uin="0",
                        name=f"第 {num_label} 话 - 第 {i + 1} 页",
                        content=[_img(i)],
                    ))
                if total_pages > max_pages:
                    nodes.append(self.c.Node(
                        uin="0",
                        name="提示",
                        content=[self.c.Plain(f"... 还有 {total_pages - max_pages} 页")],
                    ))
                self.c.Nodes(nodes)
                await self.context.send_message(umo, MagicMock())
            else:
                chain = [self.c.Plain(f"\U0001f4d6「{title}」第 {num_label} 话")]
                chain.extend(_img(i) for i in range(len(page_urls)))
                if total_pages > max_pages:
                    chain.append(self.c.Plain(f"... 还有 {total_pages - max_pages} 页"))
                await self.context.send_message(umo, MagicMock())
        except Exception:
            await self.context.send_message(umo, MagicMock())
            self.c.created.append({"type": "FallbackText"})


def _fake_pages(n):
    return [MagicMock() for _ in range(n)]


@pytest.fixture
def spy():
    return CompSpy()


@pytest.fixture
def mock_context():
    ctx = MagicMock()
    ctx.send_message = AsyncMock(return_value=True)
    ctx.get_platform_inst = MagicMock(return_value=None)
    return ctx


@pytest.fixture
def aiocqhttp_platform():
    p = MagicMock()
    p.meta.return_value.name = "aiocqhttp"
    return p


@pytest.fixture
def chapter():
    return Chapter(
        id=42, url="", name="第1话", chapter_number=1.0,
        source_order=1, upload_date=0,
        is_downloaded=False,
        manga_id=1, page_count=0,
    )


class TestPushChapterImages:

    @pytest.mark.asyncio
    async def test_inline_mode_sends_direct_images(self, mock_context, spy, chapter):
        """send_mode=image: Plain + N Image, no Nodes."""
        tester = PushTester(mock_context, FakeConfig(send_mode="image", max_pages=30), spy)
        await tester._push_chapter_images("QQ:GroupMessage:999", "Test", chapter, _fake_pages(5))

        types = [c["type"] for c in spy.created]
        assert types == ["Plain"] + ["Image"] * 5

    @pytest.mark.asyncio
    async def test_forward_mode_sends_nodes(self, mock_context, aiocqhttp_platform, spy, chapter):
        """send_mode=forward on aiocqhttp: Nodes wrapping title Node + 3 page Nodes."""
        mock_context.get_platform_inst = MagicMock(return_value=aiocqhttp_platform)
        tester = PushTester(mock_context, FakeConfig(send_mode="forward", max_pages=30), spy)
        await tester._push_chapter_images("QQ:GroupMessage:999", "Test", chapter, _fake_pages(3))

        types = [c["type"] for c in spy.created]
        # Content created in order: Plain→Node→Image→Node→Image→Node→Image→Node→Nodes
        assert types.count("Node") == 4   # title + 3 pages
        assert types.count("Nodes") == 1  # the wrapper
        assert spy.created[-1]["type"] == "Nodes"
        assert spy.created[-1]["count"] == 4

    @pytest.mark.asyncio
    async def test_forward_mode_fallback_on_non_aiocqhttp(self, mock_context, spy, chapter):
        """send_mode=forward but platform not aiocqhttp: inline fallback."""
        tester = PushTester(mock_context, FakeConfig(send_mode="forward", max_pages=30), spy)
        await tester._push_chapter_images("QQ:GroupMessage:999", "Test", chapter, _fake_pages(3))

        types = [c["type"] for c in spy.created]
        # No Nodes at all — just inline Plain + Image
        assert "Nodes" not in types
        assert types == ["Plain"] + ["Image"] * 3

    @pytest.mark.asyncio
    async def test_no_pages_returns_early(self, mock_context, spy, chapter):
        """Empty pages: nothing sent, no Comp calls."""
        tester = PushTester(mock_context, FakeConfig(send_mode="image"), spy)
        await tester._push_chapter_images("QQ:GroupMessage:999", "Test", chapter, [])
        mock_context.send_message.assert_not_called()
        assert spy.created == []

    @pytest.mark.asyncio
    async def test_send_failure_falls_back_to_text(self, mock_context, spy, chapter):
        """send_message raises: fallback text."""
        mock_context.send_message = AsyncMock(side_effect=[RuntimeError("fail"), True])
        tester = PushTester(mock_context, FakeConfig(send_mode="image", max_pages=30), spy)
        await tester._push_chapter_images("QQ:GroupMessage:999", "Test", chapter, _fake_pages(2))

        assert mock_context.send_message.await_count == 2
        assert any(c["type"] == "FallbackText" for c in spy.created)

class TestIsAiocqhttpTarget:

    def test_aiocqhttp_true(self, mock_context):
        p = MagicMock(); p.meta.return_value.name = "aiocqhttp"
        mock_context.get_platform_inst = MagicMock(return_value=p)
        tester = PushTester(mock_context, FakeConfig(), CompSpy())
        assert tester._is_aiocqhttp_target("QQ:GroupMessage:999") is True

    def test_non_aiocqhttp_false(self, mock_context):
        p = MagicMock(); p.meta.return_value.name = "telegram"
        mock_context.get_platform_inst = MagicMock(return_value=p)
        tester = PushTester(mock_context, FakeConfig(), CompSpy())
        assert tester._is_aiocqhttp_target("tg:Private:123") is False

    def test_no_platform_false(self, mock_context):
        mock_context.get_platform_inst = MagicMock(return_value=None)
        tester = PushTester(mock_context, FakeConfig(), CompSpy())
        assert tester._is_aiocqhttp_target("unknown:Group:1") is False


class TestScheduleCleanup:

    @pytest.mark.asyncio
    async def test_cleanup_removes_dir_after_delay(self, tmp_path):
        d = tmp_path / "d"
        d.mkdir()
        pusher_module.schedule_cleanup(d, delay=0.05)
        assert d.exists()
        await asyncio.sleep(0.15)
        assert not d.exists()

    def test_cleanup_skips_none(self):
        assert pusher_module.schedule_cleanup(None) is None

    @pytest.mark.asyncio
    async def test_cancel_pending_cleanups(self, tmp_path):
        d = tmp_path / "d"
        d.mkdir()
        task = pusher_module.schedule_cleanup(d, delay=60)
        assert task is not None
        assert task in pusher_module._cleanup_tasks
        n = pusher_module.cancel_pending_cleanups()
        assert n >= 1
        await asyncio.sleep(0.05)
        assert len(pusher_module._cleanup_tasks) == 0


class TestBuildImageChain:

    @pytest.fixture(autouse=True)
    def reset_comp(self):
        Comp.reset_mock()
        yield

    def test_inline_with_header_and_tail(self):
        chain = build_image_chain(
            ["http://x/1", "http://x/2"], ["", ""], "download",
            send_mode="image", forward_platform=True,
            page_label="第1话", header="📖「T」第1话",
            total_pages=5, max_pages=2, tail_text="tail",
        )
        assert len(chain) == 4
        assert Comp.Plain.call_count == 2
        assert Comp.Image.fromURL.call_count == 2

    def test_forward_with_header(self):
        chain = build_image_chain(
            ["http://x/1"], [""], "download",
            send_mode="forward", forward_platform=True,
            page_label="第1话", header="📖「T」第1话",
            header_node_name="「T」第1话",
            total_pages=1, max_pages=30, tail_text="tail",
        )
        assert len(chain) == 1  # [Nodes]
        assert Comp.Nodes.call_count == 1
        nodes = Comp.Nodes.call_args.args[0]
        assert len(nodes) == 2  # header node + 1 page node

    def test_forward_without_header(self):
        chain = build_image_chain(
            ["http://x/1"], [""], "download",
            send_mode="forward", forward_platform=True,
            page_label="第1话", header=None,
            total_pages=1, max_pages=30, tail_text="tail",
        )
        nodes = Comp.Nodes.call_args.args[0]
        assert len(nodes) == 1

    def test_forward_ignored_on_non_forward_platform(self):
        chain = build_image_chain(
            ["http://x/1"], [""], "download",
            send_mode="forward", forward_platform=False,
            page_label="第1话", header=None,
            total_pages=1, max_pages=30, tail_text="tail",
        )
        assert Comp.Nodes.call_count == 0
        assert len(chain) == 1

    def test_download_mode_uses_local_files(self):
        chain = build_image_chain(
            ["http://x/1"], ["/tmp/1.jpg"], "download",
            send_mode="image", forward_platform=False,
            page_label="第1话", header=None,
            total_pages=1, max_pages=30, tail_text="tail",
        )
        assert Comp.Image.fromFileSystem.call_count == 1
        assert Comp.Image.fromURL.call_count == 0

from pathlib import Path

from plugin_pkg.utils.pusher import schedule_cleanup_file


@pytest.mark.asyncio
async def test_schedule_cleanup_file_deletes_file(tmp_path):
    target = tmp_path / "card.jpg"
    target.write_bytes(b"x")
    schedule_cleanup_file(str(target), delay=0)
    await asyncio.sleep(0.05)
    assert not target.exists()


@pytest.mark.asyncio
async def test_schedule_cleanup_file_none_noop():
    assert schedule_cleanup_file(None) is None
