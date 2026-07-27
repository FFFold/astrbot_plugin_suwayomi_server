from __future__ import annotations

from typing import Any

from astrbot.api import logger

KV_KEY = "suwayomi_subscriptions"


class SubscriptionManager:
    def __init__(self, plugin):
        self._plugin = plugin

    async def _load(self) -> dict[str, Any]:
        data = await self._plugin.get_kv_data(KV_KEY, {})
        if not isinstance(data, dict):
            return {}
        return data

    async def run_migration(self):
        """Check for legacy subscription data and migrate to new format. Safe to call multiple times."""
        data = await self._load()
        if self._migrate(data):
            await self._save(data)

    @staticmethod
    def _migrate(data: dict[str, Any]) -> bool:
        """Migrate old list-format subscribers to dict format. Returns True if any migration occurred."""
        migrated = False
        for key in list(data.keys()):
            info = data[key]
            if not isinstance(info, dict):
                data.pop(key, None)
                migrated = True
                continue
            subs = info.get("subscribers")
            if isinstance(subs, list):
                logger.info(f"[suwayomi_subscription] Migrating subscription data for manga {key}")
                raw_auto_push = info.pop("auto_push", {})
                auto_push = raw_auto_push if isinstance(raw_auto_push, dict) else {}
                info["subscribers"] = {
                    umo: {"push_enabled": auto_push.get(umo, {}).get("enabled", False) if isinstance(auto_push.get(umo), dict) else False}
                    for umo in subs
                }
                migrated = True
        if migrated:
            logger.info("[suwayomi_subscription] Subscription data migration completed")
        return migrated

    async def _save(self, data: dict[str, Any]):
        await self._plugin.put_kv_data(KV_KEY, data)

    async def subscribe(self, manga_id: int, title: str, source_id: int, umo: str):
        data = await self._load()
        key = str(manga_id)
        if key not in data:
            data[key] = {
                "title": title,
                "source_id": source_id,
                "latest_chapter_id": 0,
                "subscribers": {},
            }
        if umo not in data[key]["subscribers"]:
            data[key]["subscribers"][umo] = {"push_enabled": False}
        await self._save(data)

    async def unsubscribe(self, manga_id: int, umo: str):
        data = await self._load()
        key = str(manga_id)
        if key in data:
            data[key]["subscribers"].pop(umo, None)
            if not data[key]["subscribers"]:
                del data[key]
        await self._save(data)

    async def get_subscriptions(self, umo: str) -> list[dict[str, Any]]:
        data = await self._load()
        result = []
        for manga_id, info in data.items():
            if umo in info.get("subscribers", {}):
                result.append({
                    "manga_id": int(manga_id),
                    "title": info["title"],
                    "source_id": info.get("source_id", 0),
                    "latest_chapter_id": info.get("latest_chapter_id", 0),
                    "push_enabled": info.get("subscribers", {}).get(umo, {}).get("push_enabled", False),
                })
        return result

    async def get_all_subscriptions(self) -> dict[str, Any]:
        return await self._load()

    async def delete_manga(self, manga_id: int):
        data = await self._load()
        key = str(manga_id)
        if key in data:
            del data[key]
            await self._save(data)

    async def update_latest_chapter(self, manga_id: int, chapter_id: int):
        data = await self._load()
        key = str(manga_id)
        if key in data:
            data[key]["latest_chapter_id"] = chapter_id
            await self._save(data)

    async def update_title(self, manga_id: int, new_title: str) -> bool:
        data = await self._load()
        key = str(manga_id)
        if key in data and data[key].get("title") != new_title:
            data[key]["title"] = new_title
            await self._save(data)
            return True
        return False

    async def set_auto_push(self, manga_id: int, umo: str, enabled: bool):
        data = await self._load()
        key = str(manga_id)
        if key in data and umo in data[key]["subscribers"]:
            data[key]["subscribers"][umo]["push_enabled"] = enabled
            await self._save(data)

    async def get_auto_push(self, manga_id: int, umo: str) -> bool:
        data = await self._load()
        return self.is_auto_push_enabled(data, manga_id, umo)

    @staticmethod
    def is_auto_push_enabled(data: dict[str, Any], manga_id: int, umo: str) -> bool:
        key = str(manga_id)
        info = data.get(key, {})
        sub = info.get("subscribers", {}).get(umo, {})
        return sub.get("push_enabled", False)

    async def set_auto_push_all(self, umo: str, enabled: bool):
        data = await self._load()
        for info in data.values():
            if umo in info.get("subscribers", {}):
                info["subscribers"][umo]["push_enabled"] = enabled
        await self._save(data)
