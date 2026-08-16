"""Command-level card regression tests (no network)."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from plugin_pkg.main import SuwayomiPlugin
from plugin_pkg.suwayomi.models import Manga, SearchResult, Source


def _plugin(cards_enabled=True):
    plugin = SuwayomiPlugin.__new__(SuwayomiPlugin)
    plugin.client = MagicMock()
    plugin.client.auth_headers = {}
    plugin.sub_mgr = MagicMock()
    plugin.config = {
        "chapter_list_show_cover": True,
        "temp_dir": "",
        "download_retries": 3,
        "result_cards_enabled": cards_enabled,
        "card_render_timeout_sec": 30,
    }
    plugin.get_kv_data = AsyncMock(return_value={})
    plugin.put_kv_data = AsyncMock()
    plugin._search_cache = {}
    return plugin


def _event():
    event = MagicMock()
    event.unified_msg_origin = "aiocqhttp:group:g1"
    event.message_str = "/漫画 搜索 咒术回战"
    event.plain_result = MagicMock(side_effect=lambda text: text)
    event.chain_result = MagicMock(side_effect=lambda chain: chain)
    event.send = AsyncMock()
    return event


def _manga(title, mid):
    return Manga(id=mid, source_id=2, url="", title=title,
                 status="ONGOING", thumbnail_url=f"/api/v1/manga/{mid}/thumbnail")


def _source(name="拷贝漫画"):
    return Source(id="2", name="manga", lang="zh", display_name=name)


def _plugin_with_search(plugin, mangas):
    src = _source()
    plugin.client.get_sources = AsyncMock(return_value=[src])
    plugin.client.search_manga = AsyncMock(
        return_value=SearchResult(mangas=mangas, has_next_page=False)
    )


@pytest.mark.asyncio
async def test_search_cards_disabled_keeps_plain_text(monkeypatch):
    plugin = _plugin(cards_enabled=False)
    _plugin_with_search(plugin, [_manga("咒术回战", 1)])
    event = _event()
    monkeypatch.setattr("plugin_pkg.main.SuwayomiClient", MagicMock())

    results = [msg async for msg in plugin.search_manga(event, "咒术回战")]
    assert len(results) == 1
    assert "搜索结果" in results[0]
    event.plain_result.assert_called_once()
    event.chain_result.assert_not_called()


@pytest.mark.asyncio
async def test_search_cards_render_failure_falls_back_to_text(monkeypatch):
    plugin = _plugin(cards_enabled=True)
    _plugin_with_search(plugin, [_manga("咒术回战", 1)])
    event = _event()
    plugin._render_card_result = AsyncMock(return_value=None)

    results = [msg async for msg in plugin.search_manga(event, "咒术回战")]
    assert len(results) == 1
    assert "搜索结果" in results[0]
    event.plain_result.assert_called_once()
    event.chain_result.assert_not_called()


@pytest.mark.asyncio
async def test_search_cards_success_sends_image(monkeypatch):
    plugin = _plugin(cards_enabled=True)
    _plugin_with_search(plugin, [_manga("咒术回战", 1)])
    event = _event()
    plugin._render_card_result = AsyncMock(return_value="/tmp/card.jpg")
    monkeypatch.setattr(
        "plugin_pkg.main.embed_covers",
        AsyncMock(side_effect=lambda c, items, **kw: items),
    )

    results = [msg async for msg in plugin.search_manga(event, "咒术回战")]
    assert len(results) == 1
    event.chain_result.assert_called_once()
    event.plain_result.assert_not_called()
    chain = event.chain_result.call_args[0][0]
    assert len(chain) == 1
