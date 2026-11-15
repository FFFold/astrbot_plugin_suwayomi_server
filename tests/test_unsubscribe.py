"""Unit tests for /漫画 取消订阅 reference syntax (no network)."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from plugin_pkg.main import SuwayomiPlugin


def _plugin(subscriptions=None, removed=True):
    plugin = SuwayomiPlugin.__new__(SuwayomiPlugin)
    plugin.sub_mgr = MagicMock()
    plugin.sub_mgr.get_subscriptions = AsyncMock(return_value=subscriptions or [])
    plugin.sub_mgr.unsubscribe = AsyncMock(return_value=removed)
    return plugin


def _event(message):
    event = MagicMock()
    event.unified_msg_origin = "aiocqhttp:group:g1"
    event.message_str = message
    event.plain_result = MagicMock(side_effect=lambda text: text)
    return event


@pytest.mark.asyncio
async def test_unsubscribe_accepts_id_prefix():
    plugin = _plugin([{"manga_id": 151, "title": "安达与岛村"}])
    results = [
        m async for m in plugin.unsubscribe_manga(
            _event("/漫画 取消订阅 ID:151"), "ID:151"
        )
    ]
    plugin.sub_mgr.unsubscribe.assert_awaited_once_with(151, "aiocqhttp:group:g1")
    assert "已取消订阅" in results[0]


@pytest.mark.asyncio
async def test_unsubscribe_rejects_bare_number_with_guidance():
    plugin = _plugin([{"manga_id": 151, "title": "安达与岛村"}])
    results = [
        m async for m in plugin.unsubscribe_manga(_event("/漫画 取消订阅 3"), "3")
    ]
    plugin.sub_mgr.unsubscribe.assert_not_awaited()
    assert "不支持搜索结果编号" in results[0]


@pytest.mark.asyncio
async def test_unsubscribe_unsubscribed_id_is_reported():
    plugin = _plugin([{"manga_id": 151, "title": "安达与岛村"}], removed=False)
    results = [
        m async for m in plugin.unsubscribe_manga(
            _event("/漫画 取消订阅 ID:9"), "ID:9"
        )
    ]
    plugin.sub_mgr.unsubscribe.assert_awaited_once_with(9, "aiocqhttp:group:g1")
    assert "未找到该订阅" in results[0] and "ID:9" in results[0]


@pytest.mark.asyncio
async def test_unsubscribe_by_name_still_works():
    plugin = _plugin([{"manga_id": 151, "title": "安达与岛村"}])
    results = [
        m async for m in plugin.unsubscribe_manga(
            _event("/漫画 取消订阅 安达与岛村"), "安达与岛村"
        )
    ]
    plugin.sub_mgr.unsubscribe.assert_awaited_once_with(151, "aiocqhttp:group:g1")
    assert "已取消订阅" in results[0]
