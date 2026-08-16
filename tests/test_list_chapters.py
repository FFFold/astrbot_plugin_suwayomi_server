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
    monkeypatch.setattr(
        "plugin_pkg.main.download_cover",
        AsyncMock(return_value=("/tmp/cover.jpg", MagicMock())),
    )
    monkeypatch.setattr("plugin_pkg.main.schedule_cleanup", MagicMock())

    results = [msg async for msg in plugin.list_chapters(event, "测试漫画")]

    assert len(results) == 1
    event.chain_result.assert_called_once()
    event.plain_result.assert_not_called()
    chain = event.chain_result.call_args[0][0]
    assert len(chain) == 2


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
    monkeypatch.setattr("plugin_pkg.main.schedule_cleanup", MagicMock())

    results = [msg async for msg in plugin.list_chapters(event, "测试漫画")]

    assert len(results) == 1
    assert "章节列表" in results[0]
    event.plain_result.assert_called_once()
    event.chain_result.assert_not_called()
    cover_mock.assert_not_awaited()


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
    monkeypatch.setattr(
        "plugin_pkg.main.download_cover",
        AsyncMock(return_value=("/tmp/cover.jpg", MagicMock())),
    )
    monkeypatch.setattr("plugin_pkg.main.schedule_cleanup", MagicMock())

    results = [msg async for msg in plugin.list_chapters(event, "测试漫画")]

    assert len(results) == 1
    event.chain_result.assert_called_once()
    event.plain_result.assert_not_called()
    chain = event.chain_result.call_args[0][0]
    assert len(chain) == 2


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
    monkeypatch.setattr("plugin_pkg.main.schedule_cleanup", MagicMock())

    results = [msg async for msg in plugin.list_chapters(event, "测试漫画")]

    assert len(results) == 1
    assert "章节列表" in results[0]
    event.plain_result.assert_called_once()
    event.chain_result.assert_not_called()
