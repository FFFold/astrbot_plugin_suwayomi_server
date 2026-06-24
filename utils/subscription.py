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

    async def update_latest_chapter(self, manga_id: int, chapter_id: int):
        data = await self._load()
        key = str(manga_id)
        if key in data:
            data[key]["latest_chapter_id"] = chapter_id
            await self._save(data)
