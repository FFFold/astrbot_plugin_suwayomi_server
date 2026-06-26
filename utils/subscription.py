from __future__ import annotations

from typing import Any

KV_KEY = "suwayomi_subscriptions"


class SubscriptionManager:
    def __init__(self, plugin):
        self._plugin = plugin

    async def _load(self) -> dict[str, Any]:
        data = await self._plugin.get_kv_data(KV_KEY, {})
        if not isinstance(data, dict):
            return {}
        return data

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
                "subscribers": [],
            }
        if umo not in data[key]["subscribers"]:
            data[key]["subscribers"].append(umo)
        await self._save(data)

    async def unsubscribe(self, manga_id: int, umo: str):
        data = await self._load()
        key = str(manga_id)
        if key in data:
            subs = data[key]["subscribers"]
            if umo in subs:
                subs.remove(umo)
            if not subs:
                del data[key]
        await self._save(data)

    async def get_subscriptions(self, umo: str) -> list[dict[str, Any]]:
        data = await self._load()
        result = []
        for manga_id, info in data.items():
            if umo in info.get("subscribers", []):
                result.append({
                    "manga_id": int(manga_id),
                    "title": info["title"],
                    "source_id": info.get("source_id", 0),
                    "latest_chapter_id": info.get("latest_chapter_id", 0),
                })
        return result

    async def get_all_subscriptions(self) -> dict[str, Any]:
        return await self._load()

    async def delete_manga(self, manga_id: int):
        """Delete all subscribers for a manga (entire entry)."""
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
        """Update stored title if changed. Returns True if updated."""
        data = await self._load()
        key = str(manga_id)
        if key in data and data[key].get("title") != new_title:
            data[key]["title"] = new_title
            await self._save(data)
            return True
        return False

    async def set_auto_push(self, manga_id: int, umo: str, enabled: bool):
        """Enable or disable auto-push for a umo on a manga."""
        data = await self._load()
        key = str(manga_id)
        if key not in data:
            return
        if "auto_push" not in data[key]:
            data[key]["auto_push"] = {}
        data[key]["auto_push"][umo] = {"enabled": enabled}
        await self._save(data)

    async def get_auto_push(self, manga_id: int, umo: str) -> bool:
        """Check if auto-push is enabled for a umo on a manga."""
        data = await self._load()
        return self.is_auto_push_enabled(data, manga_id, umo)

    @staticmethod
    def is_auto_push_enabled(data: dict[str, Any], manga_id: int, umo: str) -> bool:
        """Check auto-push state from pre-loaded data (no KV read)."""
        key = str(manga_id)
        info = data.get(key, {})
        ap = info.get("auto_push", {})
        entry = ap.get(umo, {})
        return entry.get("enabled", False)

    async def set_auto_push_all(self, umo: str, enabled: bool):
        """Enable or disable auto-push for a umo on ALL subscribed manga."""
        data = await self._load()
        for manga_id, info in data.items():
            if umo in info.get("subscribers", []):
                if "auto_push" not in info:
                    info["auto_push"] = {}
                info["auto_push"][umo] = {"enabled": enabled}
        await self._save(data)
