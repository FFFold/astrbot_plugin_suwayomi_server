"""Wiring tests: every resolve_manga call site forwards index_lookup (no network)."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from plugin_pkg.main import SuwayomiPlugin


def _plugin():
    plugin = SuwayomiPlugin.__new__(SuwayomiPlugin)
    plugin.client = MagicMock()
    plugin.client.auth_headers = {}
    plugin.sub_mgr = MagicMock()
    plugin.config = {"result_cards_enabled": False}
    plugin.get_kv_data = AsyncMock(return_value={})
    plugin.put_kv_data = AsyncMock()
    plugin._search_cache = {}
    return plugin


def _event(message):
    event = MagicMock()
    event.unified_msg_origin = "aiocqhttp:group:g1"
    event.message_str = message
    event.plain_result = MagicMock(side_effect=lambda text: text)
    event.chain_result = MagicMock(side_effect=lambda chain: chain)
    event.send = AsyncMock()
    return event


@pytest.mark.asyncio
async def test_read_chapter_forwards_index_lookup(monkeypatch):
    plugin = _plugin()
    mocked = AsyncMock(return_value=(None, "stop"))
    monkeypatch.setattr("plugin_pkg.main.resolve_manga", mocked)

    _ = [m async for m in plugin.read_chapter(_event("/漫画 阅读 3 5"), "3", "5")]

    assert mocked.call_args.kwargs["index_lookup"].__self__ is plugin


@pytest.mark.asyncio
async def test_download_chapter_forwards_index_lookup(monkeypatch):
    plugin = _plugin()
    mocked = AsyncMock(return_value=(None, "stop"))
    monkeypatch.setattr("plugin_pkg.main.resolve_manga", mocked)

    _ = [m async for m in plugin.download_chapter(_event("/漫画 下载 3 5"), "3", "5")]

    assert mocked.call_args.kwargs["index_lookup"].__self__ is plugin
