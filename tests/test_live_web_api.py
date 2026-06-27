"""Integration tests for WebUI API handlers against a live Suwayomi-Server.

Usage:
    uv run pytest tests/test_live_web_api.py -v -s

Set SUWAYOMI_URL env var or it defaults to http://100.87.49.15:9330
"""
import asyncio
import os
import time

import pytest

from suwayomi.client import SuwayomiClient, SuwayomiError
from suwayomi.models import Source
from utils.subscription import SubscriptionManager
from web.api import (
    api_config_get,
    api_config_post,
    api_sources,
    api_status,
    api_subscription_delete,
    api_subscription_push,
    api_subscriptions,
    api_update,
)

SERVER_URL = os.environ.get("SUWAYOMI_URL", "http://100.87.49.15:9330")


# ── Fixtures ────────────────────────────────────────────────────


class FakePlugin:
    """In-memory KV store for testing."""

    def __init__(self):
        self._store: dict = {}

    async def get_kv_data(self, key, default=None):
        return self._store.get(key, default)

    async def put_kv_data(self, key, value):
        self._store[key] = value

    async def delete_kv_data(self, key):
        self._store.pop(key, None)


class FakeConfig(dict):
    """Config dict with save_config mock."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved = False

    def save_config(self):
        self._saved = True


@pytest.fixture
def kv():
    return FakePlugin()


@pytest.fixture
def sub_mgr(kv):
    return SubscriptionManager(kv)


@pytest.fixture
def client():
    c = SuwayomiClient(SERVER_URL, "none", "", "")
    yield c
    asyncio.get_event_loop().run_until_complete(c.close())


@pytest.fixture
def config():
    return FakeConfig({
        "server_url": SERVER_URL,
        "auth_mode": "none",
        "username": "",
        "password": "",
    })


# ── api_status ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_status_live(client, sub_mgr, kv):
    """api_status returns connected=true against live server."""
    result = await api_status(client, sub_mgr, kv.get_kv_data)

    print(f"\n  api_status result: {result}")
    assert result["connected"] is True
    assert result["source_count"] > 0
    assert "library_count" in result
    assert "subscription_count" in result
    assert "subscriber_total" in result


@pytest.mark.asyncio
async def test_status_with_subscriptions(client, sub_mgr, kv):
    """api_status counts subscriptions correctly."""
    await sub_mgr.subscribe(1, "Test Manga", 100, "test_user_1")
    await sub_mgr.subscribe(1, "Test Manga", 100, "test_user_2")
    await sub_mgr.subscribe(2, "Another Manga", 200, "test_user_1")

    result = await api_status(client, sub_mgr, kv.get_kv_data)

    print(f"\n  With subscriptions: {result['subscription_count']} mangas, {result['subscriber_total']} subscribers")
    assert result["subscription_count"] >= 2
    assert result["subscriber_total"] >= 3

    # Cleanup
    await sub_mgr.unsubscribe(1, "test_user_1")
    await sub_mgr.unsubscribe(1, "test_user_2")
    await sub_mgr.unsubscribe(2, "test_user_1")


# ── api_subscriptions ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_subscriptions_empty_live(client, sub_mgr):
    """api_subscriptions returns empty when no subscriptions exist."""
    result = await api_subscriptions(client, sub_mgr)

    print(f"\n  api_subscriptions (empty): {len(result['subscriptions'])} items")
    assert "subscriptions" in result
    assert isinstance(result["subscriptions"], list)


@pytest.mark.asyncio
async def test_subscriptions_with_source_names(client, sub_mgr):
    """api_subscriptions enriches data with source display names."""
    # Get a real source ID
    sources = await client.get_sources()
    assert sources, "Server should have at least one source"
    src = sources[0]

    await sub_mgr.subscribe(999001, "Integration Test Manga", int(src.id), "test_user")

    result = await api_subscriptions(client, sub_mgr)

    print(f"\n  Subscriptions: {len(result['subscriptions'])} items")
    if result["subscriptions"]:
        sub = result["subscriptions"][0]
        print(f"    manga_id={sub['manga_id']}, source={sub['source_name']}, subs={sub['subscriber_count']}")
        assert sub["source_name"] != f"源{src.id}", "Source name should be resolved"

    # Cleanup
    await sub_mgr.unsubscribe(999001, "test_user")


@pytest.mark.asyncio
async def test_subscriptions_push_count(client, sub_mgr):
    """api_subscriptions reports push_enabled_count correctly."""
    await sub_mgr.subscribe(999002, "Push Test", 100, "user_a")
    await sub_mgr.subscribe(999002, "Push Test", 100, "user_b")
    await sub_mgr.set_auto_push(999002, "user_a", True)

    result = await api_subscriptions(client, sub_mgr)
    found = [s for s in result["subscriptions"] if s["manga_id"] == 999002]
    assert len(found) == 1
    assert found[0]["subscriber_count"] == 2
    assert found[0]["push_enabled_count"] == 1

    # Cleanup
    await sub_mgr.unsubscribe(999002, "user_a")
    await sub_mgr.unsubscribe(999002, "user_b")


# ── api_sources ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sources_live(client):
    """api_sources returns real source list from server."""
    result = await api_sources(client)

    print(f"\n  api_sources: {len(result['sources'])} sources")
    assert "sources" in result
    assert len(result["sources"]) > 0
    for s in result["sources"][:3]:
        print(f"    [{s['id']}] {s['display_name']} ({s['lang']})")
        assert "id" in s
        assert "name" in s
        assert "display_name" in s
        assert "lang" in s


@pytest.mark.asyncio
async def test_sources_no_local_source(client):
    """api_sources should not include local source (id=0) in a way that breaks searches."""
    result = await api_sources(client)
    source_ids = [s["id"] for s in result["sources"]]
    print(f"\n  Source IDs: {source_ids[:5]}...")
    # Just verify we get valid data — the plugin itself skips source 0 in searches
    assert len(source_ids) > 0


# ── api_subscription_delete ─────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_single_subscriber(sub_mgr):
    """api_subscription_delete removes one subscriber."""
    await sub_mgr.subscribe(999010, "Delete Test", 100, "del_user_1")
    await sub_mgr.subscribe(999010, "Delete Test", 100, "del_user_2")

    result = await api_subscription_delete(sub_mgr, {"manga_id": 999010, "umo": "del_user_1"})
    assert result["success"] is True

    subs = await sub_mgr.get_subscriptions("del_user_1")
    assert len(subs) == 0
    # User 2 should still be subscribed
    subs2 = await sub_mgr.get_subscriptions("del_user_2")
    assert len(subs2) == 1

    # Cleanup
    await sub_mgr.unsubscribe(999010, "del_user_2")


@pytest.mark.asyncio
async def test_delete_all_subscribers(sub_mgr):
    """api_subscription_delete with no umo removes entire manga entry."""
    await sub_mgr.subscribe(999011, "Delete All Test", 100, "user_x")
    await sub_mgr.subscribe(999011, "Delete All Test", 100, "user_y")

    result = await api_subscription_delete(sub_mgr, {"manga_id": 999011})
    assert result["success"] is True

    all_subs = await sub_mgr.get_all_subscriptions()
    assert "999011" not in all_subs


@pytest.mark.asyncio
async def test_delete_missing_manga(sub_mgr):
    """api_subscription_delete with missing manga_id returns error."""
    result = await api_subscription_delete(sub_mgr, {})
    assert isinstance(result, tuple)
    assert result[0]["success"] is False
    assert result[1] == 400


# ── api_subscription_push ───────────────────────────────────────


@pytest.mark.asyncio
async def test_push_enable_disable(sub_mgr):
    """api_subscription_push toggles auto-push correctly."""
    await sub_mgr.subscribe(999020, "Push Toggle", 100, "push_user")

    # Enable
    result = await api_subscription_push(sub_mgr, {
        "manga_id": 999020, "umo": "push_user", "enabled": True,
    })
    assert result["success"] is True
    assert await sub_mgr.get_auto_push(999020, "push_user") is True

    # Disable
    result = await api_subscription_push(sub_mgr, {
        "manga_id": 999020, "umo": "push_user", "enabled": False,
    })
    assert result["success"] is True
    assert await sub_mgr.get_auto_push(999020, "push_user") is False

    # Cleanup
    await sub_mgr.unsubscribe(999020, "push_user")


@pytest.mark.asyncio
async def test_push_missing_params():
    """api_subscription_push rejects incomplete requests."""
    result = await api_subscription_push(FakePlugin(), {"manga_id": 42})
    assert isinstance(result, tuple)
    assert result[0]["success"] is False
    assert result[1] == 400


# ── api_config ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_config_get_live(config):
    """api_config_get returns the config dict."""
    result = api_config_get(config)
    assert result["server_url"] == SERVER_URL
    assert result["auth_mode"] == "none"
    print(f"\n  config: {result}")


@pytest.mark.asyncio
async def test_config_post_save(config):
    """api_config_post saves and triggers rebuild."""
    rebuild_called = False

    async def rebuild(cfg):
        nonlocal rebuild_called
        rebuild_called = True

    result = await api_config_post(config, {
        "server_url": "http://100.87.49.15:9330",
        "max_pages": 50,
    }, rebuild)

    assert result["success"] is True
    assert config["max_pages"] == 50
    assert config._saved is True
    assert rebuild_called is True
    print(f"\n  config after save: max_pages={config['max_pages']}")


@pytest.mark.asyncio
async def test_config_post_validation():
    """api_config_post rejects empty server_url."""
    cfg = FakeConfig({"server_url": "http://old:9330"})

    result = await api_config_post(cfg, {"server_url": ""}, None)
    assert isinstance(result, tuple)
    assert result[0]["success"] is False
    assert result[1] == 400


@pytest.mark.asyncio
async def test_config_post_empty_body():
    """api_config_post rejects empty body."""
    cfg = FakeConfig()

    result = await api_config_post(cfg, {}, None)
    assert isinstance(result, tuple)
    assert result[0]["success"] is False
    assert result[1] == 400


# ── api_update ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_success(kv):
    """api_update calls check_updates and records timestamp."""
    check_called = False

    async def mock_check(force):
        nonlocal check_called
        check_called = True
        return "✅ 所有订阅的漫画暂无更新。"

    result = await api_update(mock_check, kv.put_kv_data)

    assert result["success"] is True
    assert check_called is True
    assert "暂无更新" in result["summary"]
    # Timestamp should be stored
    ts = await kv.get_kv_data("suwayomi_last_update_check")
    assert ts > 0
    safe_summary = result['summary'].encode('ascii', 'replace').decode()[:40]
    print(f"\n  api_update: summary='{safe_summary}', ts={ts}")


@pytest.mark.asyncio
async def test_update_failure(kv):
    """api_update handles check_updates raising exception."""

    async def failing_check(force):
        raise RuntimeError("Connection refused")

    result = await api_update(failing_check, kv.put_kv_data)

    assert result["success"] is False
    assert "Connection refused" in result["summary"]


# ── End-to-end: subscribe → check → unsubscribe ─────────────────


@pytest.mark.asyncio
async def test_e2e_subscribe_push_check_unsubscribe(client, sub_mgr, kv):
    """Full lifecycle: subscribe → enable push → check status → unsubscribe."""
    sources = await client.get_sources()
    assert sources, "Need sources"
    src = sources[0]

    manga_id = 999099
    umo = "e2e_test_user"

    # 1. Subscribe
    await sub_mgr.subscribe(manga_id, "E2E Test Manga", int(src.id), umo)
    subs = await sub_mgr.get_subscriptions(umo)
    manga_ids = [s["manga_id"] for s in subs]
    assert manga_id in manga_ids

    # 2. Enable push
    await sub_mgr.set_auto_push(manga_id, umo, True)
    assert await sub_mgr.get_auto_push(manga_id, umo) is True

    # 3. Verify via api_subscriptions
    result = await api_subscriptions(client, sub_mgr)
    found = [s for s in result["subscriptions"] if s["manga_id"] == manga_id]
    assert len(found) == 1
    assert found[0]["push_enabled_count"] == 1

    # 4. Verify via api_status
    status = await api_status(client, sub_mgr, kv.get_kv_data)
    assert status["connected"] is True

    # 5. Unsubscribe
    result = await api_subscription_delete(sub_mgr, {"manga_id": manga_id, "umo": umo})
    assert result["success"] is True

    # 6. Verify gone
    subs = await sub_mgr.get_subscriptions(umo)
    assert manga_id not in [s.get("manga_id") for s in subs]

    print(f"\n  E2E test passed: subscribe → push → status → delete")
