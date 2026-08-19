"""Unit tests for the /漫画 章节 cover enhancement (no network)."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from plugin_pkg.main import SuwayomiPlugin
from plugin_pkg.suwayomi.models import Chapter, Manga


def _make_plugin(config: dict | None = None) -> SuwayomiPlugin:
    plugin = SuwayomiPlugin.__new__(SuwayomiPlugin)
    plugin.client = MagicMock()
    plugin.client.auth_headers = {}
    plugin.client.get_sources = AsyncMock(return_value=[])
    plugin.sub_mgr = MagicMock()
    plugin.config = {
        "chapter_list_show_cover": True,
        "result_cards_enabled": False,
        "temp_dir": "",
        "download_retries": 3,
        **(config or {}),
    }
    plugin.get_kv_data = AsyncMock(return_value={})
    plugin.put_kv_data = AsyncMock()
    return plugin


def _make_event():
    event = MagicMock()
    event.message_str = "/漫画 章节 测试漫画"
    event.plain_result = MagicMock(side_effect=lambda text: text)
    event.chain_result = MagicMock(side_effect=lambda chain: chain)
    event.send = AsyncMock()
    return event


def _make_manga() -> Manga:
    return Manga(
        id=1,
        source_id=2,
        url="",
        title="测试漫画",
        thumbnail_url="/api/v1/manga/1/thumbnail",
        description="测试漫画简介",
    )


def _make_chapters() -> list[Chapter]:
    return [Chapter(id=1, url="", name="第1话", chapter_number=1.0)]


@pytest.mark.asyncio
async def test_list_chapters_first_message_uses_cover_chain(monkeypatch):
    manga = _make_manga()
    chapters = _make_chapters()
    plugin = _make_plugin()
    event = _make_event()

    monkeypatch.setattr(
        "plugin_pkg.main.resolve_manga", AsyncMock(return_value=(manga, None))
    )
    monkeypatch.setattr(
        "plugin_pkg.main.get_or_fetch_chapters", AsyncMock(return_value=chapters)
    )
    cover_tmp = MagicMock()
    monkeypatch.setattr(
        "plugin_pkg.main.download_cover",
        AsyncMock(return_value=("/tmp/cover.jpg", cover_tmp)),
    )
    schedule_cleanup_mock = MagicMock()
    monkeypatch.setattr("plugin_pkg.main.schedule_cleanup", schedule_cleanup_mock)

    results = [msg async for msg in plugin.list_chapters(event, "测试漫画")]

    assert len(results) == 1
    event.chain_result.assert_called_once()
    event.plain_result.assert_not_called()
    chain = event.chain_result.call_args[0][0]
    assert len(chain) == 2
    schedule_cleanup_mock.assert_called_once()
    cleanup_args = schedule_cleanup_mock.call_args
    assert cleanup_args.args[0] is cover_tmp
    assert cleanup_args.kwargs.get("delay") == 60


@pytest.mark.asyncio
async def test_list_chapters_cover_disabled_uses_plain_text(monkeypatch):
    manga = _make_manga()
    chapters = _make_chapters()
    plugin = _make_plugin(config={"chapter_list_show_cover": False})
    event = _make_event()
    cover_mock = AsyncMock()

    monkeypatch.setattr(
        "plugin_pkg.main.resolve_manga", AsyncMock(return_value=(manga, None))
    )
    monkeypatch.setattr(
        "plugin_pkg.main.get_or_fetch_chapters", AsyncMock(return_value=chapters)
    )
    monkeypatch.setattr("plugin_pkg.main.download_cover", cover_mock)
    schedule_cleanup_mock = MagicMock()
    monkeypatch.setattr("plugin_pkg.main.schedule_cleanup", schedule_cleanup_mock)

    results = [msg async for msg in plugin.list_chapters(event, "测试漫画")]

    assert len(results) == 1
    assert "章节列表" in results[0]
    event.plain_result.assert_called_once()
    event.chain_result.assert_not_called()
    cover_mock.assert_not_awaited()
    schedule_cleanup_mock.assert_not_called()


@pytest.mark.asyncio
async def test_list_chapters_no_chapters_still_shows_cover(monkeypatch):
    manga = _make_manga()
    plugin = _make_plugin()
    event = _make_event()

    monkeypatch.setattr(
        "plugin_pkg.main.resolve_manga", AsyncMock(return_value=(manga, None))
    )
    monkeypatch.setattr(
        "plugin_pkg.main.get_or_fetch_chapters", AsyncMock(return_value=[])
    )
    cover_tmp = MagicMock()
    monkeypatch.setattr(
        "plugin_pkg.main.download_cover",
        AsyncMock(return_value=("/tmp/cover.jpg", cover_tmp)),
    )
    schedule_cleanup_mock = MagicMock()
    monkeypatch.setattr("plugin_pkg.main.schedule_cleanup", schedule_cleanup_mock)

    results = [msg async for msg in plugin.list_chapters(event, "测试漫画")]

    assert len(results) == 1
    event.chain_result.assert_called_once()
    event.plain_result.assert_not_called()
    chain = event.chain_result.call_args[0][0]
    assert len(chain) == 2
    schedule_cleanup_mock.assert_called_once()
    cleanup_args = schedule_cleanup_mock.call_args
    assert cleanup_args.args[0] is cover_tmp
    assert cleanup_args.kwargs.get("delay") == 60


@pytest.mark.asyncio
async def test_list_chapters_missing_cover_falls_back_to_plain_text(monkeypatch):
    manga = _make_manga()
    chapters = _make_chapters()
    plugin = _make_plugin()
    event = _make_event()

    monkeypatch.setattr(
        "plugin_pkg.main.resolve_manga", AsyncMock(return_value=(manga, None))
    )
    monkeypatch.setattr(
        "plugin_pkg.main.get_or_fetch_chapters", AsyncMock(return_value=chapters)
    )
    monkeypatch.setattr(
        "plugin_pkg.main.download_cover", AsyncMock(return_value=(None, None))
    )
    schedule_cleanup_mock = MagicMock()
    monkeypatch.setattr("plugin_pkg.main.schedule_cleanup", schedule_cleanup_mock)

    results = [msg async for msg in plugin.list_chapters(event, "测试漫画")]

    assert len(results) == 1
    assert "章节列表" in results[0]
    event.plain_result.assert_called_once()
    event.chain_result.assert_not_called()
    schedule_cleanup_mock.assert_not_called()


@pytest.mark.asyncio
async def test_list_chapters_skips_download_cover_when_thumbnail_is_none(monkeypatch):
    manga = _make_manga()
    manga.thumbnail_url = None
    chapters = _make_chapters()
    plugin = _make_plugin()
    event = _make_event()
    cover_mock = AsyncMock()

    monkeypatch.setattr(
        "plugin_pkg.main.resolve_manga", AsyncMock(return_value=(manga, None))
    )
    monkeypatch.setattr(
        "plugin_pkg.main.get_or_fetch_chapters", AsyncMock(return_value=chapters)
    )
    monkeypatch.setattr("plugin_pkg.main.download_cover", cover_mock)
    schedule_cleanup_mock = MagicMock()
    monkeypatch.setattr("plugin_pkg.main.schedule_cleanup", schedule_cleanup_mock)

    results = [msg async for msg in plugin.list_chapters(event, "测试漫画")]

    assert len(results) == 1
    assert "章节列表" in results[0]
    event.plain_result.assert_called_once()
    event.chain_result.assert_not_called()
    cover_mock.assert_not_awaited()
    schedule_cleanup_mock.assert_not_called()


@pytest.mark.asyncio
async def test_list_chapters_skips_download_cover_when_thumbnail_is_empty_string(monkeypatch):
    manga = _make_manga()
    manga.thumbnail_url = ""
    chapters = _make_chapters()
    plugin = _make_plugin()
    event = _make_event()
    cover_mock = AsyncMock()

    monkeypatch.setattr(
        "plugin_pkg.main.resolve_manga", AsyncMock(return_value=(manga, None))
    )
    monkeypatch.setattr(
        "plugin_pkg.main.get_or_fetch_chapters", AsyncMock(return_value=chapters)
    )
    monkeypatch.setattr("plugin_pkg.main.download_cover", cover_mock)
    schedule_cleanup_mock = MagicMock()
    monkeypatch.setattr("plugin_pkg.main.schedule_cleanup", schedule_cleanup_mock)

    results = [msg async for msg in plugin.list_chapters(event, "测试漫画")]

    assert len(results) == 1
    assert "章节列表" in results[0]
    event.plain_result.assert_called_once()
    event.chain_result.assert_not_called()
    cover_mock.assert_not_awaited()
    schedule_cleanup_mock.assert_not_called()


@pytest.mark.asyncio
async def test_list_chapters_cover_download_error_falls_back_to_plain_text(monkeypatch):
    manga = _make_manga()
    chapters = _make_chapters()
    plugin = _make_plugin()
    event = _make_event()

    monkeypatch.setattr(
        "plugin_pkg.main.resolve_manga", AsyncMock(return_value=(manga, None))
    )
    monkeypatch.setattr(
        "plugin_pkg.main.get_or_fetch_chapters", AsyncMock(return_value=chapters)
    )
    monkeypatch.setattr(
        "plugin_pkg.main.download_cover", AsyncMock(side_effect=OSError("boom"))
    )
    schedule_cleanup_mock = MagicMock()
    monkeypatch.setattr("plugin_pkg.main.schedule_cleanup", schedule_cleanup_mock)

    results = [msg async for msg in plugin.list_chapters(event, "测试漫画")]

    assert len(results) == 1
    assert "章节列表" in results[0]
    event.plain_result.assert_called_once()
    event.chain_result.assert_not_called()
    schedule_cleanup_mock.assert_not_called()


@pytest.mark.asyncio
async def test_list_chapters_chapters_error_cleans_cover_tmp_and_returns_error(monkeypatch):
    manga = _make_manga()
    plugin = _make_plugin()
    event = _make_event()
    cover_tmp = MagicMock()

    monkeypatch.setattr(
        "plugin_pkg.main.resolve_manga", AsyncMock(return_value=(manga, None))
    )
    monkeypatch.setattr(
        "plugin_pkg.main.get_or_fetch_chapters",
        AsyncMock(side_effect=RuntimeError("chapters failed")),
    )
    monkeypatch.setattr(
        "plugin_pkg.main.download_cover",
        AsyncMock(return_value=("/tmp/cover.jpg", cover_tmp)),
    )
    schedule_cleanup_mock = MagicMock()
    monkeypatch.setattr("plugin_pkg.main.schedule_cleanup", schedule_cleanup_mock)

    results = [msg async for msg in plugin.list_chapters(event, "测试漫画")]

    assert len(results) == 1
    assert "获取章节列表失败" in results[0]
    event.chain_result.assert_not_called()
    schedule_cleanup_mock.assert_called_once()
    cleanup_args = schedule_cleanup_mock.call_args
    assert cleanup_args.args[0] is cover_tmp
    assert cleanup_args.kwargs.get("delay") == 60


@pytest.mark.asyncio
async def test_list_chapters_cards_success_multiple_images(monkeypatch):
    manga = _make_manga()
    chapters = [Chapter(id=i, url="", name=f"第{i}话", chapter_number=float(i),
                        source_order=i, manga_id=1) for i in range(1, 300)]
    plugin = _make_plugin(config={"result_cards_enabled": True})
    event = _make_event()

    monkeypatch.setattr("plugin_pkg.main.resolve_manga", AsyncMock(return_value=(manga, None)))
    monkeypatch.setattr("plugin_pkg.main.get_or_fetch_chapters", AsyncMock(return_value=chapters))
    monkeypatch.setattr(
        "plugin_pkg.main.embed_covers",
        AsyncMock(side_effect=lambda c, items, **kw: [dict(i, cover_data_url="x") for i in items]),
    )
    download_cover_mock = AsyncMock(return_value=("/tmp/cover.jpg", MagicMock()))
    monkeypatch.setattr("plugin_pkg.main.download_cover", download_cover_mock)
    plugin._render_card_result = AsyncMock(
        side_effect=lambda data: f"/tmp/card{data['title']}.jpg"
    )
    schedule_cleanup_mock = MagicMock()
    monkeypatch.setattr("plugin_pkg.main.schedule_cleanup", schedule_cleanup_mock)

    _ = [msg async for msg in plugin.list_chapters(event, "测试漫画")]

    # 3 张卡：第 1 张 yield，后续 2 张 event.send
    assert event.chain_result.call_count == 3
    assert event.send.await_count == 2
    assert event.send.await_count == plugin._render_card_result.call_count - 1
    event.plain_result.assert_not_called()
    # 首张卡头部携带漫画简介，续卡不含
    first_card = plugin._render_card_result.call_args_list[0][0][0]
    assert first_card["synopsis"] == "测试漫画简介"
    # 卡片模式封面由 embed_covers 统一负责：不调用 download_cover，无临时目录泄漏
    download_cover_mock.assert_not_awaited()
    schedule_cleanup_mock.assert_not_called()


@pytest.mark.asyncio
async def test_list_chapters_cards_render_failure_falls_back(monkeypatch):
    manga = _make_manga()
    chapters = [Chapter(id=i, url="", name=f"第{i}话", chapter_number=float(i),
                        source_order=i, manga_id=1) for i in range(1, 4)]
    plugin = _make_plugin(config={"result_cards_enabled": True})
    event = _make_event()
    plugin._render_card_result = AsyncMock(return_value=None)
    monkeypatch.setattr("plugin_pkg.main.resolve_manga", AsyncMock(return_value=(manga, None)))
    monkeypatch.setattr("plugin_pkg.main.get_or_fetch_chapters", AsyncMock(return_value=chapters))
    download_cover_mock = AsyncMock(return_value=("/tmp/cover.jpg", MagicMock()))
    monkeypatch.setattr("plugin_pkg.main.download_cover", download_cover_mock)
    schedule_cleanup_mock = MagicMock()
    monkeypatch.setattr("plugin_pkg.main.schedule_cleanup", schedule_cleanup_mock)
    monkeypatch.setattr(
        "plugin_pkg.main.embed_covers",
        AsyncMock(side_effect=lambda c, items, **kw: [dict(i, cover_data_url="x") for i in items]),
    )

    results = [msg async for msg in plugin.list_chapters(event, "测试漫画")]

    assert len(results) == 1
    assert "章节列表" in results[0]
    # 卡片模式未预下载封面，回退时直接纯文本（无封面）
    event.plain_result.assert_called_once()
    event.chain_result.assert_not_called()
    download_cover_mock.assert_not_awaited()
    schedule_cleanup_mock.assert_not_called()
