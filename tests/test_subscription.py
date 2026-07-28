import pytest
from utils.subscription import SubscriptionManager


class FakePlugin:
    def __init__(self):
        self._store: dict = {}

    async def get_kv_data(self, key, default=None):
        return self._store.get(key, default)

    async def put_kv_data(self, key, value):
        self._store[key] = value

    async def delete_kv_data(self, key):
        self._store.pop(key, None)


@pytest.fixture
def kv():
    return FakePlugin()


@pytest.fixture
def mgr(kv):
    return SubscriptionManager(kv)


@pytest.mark.asyncio
async def test_subscribe_new(mgr):
    await mgr.subscribe(42, "One Piece", 100, "user1")
    subs = await mgr.get_subscriptions("user1")
    assert len(subs) == 1
    assert subs[0]["manga_id"] == 42
    assert subs[0]["title"] == "One Piece"
    assert subs[0]["push_enabled"] is False  # default: no preference set


@pytest.mark.asyncio
async def test_subscribe_inherits_push_preference(mgr):
    await mgr.set_push_default("user1", True)
    await mgr.subscribe(42, "One Piece", 100, "user1")
    subs = await mgr.get_subscriptions("user1")
    assert subs[0]["push_enabled"] is True


@pytest.mark.asyncio
async def test_set_push_default_returns_correct_value(mgr):
    assert await mgr.get_push_default("user1") is False
    await mgr.set_push_default("user1", True)
    assert await mgr.get_push_default("user1") is True


@pytest.mark.asyncio
async def test_clear_push_default(mgr):
    await mgr.set_push_default("user1", True)
    await mgr.clear_push_default("user1")
    assert await mgr.get_push_default("user1") is False


@pytest.mark.asyncio
async def test_push_preference_isolated_by_session(mgr):
    await mgr.set_push_default("user1", True)
    await mgr.subscribe(42, "A", 100, "user1")
    await mgr.subscribe(42, "A", 100, "user2")
    assert await mgr.get_auto_push(42, "user1") is True
    assert await mgr.get_auto_push(42, "user2") is False


@pytest.mark.asyncio
async def test_push_preference_not_retroactive(mgr):
    await mgr.subscribe(42, "One Piece", 100, "user1")
    await mgr.set_push_default("user1", True)
    assert await mgr.get_auto_push(42, "user1") is False  # already subscribed, not affected


@pytest.mark.asyncio
async def test_push_preference_persisted_across_loads(mgr):
    await mgr.set_push_default("user1", True)
    # Simulate re-loading by reading from underlying store
    raw = await mgr._load_prefs()
    assert raw["user1"] is True


@pytest.mark.asyncio
async def test_subscribe_duplicate_user(mgr):
    await mgr.subscribe(42, "One Piece", 100, "user1")
    await mgr.subscribe(42, "One Piece", 100, "user1")
    subs = await mgr.get_subscriptions("user1")
    assert len(subs) == 1


@pytest.mark.asyncio
async def test_subscribe_multiple_users(mgr):
    await mgr.subscribe(42, "One Piece", 100, "user1")
    await mgr.subscribe(42, "One Piece", 100, "user2")
    all_subs = await mgr.get_all_subscriptions()
    assert len(all_subs["42"]["subscribers"]) == 2


@pytest.mark.asyncio
async def test_unsubscribe(mgr):
    await mgr.subscribe(42, "One Piece", 100, "user1")
    await mgr.unsubscribe(42, "user1")
    subs = await mgr.get_subscriptions("user1")
    assert len(subs) == 0


@pytest.mark.asyncio
async def test_get_subscriptions_empty(mgr):
    subs = await mgr.get_subscriptions("nobody")
    assert subs == []


@pytest.mark.asyncio
async def test_update_latest_chapter(mgr):
    await mgr.subscribe(42, "One Piece", 100, "user1")
    await mgr.update_latest_chapter(42, 200)
    all_subs = await mgr.get_all_subscriptions()
    assert all_subs["42"]["latest_chapter_id"] == 200


@pytest.mark.asyncio
async def test_remove_subscription_entry(mgr):
    await mgr.subscribe(42, "One Piece", 100, "user1")
    await mgr.unsubscribe(42, "user1")
    all_subs = await mgr.get_all_subscriptions()
    assert "42" not in all_subs


@pytest.mark.asyncio
async def test_unsubscribe_nonexistent_manga(mgr):
    # Should not raise
    await mgr.unsubscribe(999, "user1")


@pytest.mark.asyncio
async def test_unsubscribe_nonexistent_user(mgr):
    await mgr.subscribe(42, "One Piece", 100, "user1")
    await mgr.unsubscribe(42, "user2")  # user2 not subscribed
    subs = await mgr.get_subscriptions("user1")
    assert len(subs) == 1  # user1 still subscribed


@pytest.mark.asyncio
async def test_update_latest_chapter_nonexistent(mgr):
    # Should not raise
    await mgr.update_latest_chapter(999, 200)


@pytest.mark.asyncio
async def test_subscribe_preserves_other_mangas(mgr):
    await mgr.subscribe(1, "A", 10, "user1")
    await mgr.subscribe(2, "B", 20, "user1")
    subs = await mgr.get_subscriptions("user1")
    assert len(subs) == 2
    titles = {s["title"] for s in subs}
    assert titles == {"A", "B"}


@pytest.mark.asyncio
async def test_set_auto_push(mgr):
    await mgr.subscribe(42, "One Piece", 100, "user1")
    assert await mgr.get_auto_push(42, "user1") is False
    await mgr.set_auto_push(42, "user1", True)
    assert await mgr.get_auto_push(42, "user1") is True


@pytest.mark.asyncio
async def test_set_auto_push_disable(mgr):
    await mgr.subscribe(42, "One Piece", 100, "user1")
    await mgr.set_auto_push(42, "user1", True)
    await mgr.set_auto_push(42, "user1", False)
    assert await mgr.get_auto_push(42, "user1") is False


@pytest.mark.asyncio
async def test_get_auto_push_nonexistent(mgr):
    assert await mgr.get_auto_push(999, "user1") is False


@pytest.mark.asyncio
async def test_is_auto_push_enabled_static(mgr):
    await mgr.subscribe(42, "One Piece", 100, "user1")
    await mgr.subscribe(42, "One Piece", 100, "user2")
    await mgr.set_auto_push(42, "user1", True)
    data = await mgr._load()
    assert SubscriptionManager.is_auto_push_enabled(data, 42, "user1") is True
    assert SubscriptionManager.is_auto_push_enabled(data, 42, "user2") is False


@pytest.mark.asyncio
async def test_set_auto_push_all(mgr):
    await mgr.subscribe(1, "A", 10, "user1")
    await mgr.subscribe(2, "B", 20, "user1")
    await mgr.set_auto_push_all("user1", True)
    assert await mgr.get_auto_push(1, "user1") is True
    assert await mgr.get_auto_push(2, "user1") is True


@pytest.mark.asyncio
async def test_auto_push_backward_compat(mgr):
    """Old list-format subscribers with separate auto_push should migrate correctly."""
    data = {
        "42": {
            "title": "One Piece",
            "source_id": 100,
            "latest_chapter_id": 0,
            "subscribers": ["user1", "user2"],
            "auto_push": {"user1": {"enabled": True}},
        }
    }
    await mgr._save(data)
    await mgr.run_migration()
    loaded = await mgr._load()
    subs = loaded["42"]["subscribers"]
    assert isinstance(subs, dict)
    assert subs["user1"]["push_enabled"] is True
    assert subs["user2"]["push_enabled"] is False
    assert "auto_push" not in loaded["42"]
    assert await mgr.get_auto_push(42, "user1") is True
    assert await mgr.get_auto_push(42, "user2") is False


@pytest.mark.asyncio
async def test_auto_push_backward_compat_no_auto_push(mgr):
    """Legacy data without auto_push field should migrate with all push_enabled=False."""
    data = {
        "42": {
            "title": "Naruto",
            "source_id": 200,
            "latest_chapter_id": 0,
            "subscribers": ["alice", "bob"],
        }
    }
    await mgr._save(data)
    await mgr.run_migration()
    loaded = await mgr._load()
    subs = loaded["42"]["subscribers"]
    assert isinstance(subs, dict)
    assert subs["alice"]["push_enabled"] is False
    assert subs["bob"]["push_enabled"] is False
    assert "auto_push" not in loaded["42"]
    assert await mgr.get_auto_push(42, "alice") is False
    assert await mgr.get_auto_push(42, "bob") is False


@pytest.mark.asyncio
async def test_set_auto_push_ignored_for_missing_manga(mgr):
    """set_auto_push on nonexistent manga should not raise or alter data."""
    await mgr.subscribe(1, "A", 10, "user1")
    await mgr.set_auto_push(999, "user1", True)
    assert await mgr.get_auto_push(1, "user1") is False


@pytest.mark.asyncio
async def test_set_auto_push_ignored_for_non_subscribed_umo(mgr):
    """set_auto_push for a umo not in subscribers should leave data unchanged."""
    await mgr.subscribe(1, "A", 10, "user1")
    await mgr.set_auto_push(1, "stranger", True)
    assert await mgr.get_auto_push(1, "user1") is False
    assert await mgr.get_auto_push(1, "stranger") is False


@pytest.mark.asyncio
async def test_unsubscribe_removes_push_state(mgr):
    """Unsubscribing a user should remove their push state along with subscriber entry."""
    await mgr.subscribe(42, "One Piece", 100, "user1")
    await mgr.set_auto_push(42, "user1", True)
    assert await mgr.get_auto_push(42, "user1") is True
    await mgr.unsubscribe(42, "user1")
    subs = await mgr.get_subscriptions("user1")
    assert len(subs) == 0
    assert await mgr.get_auto_push(42, "user1") is False


@pytest.mark.asyncio
async def test_delete_manga(mgr):
    """delete_manga removes entire manga entry."""
    await mgr.subscribe(42, "One Piece", 100, "user1")
    await mgr.subscribe(42, "One Piece", 100, "user2")
    await mgr.delete_manga(42)
    all_subs = await mgr.get_all_subscriptions()
    assert "42" not in all_subs


@pytest.mark.asyncio
async def test_delete_manga_nonexistent(mgr):
    """delete_manga on nonexistent manga should not raise."""
    await mgr.delete_manga(999)


@pytest.mark.asyncio
async def test_delete_manga_preserves_others(mgr):
    """delete_manga only removes the target manga."""
    await mgr.subscribe(1, "A", 10, "user1")
    await mgr.subscribe(2, "B", 20, "user1")
    await mgr.delete_manga(1)
    subs = await mgr.get_subscriptions("user1")
    assert len(subs) == 1
    assert subs[0]["manga_id"] == 2
