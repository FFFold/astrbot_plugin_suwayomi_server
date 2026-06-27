"""Tests for WebUI API handlers in web/api.py."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from web.api import (
    api_status,
    api_subscriptions,
    api_subscription_delete,
    api_subscription_push,
    api_config_get,
    api_config_post,
    api_sources,
    api_update,
)


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.get_sources = AsyncMock(return_value=[])
    client.get_library_mangas = AsyncMock(return_value=[])
    client.close = AsyncMock()
    return client


@pytest.fixture
def fake_plugin():
    class FakePlugin:
        def __init__(self):
            self._store = {}

        async def get_kv_data(self, key, default=None):
            return self._store.get(key, default)

        async def put_kv_data(self, key, value):
            self._store[key] = value

    return FakePlugin()


@pytest.fixture
def sub_mgr(fake_plugin):
    from utils.subscription import SubscriptionManager
    return SubscriptionManager(fake_plugin)


# ── api_status ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_status_connected(mock_client, sub_mgr, fake_plugin):
    from suwayomi.models import Source

    mock_client.get_sources = AsyncMock(return_value=[
        Source(id="1", name="src", lang="zh", display_name="源"),
    ])

    result = await api_status(mock_client, sub_mgr, fake_plugin.get_kv_data)
    assert result["connected"] is True
    assert result["source_count"] == 1


@pytest.mark.asyncio
async def test_status_disconnected(mock_client, sub_mgr, fake_plugin):
    mock_client.get_sources = AsyncMock(side_effect=Exception("fail"))

    result = await api_status(mock_client, sub_mgr, fake_plugin.get_kv_data)
    assert result["connected"] is False
    assert result["source_count"] == 0


@pytest.mark.asyncio
async def test_status_counts(mock_client, sub_mgr, fake_plugin):
    from suwayomi.models import Manga

    await sub_mgr.subscribe(1, "A", 10, "u1")
    await sub_mgr.subscribe(1, "A", 10, "u2")
    await sub_mgr.subscribe(2, "B", 20, "u1")

    mock_client.get_library_mangas = AsyncMock(return_value=[
        Manga(id=1, source_id=10, url="", title="A"),
        Manga(id=2, source_id=20, url="", title="B"),
        Manga(id=3, source_id=30, url="", title="C"),
    ])

    result = await api_status(mock_client, sub_mgr, fake_plugin.get_kv_data)
    assert result["library_count"] == 3
    assert result["subscription_count"] == 2
    assert result["subscriber_total"] == 3


# ── api_subscriptions ───────────────────────────────────


@pytest.mark.asyncio
async def test_subscriptions_empty(mock_client, sub_mgr):
    result = await api_subscriptions(mock_client, sub_mgr)
    assert result["subscriptions"] == []


@pytest.mark.asyncio
async def test_subscriptions_with_data(mock_client, sub_mgr):
    from suwayomi.models import Source

    await sub_mgr.subscribe(42, "One Piece", 100, "user1")
    await sub_mgr.subscribe(42, "One Piece", 100, "user2")
    await sub_mgr.set_auto_push(42, "user1", True)

    mock_client.get_sources = AsyncMock(return_value=[
        Source(id="100", name="src", lang="zh", display_name="测试源"),
    ])

    result = await api_subscriptions(mock_client, sub_mgr)
    subs = result["subscriptions"]
    assert len(subs) == 1
    assert subs[0]["manga_id"] == 42
    assert subs[0]["source_name"] == "测试源"
    assert subs[0]["subscriber_count"] == 2
    assert subs[0]["push_enabled_count"] == 1


@pytest.mark.asyncio
async def test_subscriptions_source_fallback(mock_client, sub_mgr):
    """Source name falls back to '源{id}' when source list fails."""
    await sub_mgr.subscribe(1, "Manga", 999, "user1")
    mock_client.get_sources = AsyncMock(side_effect=Exception("fail"))

    result = await api_subscriptions(mock_client, sub_mgr)
    assert result["subscriptions"][0]["source_name"] == "源999"


# ── api_subscription_delete ─────────────────────────────


@pytest.mark.asyncio
async def test_delete_subscription(sub_mgr):
    await sub_mgr.subscribe(42, "OP", 100, "user1")
    result = await api_subscription_delete(sub_mgr, {"manga_id": 42, "umo": "user1"})
    assert result["success"] is True
    subs = await sub_mgr.get_subscriptions("user1")
    assert len(subs) == 0


@pytest.mark.asyncio
async def test_delete_all_subscriptions(sub_mgr):
    await sub_mgr.subscribe(42, "OP", 100, "user1")
    await sub_mgr.subscribe(42, "OP", 100, "user2")
    result = await api_subscription_delete(sub_mgr, {"manga_id": 42})
    assert result["success"] is True
    all_subs = await sub_mgr.get_all_subscriptions()
    assert "42" not in all_subs


@pytest.mark.asyncio
async def test_delete_missing_manga_id():
    result = await api_subscription_delete(MagicMock(), {})
    assert isinstance(result, tuple)
    assert result[0]["success"] is False
    assert result[1] == 400


@pytest.mark.asyncio
async def test_delete_invalid_manga_id():
    result = await api_subscription_delete(MagicMock(), {"manga_id": "abc"})
    assert isinstance(result, tuple)
    assert result[0]["success"] is False
    assert "整数" in result[0]["message"]
    assert result[1] == 400


@pytest.mark.asyncio
async def test_delete_nonexistent_manga(sub_mgr):
    """Deleting a nonexistent manga should not raise."""
    result = await api_subscription_delete(sub_mgr, {"manga_id": 999})
    assert result["success"] is True


# ── api_subscription_push ───────────────────────────────


@pytest.mark.asyncio
async def test_push_toggle(sub_mgr):
    await sub_mgr.subscribe(42, "OP", 100, "user1")
    result = await api_subscription_push(sub_mgr, {
        "manga_id": 42, "umo": "user1", "enabled": True,
    })
    assert result["success"] is True
    assert await sub_mgr.get_auto_push(42, "user1") is True


@pytest.mark.asyncio
async def test_push_disable(sub_mgr):
    await sub_mgr.subscribe(42, "OP", 100, "user1")
    await sub_mgr.set_auto_push(42, "user1", True)
    result = await api_subscription_push(sub_mgr, {
        "manga_id": 42, "umo": "user1", "enabled": False,
    })
    assert result["success"] is True
    assert await sub_mgr.get_auto_push(42, "user1") is False


@pytest.mark.asyncio
async def test_push_missing_params():
    result = await api_subscription_push(MagicMock(), {"manga_id": 42})
    assert isinstance(result, tuple)
    assert result[0]["success"] is False
    assert result[1] == 400


# ── api_config ──────────────────────────────────────────


def test_config_get():
    cfg = {"server_url": "http://localhost:9330", "auth_mode": "none"}
    result = api_config_get(cfg)
    assert result["server_url"] == "http://localhost:9330"
    assert result is not cfg


def test_config_get_masks_password():
    cfg = {"server_url": "http://localhost:9330", "password": "s3cret"}
    result = api_config_get(cfg)
    assert result["password"] == "***"
    assert cfg["password"] == "s3cret"  # original unchanged


class FakeConfig(dict):
    """Dict with save_config method for testing."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.save_config = MagicMock()


@pytest.mark.asyncio
async def test_config_post_save():
    cfg = FakeConfig({"server_url": "http://old:9330"})
    rebuild = AsyncMock()

    result = await api_config_post(cfg, {"server_url": "http://new:9330"}, rebuild)
    assert result["success"] is True
    assert cfg["server_url"] == "http://new:9330"
    cfg.save_config.assert_called_once()
    rebuild.assert_called_once()


@pytest.mark.asyncio
async def test_config_post_empty_url():
    cfg = FakeConfig({"server_url": "http://old:9330"})

    result = await api_config_post(cfg, {"server_url": ""}, AsyncMock())
    assert isinstance(result, tuple)
    assert result[0]["success"] is False
    assert result[1] == 400


@pytest.mark.asyncio
async def test_config_post_empty_body():
    cfg = FakeConfig()

    result = await api_config_post(cfg, {}, AsyncMock())
    assert isinstance(result, tuple)
    assert result[0]["success"] is False
    assert result[1] == 400


@pytest.mark.asyncio
async def test_config_post_skips_masked_password():
    """Password field with '***' from GET should not overwrite real password."""
    cfg = FakeConfig({"server_url": "http://old:9330", "password": "real_pw"})

    result = await api_config_post(cfg, {
        "server_url": "http://new:9330",
        "password": "***",
    }, AsyncMock())
    assert result["success"] is True
    assert cfg["password"] == "real_pw"  # not overwritten


@pytest.mark.asyncio
async def test_config_post_allows_real_password():
    """Explicitly set password (not masked) should be saved."""
    cfg = FakeConfig({"server_url": "http://old:9330", "password": "old_pw"})

    result = await api_config_post(cfg, {
        "server_url": "http://new:9330",
        "password": "new_pw",
    }, AsyncMock())
    assert result["success"] is True
    assert cfg["password"] == "new_pw"


@pytest.mark.asyncio
async def test_config_post_rejects_unknown_keys():
    """Unknown keys should not be written to config."""
    cfg = FakeConfig({"server_url": "http://old:9330"})

    result = await api_config_post(cfg, {
        "server_url": "http://new:9330",
        "evil_key": "bad_value",
        "_internal": 42,
    }, AsyncMock())
    assert result["success"] is True
    assert "evil_key" not in cfg
    assert "_internal" not in cfg


@pytest.mark.asyncio
async def test_config_post_validates_numeric_fields():
    """Numeric fields should be coerced to int with min bounds."""
    cfg = FakeConfig({"server_url": "http://old:9330", "check_interval": 60})

    result = await api_config_post(cfg, {
        "server_url": "http://new:9330",
        "check_interval": "0",  # below min of 1
    }, AsyncMock())
    assert result["success"] is True
    assert cfg["check_interval"] == 1  # clamped to minimum


@pytest.mark.asyncio
async def test_config_post_validates_numeric_string():
    """Numeric string values should be coerced to int."""
    cfg = FakeConfig({"server_url": "http://old:9330"})

    result = await api_config_post(cfg, {
        "server_url": "http://new:9330",
        "max_pages": "50",
    }, AsyncMock())
    assert result["success"] is True
    assert cfg["max_pages"] == 50


def test_config_get_only_returns_allowed_keys():
    """api_config_get should only return whitelisted keys."""
    cfg = {"server_url": "http://localhost:9330", "password": "pw", "internal_key": "secret"}
    result = api_config_get(cfg)
    assert "server_url" in result
    assert "password" in result
    assert "internal_key" not in result


# ── api_sources ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_sources_list(mock_client):
    from suwayomi.models import Source

    mock_client.get_sources = AsyncMock(return_value=[
        Source(id="1", name="a", lang="zh", display_name="A"),
        Source(id="2", name="b", lang="en", display_name="B"),
    ])
    result = await api_sources(mock_client)
    assert len(result["sources"]) == 2
    assert result["sources"][0]["display_name"] == "A"
    assert result["sources"][1]["lang"] == "en"


@pytest.mark.asyncio
async def test_sources_error(mock_client):
    mock_client.get_sources = AsyncMock(side_effect=Exception("fail"))
    result = await api_sources(mock_client)
    assert result["sources"] == []
    assert "error" in result


# ── api_update ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_success(fake_plugin):
    check = AsyncMock(return_value="✅ 无更新")
    result = await api_update(check, fake_plugin.put_kv_data)
    assert result["success"] is True
    assert result["summary"] == "✅ 无更新"
    check.assert_called_once_with(force=True)


@pytest.mark.asyncio
async def test_update_stores_timestamp(fake_plugin):
    check = AsyncMock(return_value="ok")
    await api_update(check, fake_plugin.put_kv_data)
    ts = await fake_plugin.get_kv_data("suwayomi_last_update_check")
    assert ts > 0


@pytest.mark.asyncio
async def test_update_failure(fake_plugin):
    check = AsyncMock(side_effect=Exception("fail"))
    result = await api_update(check, fake_plugin.put_kv_data)
    assert result["success"] is False
    assert "fail" in result["summary"]
