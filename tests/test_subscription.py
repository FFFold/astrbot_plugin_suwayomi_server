import pytest
from utils.subscription import SubscriptionManager


class FakeKV:
    def __init__(self):
        self._store: dict = {}

    async def get(self, key, default=None):
        return self._store.get(key, default)

    async def put(self, key, value):
        self._store[key] = value

    async def delete(self, key):
        self._store.pop(key, None)


@pytest.fixture
def kv():
    return FakeKV()


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
