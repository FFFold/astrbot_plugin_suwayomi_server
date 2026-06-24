# Suwayomi-Server AstrBot Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an AstrBot plugin that integrates Suwayomi-Server as a manga backend, providing search, chapter reading, download, and subscription-based update push.

**Architecture:** Command-driven plugin with async GraphQL HTTP client to Suwayomi-Server, background polling task for update detection, AstrBot KV storage for subscription state.

**Tech Stack:** Python 3.10+, aiohttp, AstrBot Plugin API (Star, filter, Comp, KV storage)

**Spec:** `docs/superpowers/specs/2026-06-24-suwayomi-plugin-design.md`

---

## File Map

| File | Responsibility |
|------|----------------|
| `metadata.yaml` | Plugin identity and metadata |
| `requirements.txt` | Python dependencies |
| `_conf_schema.json` | User-facing configuration schema |
| `suwayomi/__init__.py` | Package init, re-exports |
| `suwayomi/models.py` | Data classes: Source, Manga, Chapter, SearchResult |
| `suwayomi/client.py` | Async GraphQL HTTP client to Suwayomi-Server |
| `utils/__init__.py` | Package init |
| `utils/subscription.py` | Subscription CRUD over AstrBot KV storage |
| `main.py` | Plugin class, commands, background update task |
| `tests/test_models.py` | Unit tests for data models |
| `tests/test_client.py` | Unit tests for GraphQL client (mocked HTTP) |
| `tests/test_subscription.py` | Unit tests for subscription logic |

---

### Task 1: Project Scaffolding

**Files:**
- Create: `metadata.yaml`
- Create: `requirements.txt`
- Create: `_conf_schema.json`
- Create: `suwayomi/__init__.py`
- Create: `utils/__init__.py`

- [ ] **Step 1: Create metadata.yaml**

```yaml
name: astrbot_suwayomi_server
author: user
desc: AstrBot plugin for Suwayomi-Server manga service integration
version: "1.0.0"
repo: ""
display_name: Suwayomi 漫画助手
short_desc: 漫画搜索、阅读、订阅更新推送
support_platforms:
  - aiocqhttp
  - telegram
  - qq_official
  - wecom
  - lark
  - dingtalk
  - discord
  - slack
  - kook
```

- [ ] **Step 2: Create requirements.txt**

```
aiohttp>=3.9.0
```

- [ ] **Step 3: Create _conf_schema.json**

```json
{
  "server_url": {
    "description": "Suwayomi-Server 地址",
    "type": "string",
    "default": "http://localhost:9330",
    "hint": "例如 http://192.168.1.100:9330"
  },
  "auth_mode": {
    "description": "认证模式",
    "type": "string",
    "default": "none",
    "options": ["none", "basic", "jwt"],
    "labels": ["无认证", "Basic 认证", "JWT 认证"]
  },
  "username": {
    "description": "认证用户名",
    "type": "string",
    "default": ""
  },
  "password": {
    "description": "认证密码",
    "type": "string",
    "default": ""
  },
  "check_interval": {
    "description": "更新检查间隔（分钟）",
    "type": "int",
    "default": 60,
    "hint": "每隔多久检查一次漫画更新"
  },
  "max_pages": {
    "description": "单次阅读最大发送页数",
    "type": "int",
    "default": 30
  },
  "send_mode": {
    "description": "图片发送模式",
    "type": "string",
    "default": "image",
    "options": ["image", "forward"],
    "labels": ["直接发图", "合并转发"]
  },
  "default_source_id": {
    "description": "默认搜索源 ID",
    "type": "int",
    "default": 0,
    "hint": "0 表示搜索所有已安装源"
  }
}
```

- [ ] **Step 4: Create package init files**

`suwayomi/__init__.py`:
```python
```

`utils/__init__.py`:
```python
```

- [ ] **Step 5: Commit**

```bash
git add metadata.yaml requirements.txt _conf_schema.json suwayomi/__init__.py utils/__init__.py
git commit -m "feat: project scaffolding with metadata, config schema, and package structure"
```

---

### Task 2: Data Models

**Files:**
- Create: `suwayomi/models.py`
- Create: `tests/__init__.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write model tests**

`tests/__init__.py`:
```python
```

`tests/test_models.py`:
```python
from suwayomi.models import Source, Manga, Chapter, SearchResult


def test_source_from_dict():
    data = {"id": 123, "name": "mangadex", "lang": "en", "displayName": "MangaDex", "supportsLatest": True}
    src = Source.from_dict(data)
    assert src.id == 123
    assert src.name == "mangadex"
    assert src.display_name == "MangaDex"
    assert src.lang == "en"
    assert src.supports_latest is True


def test_manga_from_dict():
    data = {
        "id": 42,
        "sourceId": 123,
        "url": "/manga/42",
        "title": "One Piece",
        "status": "ONGOING",
        "thumbnailUrl": "https://example.com/thumb.jpg",
        "inLibrary": True,
        "author": "Oda",
        "artist": "Oda",
        "description": "Pirate manga",
        "genre": ["Action", "Adventure"],
    }
    manga = Manga.from_dict(data)
    assert manga.id == 42
    assert manga.title == "One Piece"
    assert manga.status == "ONGOING"
    assert manga.in_library is True
    assert manga.author == "Oda"
    assert manga.genre == ["Action", "Adventure"]


def test_chapter_from_dict():
    data = {
        "id": 101,
        "url": "/chapter/101",
        "name": "Chapter 1",
        "chapterNumber": 1.0,
        "uploadDate": 1700000000,
        "isRead": False,
        "isDownloaded": True,
        "isBookmarked": False,
        "lastPageRead": 0,
        "sourceOrder": 1,
        "mangaId": 42,
    }
    ch = Chapter.from_dict(data)
    assert ch.id == 101
    assert ch.name == "Chapter 1"
    assert ch.chapter_number == 1.0
    assert ch.is_read is False
    assert ch.is_downloaded is True


def test_search_result_from_dict():
    data = {
        "mangas": [
            {"id": 1, "title": "A", "url": "/a", "sourceId": 10, "status": "ONGOING"},
            {"id": 2, "title": "B", "url": "/b", "sourceId": 10, "status": "COMPLETED"},
        ],
        "hasNextPage": True,
    }
    sr = SearchResult.from_dict(data)
    assert len(sr.mangas) == 2
    assert sr.has_next_page is True
    assert sr.mangas[0].title == "A"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:\Projects\AstrBot\data\plugins\astrbot_suwayomi_server && python -m pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'suwayomi.models'`

- [ ] **Step 3: Implement models**

`suwayomi/models.py`:
```python
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Source:
    id: int
    name: str
    lang: str
    display_name: str
    supports_latest: bool = False

    @classmethod
    def from_dict(cls, d: dict) -> Source:
        return cls(
            id=d["id"],
            name=d["name"],
            lang=d.get("lang", ""),
            display_name=d.get("displayName", d.get("name", "")),
            supports_latest=d.get("supportsLatest", False),
        )


@dataclass
class Manga:
    id: int
    source_id: int
    url: str
    title: str
    status: str = "UNKNOWN"
    thumbnail_url: str | None = None
    in_library: bool = False
    author: str | None = None
    artist: str | None = None
    description: str | None = None
    genre: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> Manga:
        return cls(
            id=d["id"],
            source_id=d.get("sourceId", 0),
            url=d.get("url", ""),
            title=d.get("title", ""),
            status=d.get("status", "UNKNOWN"),
            thumbnail_url=d.get("thumbnailUrl"),
            in_library=d.get("inLibrary", False),
            author=d.get("author"),
            artist=d.get("artist"),
            description=d.get("description"),
            genre=d.get("genre", []) or [],
        )


@dataclass
class Chapter:
    id: int
    url: str
    name: str
    chapter_number: float
    upload_date: int = 0
    is_read: bool = False
    is_downloaded: bool = False
    is_bookmarked: bool = False
    last_page_read: int = 0
    source_order: int = 0
    manga_id: int = 0
    page_count: int = 0

    @classmethod
    def from_dict(cls, d: dict) -> Chapter:
        return cls(
            id=d["id"],
            url=d.get("url", ""),
            name=d.get("name", ""),
            chapter_number=d.get("chapterNumber", 0.0),
            upload_date=d.get("uploadDate", 0),
            is_read=d.get("isRead", False),
            is_downloaded=d.get("isDownloaded", False),
            is_bookmarked=d.get("isBookmarked", False),
            last_page_read=d.get("lastPageRead", 0),
            source_order=d.get("sourceOrder", 0),
            manga_id=d.get("mangaId", 0),
            page_count=d.get("pageCount", 0),
        )


@dataclass
class SearchResult:
    mangas: list[Manga] = field(default_factory=list)
    has_next_page: bool = False

    @classmethod
    def from_dict(cls, d: dict) -> SearchResult:
        mangas = [Manga.from_dict(m) for m in d.get("mangas", [])]
        return cls(mangas=mangas, has_next_page=d.get("hasNextPage", False))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:\Projects\AstrBot\data\plugins\astrbot_suwayomi_server && python -m pytest tests/test_models.py -v`
Expected: all 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add suwayomi/models.py tests/__init__.py tests/test_models.py
git commit -m "feat: data models for Source, Manga, Chapter, SearchResult"
```

---

### Task 3: Suwayomi GraphQL Client

**Files:**
- Create: `suwayomi/client.py`
- Create: `tests/test_client.py`

- [ ] **Step 1: Write client tests**

`tests/test_client.py`:
```python
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from suwayomi.client import SuwayomiClient


@pytest.fixture
def client():
    return SuwayomiClient("http://localhost:9330", "none", "", "")


@pytest.fixture
def auth_client():
    return SuwayomiClient("http://localhost:9330", "basic", "admin", "pass")


def test_client_init_no_auth(client):
    assert client.server_url == "http://localhost:9330"
    assert client.auth_mode == "none"
    assert client._headers == {"Content-Type": "application/json"}


def test_client_init_basic_auth(auth_client):
    assert "Authorization" in auth_client._headers
    assert auth_client._headers["Authorization"].startswith("Basic ")


def test_build_image_url(client):
    url = client.build_image_url("/api/v1/manga/42/chapter/5/page/0")
    assert url == "http://localhost:9330/api/v1/manga/42/chapter/5/page/0"


def test_build_image_url_strips_trailing_slash():
    c = SuwayomiClient("http://localhost:9330/", "none", "", "")
    url = c.build_image_url("/api/v1/manga/1/chapter/1/page/0")
    assert url == "http://localhost:9330/api/v1/manga/1/chapter/1/page/0"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:\Projects\AstrBot\data\plugins\astrbot_suwayomi_server && python -m pytest tests/test_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'suwayomi.client'`

- [ ] **Step 3: Implement client**

`suwayomi/client.py`:
```python
from __future__ import annotations

import base64
from typing import Any

import aiohttp

from astrbot.api import logger

from .models import Chapter, Manga, SearchResult, Source


class SuwayomiError(Exception):
    pass


class SuwayomiClient:
    def __init__(self, server_url: str, auth_mode: str, username: str, password: str):
        self.server_url = server_url.rstrip("/")
        self.auth_mode = auth_mode
        self._session: aiohttp.ClientSession | None = None

        self._headers: dict[str, str] = {"Content-Type": "application/json"}

        if auth_mode == "basic" and username:
            cred = base64.b64encode(f"{username}:{password}".encode()).decode()
            self._headers["Authorization"] = f"Basic {cred}"

        self._jwt_access_token: str | None = None
        self._jwt_refresh_token: str | None = None
        self._username = username
        self._password = password

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    def build_image_url(self, relative_path: str) -> str:
        return f"{self.server_url}{relative_path}"

    async def _ensure_jwt(self):
        if self.auth_mode != "jwt" or self._jwt_access_token:
            return
        result = await self._raw_query(
            'mutation($u:String!,$p:String!){login(input:{username:$u,password:$p}){accessToken refreshToken}}',
            {"u": self._username, "p": self._password},
        )
        login_data = result["login"]
        self._jwt_access_token = login_data["accessToken"]
        self._jwt_refresh_token = login_data["refreshToken"]

    async def _raw_query(self, query: str, variables: dict | None = None) -> dict[str, Any]:
        await self._ensure_jwt()

        headers = dict(self._headers)
        if self._jwt_access_token:
            headers["Authorization"] = f"Bearer {self._jwt_access_token}"

        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        session = await self._get_session()
        url = f"{self.server_url}/api/graphql"

        async with session.post(url, json=payload, headers=headers) as resp:
            if resp.status == 401 and self.auth_mode == "jwt" and self._jwt_refresh_token:
                await self._refresh_jwt()
                headers["Authorization"] = f"Bearer {self._jwt_access_token}"
                async with session.post(url, json=payload, headers=headers) as retry_resp:
                    data = await retry_resp.json()
            else:
                data = await resp.json()

        if "errors" in data and data["errors"]:
            raise SuwayomiError(data["errors"][0].get("message", "Unknown GraphQL error"))

        return data.get("data", {})

    async def _refresh_jwt(self):
        result = await self._raw_query(
            'mutation($r:String!){refreshToken(input:{refreshToken:$r}){accessToken}}',
            {"r": self._jwt_refresh_token},
        )
        self._jwt_access_token = result["refreshToken"]["accessToken"]

    async def get_sources(self) -> list[Source]:
        data = await self._raw_query(
            'query{sources{nodes{id name lang displayName supportsLatest}}}'
        )
        return [Source.from_dict(s) for s in data["sources"]["nodes"]]

    async def search_manga(self, source_id: int, query: str, page: int = 1) -> SearchResult:
        data = await self._raw_query(
            'mutation($sid:Long!,$q:String!,$p:Int!){fetchSourceManga(input:{source:$sid,type:SEARCH,page:$p,query:$q}){mangas{id title url sourceId status thumbnailUrl inLibrary author artist description genre}hasNextPage}}',
            {"sid": source_id, "q": query, "p": page},
        )
        return SearchResult.from_dict(data["fetchSourceManga"])

    async def get_popular(self, source_id: int, page: int = 1) -> SearchResult:
        data = await self._raw_query(
            'mutation($sid:Long!,$p:Int!){fetchSourceManga(input:{source:$sid,type:POPULAR,page:$p}){mangas{id title url sourceId status thumbnailUrl inLibrary author artist description genre}hasNextPage}}',
            {"sid": source_id, "p": page},
        )
        return SearchResult.from_dict(data["fetchSourceManga"])

    async def get_manga(self, manga_id: int) -> Manga:
        data = await self._raw_query(
            'query($id:Int!){manga(id:$id){id title url sourceId status thumbnailUrl inLibrary author artist description genre chapters{totalCount}}}',
            {"id": manga_id},
        )
        return Manga.from_dict(data["manga"])

    async def get_chapters(self, manga_id: int) -> list[Chapter]:
        data = await self._raw_query(
            'query($id:Int!){manga(id:$id){chapters{nodes{id url name chapterNumber uploadDate isRead isDownloaded isBookmarked lastPageRead sourceOrder mangaId pageCount}}}}',
            {"id": manga_id},
        )
        return [Chapter.from_dict(c) for c in data["manga"]["chapters"]["nodes"]]

    async def fetch_chapter_pages(self, chapter_id: int) -> list[str]:
        data = await self._raw_query(
            'mutation($cid:Int!){fetchChapterPages(input:{chapterId:$cid}){pages}}',
            {"cid": chapter_id},
        )
        return data["fetchChapterPages"]["pages"]

    async def enqueue_download(self, chapter_ids: list[int]) -> None:
        await self._raw_query(
            'mutation($ids:[Int!]!){enqueueChapterDownloads(input:{ids:$ids}){downloadStatus{state}}}',
            {"ids": chapter_ids},
        )

    async def update_library(self) -> None:
        await self._raw_query(
            'mutation{updateLibrary(input:{categories:null}){updateStatus{isRunning}}}'
        )

    async def get_library_mangas(self) -> list[Manga]:
        data = await self._raw_query(
            'query{mangas(condition:{inLibrary:true}){nodes{id title url sourceId status thumbnailUrl inLibrary author artist description genre}}}'
        )
        return [Manga.from_dict(m) for m in data["mangas"]["nodes"]]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:\Projects\AstrBot\data\plugins\astrbot_suwayomi_server && python -m pytest tests/test_client.py -v`
Expected: all 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add suwayomi/client.py tests/test_client.py
git commit -m "feat: Suwayomi GraphQL HTTP client with auth and core methods"
```

---

### Task 4: Subscription Management

**Files:**
- Create: `utils/subscription.py`
- Create: `tests/test_subscription.py`

- [ ] **Step 1: Write subscription tests**

`tests/test_subscription.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:\Projects\AstrBot\data\plugins\astrbot_suwayomi_server && python -m pytest tests/test_subscription.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'utils.subscription'`

- [ ] **Step 3: Implement subscription manager**

`utils/subscription.py`:
```python
from __future__ import annotations

from typing import Any

KV_KEY = "suwayomi_subscriptions"


class SubscriptionManager:
    def __init__(self, kv_store):
        self._kv = kv_store

    async def _load(self) -> dict[str, Any]:
        data = await self._kv.get(KV_KEY, {})
        if not isinstance(data, dict):
            return {}
        return data

    async def _save(self, data: dict[str, Any]):
        await self._kv.put(KV_KEY, data)

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:\Projects\AstrBot\data\plugins\astrbot_suwayomi_server && python -m pytest tests/test_subscription.py -v`
Expected: all 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add utils/subscription.py tests/test_subscription.py
git commit -m "feat: subscription manager with KV storage persistence"
```

---

### Task 5: Main Plugin — Init, Lifecycle, Source Listing

**Files:**
- Create: `main.py`

- [ ] **Step 1: Implement plugin skeleton with init, terminate, and 漫画源 command**

`main.py`:
```python
from __future__ import annotations

import asyncio

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star

from .suwayomi.client import SuwayomiClient, SuwayomiError
from .suwayomi.models import SearchResult
from .utils.subscription import SubscriptionManager

PLUGIN_NAME = "astrbot_suwayomi_server"

STATUS_EMOJI = {
    "ONGOING": "连载中",
    "COMPLETED": "已完结",
    "LICENSED": "已授权",
    "PUBLISHING_FINISHED": "已完结",
    "CANCELLED": "已停刊",
    "ON_HIATUS": "休刊中",
    "UNKNOWN": "未知",
}


class SuwayomiPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.client = SuwayomiClient(
            server_url=config.get("server_url", "http://localhost:9330"),
            auth_mode=config.get("auth_mode", "none"),
            username=config.get("username", ""),
            password=config.get("password", ""),
        )
        self.sub_mgr = SubscriptionManager(self.context.get_kv_storage())
        self._search_cache: dict[str, SearchResult] = {}
        self._update_lock = asyncio.Lock()
        self._bg_task: asyncio.Task | None = None

        interval = config.get("check_interval", 60) * 60
        self._bg_task = asyncio.create_task(self._update_loop(interval))

        logger.info(f"[{PLUGIN_NAME}] 插件已加载，服务器: {config.get('server_url')}")

    async def terminate(self):
        if self._bg_task and not self._bg_task.done():
            self._bg_task.cancel()
        await self.client.close()
        logger.info(f"[{PLUGIN_NAME}] 插件已卸载")

    async def _update_loop(self, interval: float):
        try:
            while True:
                await asyncio.sleep(interval)
                try:
                    await self._check_updates(None)
                except Exception as e:
                    logger.error(f"[{PLUGIN_NAME}] 后台更新检查失败: {e}")
        except asyncio.CancelledError:
            pass

    @filter.command_group("漫画")
    def manga_group(self):
        pass

    @manga_group.command("源")
    async def list_sources(self, event: AstrMessageEvent):
        '''列出所有已安装的漫画源'''
        try:
            sources = await self.client.get_sources()
            if not sources:
                yield event.plain_result("未找到已安装的漫画源，请在 Suwayomi WebUI 中安装扩展。")
                return
            lines = ["📚 已安装的漫画源:"]
            for i, src in enumerate(sources, 1):
                nsfw = " 🔞" if hasattr(src, "nsfw") and src.nsfw else ""
                lines.append(f"  [{i}] {src.display_name} ({src.lang}){nsfw}")
            yield event.plain_result("\n".join(lines))
        except SuwayomiError as e:
            yield event.plain_result(f"获取源列表失败: {e}")
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] list_sources error: {e}")
            yield event.plain_result("漫画服务暂时不可用，请稍后重试。")
```

- [ ] **Step 2: Verify syntax**

Run: `cd D:\Projects\AstrBot\data\plugins\astrbot_suwayomi_server && python -c "import ast; ast.parse(open('main.py').read()); print('OK')"`
Expected: OK

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: plugin skeleton with init, lifecycle, and source listing command"
```

---

### Task 6: Search Command

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add search command to main.py**

Append after the `list_sources` method in `SuwayomiPlugin`:

```python
    @manga_group.command("搜索")
    async def search_manga(self, event: AstrMessageEvent, keyword: str):
        '''搜索漫画。用法: 漫画搜索 <关键词> [源名]'''
        try:
            sources = await self.client.get_sources()
            if not sources:
                yield event.plain_result("未找到已安装的漫画源。")
                return

            # Parse optional source name from keyword
            # If the last word matches a source name, use that source
            source_filter = None
            search_query = keyword
            words = keyword.rsplit(" ", 1)
            if len(words) == 2:
                potential_source = words[1].lower()
                for src in sources:
                    if potential_source in (src.name.lower(), src.display_name.lower(), src.lang.lower()):
                        source_filter = src
                        search_query = words[0]
                        break

            # Default source from config
            default_sid = self.config.get("default_source_id", 0)
            if source_filter:
                target_sources = [source_filter]
            elif default_sid:
                target_sources = [s for s in sources if s.id == default_sid]
                if not target_sources:
                    target_sources = sources[:3]  # fallback to first 3
            else:
                target_sources = sources[:5]  # search first 5 sources

            all_results: list[tuple[str, SearchResult]] = []
            for src in target_sources:
                try:
                    result = await self.client.search_manga(src.id, search_query)
                    all_results.append((src.display_name, result))
                except Exception as e:
                    logger.warning(f"[{PLUGIN_NAME}] 搜索源 {src.name} 失败: {e}")

            if not all_results:
                yield event.plain_result("未找到相关漫画，请确认关键词。")
                return

            # Build result message and cache
            lines = []
            idx = 1
            cache = {}
            for source_name, result in all_results:
                if result.mangas:
                    lines.append(f"\n🔍 搜索结果（源: {source_name}）:")
                    for m in result.mangas:
                        status = STATUS_EMOJI.get(m.status, m.status)
                        lines.append(f"  [{idx}] {m.title} - {status}")
                        cache[str(idx)] = m
                        idx += 1

            if idx == 1:
                yield event.plain_result("未找到相关漫画，请确认关键词。")
                return

            lines.append(f'\n回复「漫画订阅 <编号>」订阅，如「漫画订阅 1」')
            self._search_cache[event.unified_msg_origin] = cache
            yield event.plain_result("\n".join(lines))

        except SuwayomiError as e:
            yield event.plain_result(f"搜索失败: {e}")
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] search error: {e}")
            yield event.plain_result("搜索失败，漫画服务暂时不可用。")
```

- [ ] **Step 2: Verify syntax**

Run: `cd D:\Projects\AstrBot\data\plugins\astrbot_suwayomi_server && python -c "import ast; ast.parse(open('main.py').read()); print('OK')"`
Expected: OK

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: manga search command with multi-source and source filter"
```

---

### Task 7: Subscription Commands

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add subscribe, unsubscribe, my subscriptions commands**

Append after the `search_manga` method:

```python
    @manga_group.command("订阅")
    async def subscribe_manga(self, event: AstrMessageEvent, index: int):
        '''订阅漫画。用法: 漫画订阅 <搜索结果编号>'''
        try:
            umo = event.unified_msg_origin
            cache = self._search_cache.get(umo, {})
            key = str(index)

            manga = None
            if key in cache:
                manga = cache[key]

            if manga is None:
                yield event.plain_result("未找到该编号的漫画，请先使用「漫画搜索」。")
                return

            await self.sub_mgr.subscribe(manga.id, manga.title, manga.source_id, umo)
            yield event.plain_result(f"✅ 已订阅「{manga.title}」，有新章节时会推送。")

        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] subscribe error: {e}")
            yield event.plain_result("订阅失败，请稍后重试。")

    @manga_group.command("取消订阅")
    async def unsubscribe_manga(self, event: AstrMessageEvent, manga_id_or_name: str):
        '''取消订阅。用法: 漫画取消订阅 <漫画ID或名称>'''
        try:
            umo = event.unified_msg_origin
            manga_id = None

            # Try parsing as ID
            try:
                manga_id = int(manga_id_or_name)
            except ValueError:
                # Search by name in subscriptions
                subs = await self.sub_mgr.get_subscriptions(umo)
                for s in subs:
                    if manga_id_or_name in s["title"]:
                        manga_id = s["manga_id"]
                        break

            if manga_id is None:
                yield event.plain_result("未找到匹配的订阅，请使用漫画 ID 或名称。")
                return

            await self.sub_mgr.unsubscribe(manga_id, umo)
            yield event.plain_result(f"✅ 已取消订阅（漫画 ID: {manga_id}）。")

        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] unsubscribe error: {e}")
            yield event.plain_result("取消订阅失败，请稍后重试。")

    @manga_group.command("我的订阅")
    async def my_subscriptions(self, event: AstrMessageEvent):
        '''查看当前会话的订阅列表'''
        try:
            subs = await self.sub_mgr.get_subscriptions(event.unified_msg_origin)
            if not subs:
                yield event.plain_result("📭 你还没有订阅任何漫画。使用「漫画搜索」来查找并订阅。")
                return
            lines = ["📋 你的订阅列表:"]
            for s in subs:
                lines.append(f"  • {s['title']} (ID: {s['manga_id']})")
            yield event.plain_result("\n".join(lines))
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] my_subscriptions error: {e}")
            yield event.plain_result("获取订阅列表失败。")
```

- [ ] **Step 2: Verify syntax**

Run: `cd D:\Projects\AstrBot\data\plugins\astrbot_suwayomi_server && python -c "import ast; ast.parse(open('main.py').read()); print('OK')"`
Expected: OK

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: subscribe, unsubscribe, and my-subscriptions commands"
```

---

### Task 8: Chapter List Command

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add manga name resolution helper and chapter list command**

Add helper method `_resolve_manga` before the command methods, then add `list_chapters`:

```python
    async def _resolve_manga(self, event: AstrMessageEvent, name_or_id: str):
        """Resolve manga by ID or name. Returns (Manga, error_message)."""
        # Try as integer ID
        try:
            manga_id = int(name_or_id)
            manga = await self.client.get_manga(manga_id)
            return manga, None
        except (ValueError, SuwayomiError):
            pass

        # Search by title in subscriptions first
        subs = await self.sub_mgr.get_subscriptions(event.unified_msg_origin)
        for s in subs:
            if name_or_id in s["title"]:
                try:
                    manga = await self.client.get_manga(s["manga_id"])
                    return manga, None
                except SuwayomiError:
                    continue

        # Search in Suwayomi library
        try:
            from .suwayomi.client import SuwayomiClient
            data = await self.client._raw_query(
                'query($t:String!){mangas(condition:{title:{ilike:$t}},first:10){nodes{id title url sourceId status thumbnailUrl inLibrary author artist description genre}}}',
                {"t": f"%{name_or_id}%"},
            )
            nodes = data.get("mangas", {}).get("nodes", [])
            if len(nodes) == 0:
                return None, "未找到该漫画。"
            if len(nodes) == 1:
                from .suwayomi.models import Manga as MangaModel
                return MangaModel.from_dict(nodes[0]), None
            # Multiple results — ask user to be more specific
            lines = ["找到多个结果，请使用 ID 指定:"]
            for n in nodes:
                lines.append(f"  ID {n['id']}: {n['title']}")
            return None, "\n".join(lines)
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] resolve_manga error: {e}")
            return None, "查找漫画失败。"

    @manga_group.command("章节")
    async def list_chapters(self, event: AstrMessageEvent, manga_name_or_id: str):
        '''查看漫画章节列表。用法: 漫画章节 <漫画名或ID>'''
        try:
            manga, err = await self._resolve_manga(event, manga_name_or_id)
            if err:
                yield event.plain_result(err)
                return

            chapters = await self.client.get_chapters(manga.id)
            if not chapters:
                yield event.plain_result(f"「{manga.title}」暂无章节。")
                return

            # Show latest 20 chapters
            display = chapters[:20]
            lines = [f"📖「{manga.title}」章节列表（共 {len(chapters)} 话）:"]
            for ch in display:
                read_mark = "✅" if ch.is_read else "⬜"
                dl_mark = "📥" if ch.is_downloaded else ""
                num = int(ch.chapter_number) if ch.chapter_number == int(ch.chapter_number) else ch.chapter_number
                lines.append(f"  {read_mark} #{num} {ch.name} {dl_mark}")

            if len(chapters) > 20:
                lines.append(f"  ... 还有 {len(chapters) - 20} 话，请到 WebUI 查看")

            yield event.plain_result("\n".join(lines))

        except SuwayomiError as e:
            yield event.plain_result(f"获取章节失败: {e}")
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] list_chapters error: {e}")
            yield event.plain_result("获取章节列表失败。")
```

- [ ] **Step 2: Verify syntax**

Run: `cd D:\Projects\AstrBot\data\plugins\astrbot_suwayomi_server && python -c "import ast; ast.parse(open('main.py').read()); print('OK')"`
Expected: OK

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: manga name resolution helper and chapter list command"
```

---

### Task 9: Chapter Reading Command

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add read_chapter command**

Append after `list_chapters`:

```python
    @manga_group.command("阅读")
    async def read_chapter(self, event: AstrMessageEvent, manga_name_or_id: str, chapter_num: float):
        '''阅读漫画章节。用法: 漫画阅读 <漫画名或ID> <章节号>'''
        try:
            manga, err = await self._resolve_manga(event, manga_name_or_id)
            if err:
                yield event.plain_result(err)
                return

            chapters = await self.client.get_chapters(manga.id)
            target = None
            for ch in chapters:
                if abs(ch.chapter_number - chapter_num) < 0.01:
                    target = ch
                    break

            if target is None:
                yield event.plain_result(f"未找到「{manga.title}」第 {chapter_num} 话。")
                return

            pages = await self.client.fetch_chapter_pages(target.id)
            if not pages:
                yield event.plain_result(f"第 {chapter_num} 话暂无可用页面。")
                return

            max_pages = self.config.get("max_pages", 30)
            send_mode = self.config.get("send_mode", "image")

            import astrbot.api.message_components as Comp

            if send_mode == "forward" and event.get_platform_name() == "aiocqhttp":
                # Build forward message nodes
                nodes = []
                for i, page_path in enumerate(pages[:max_pages]):
                    url = self.client.build_image_url(page_path)
                    nodes.append(Comp.Node(
                        uin=event.get_sender_id(),
                        name=f"第 {chapter_num} 话 - 第 {i+1} 页",
                        content=[Comp.Image.fromURL(url)],
                    ))
                if len(pages) > max_pages:
                    nodes.append(Comp.Node(
                        uin=event.get_sender_id(),
                        name="提示",
                        content=[Comp.Plain(f"... 还有 {len(pages) - max_pages} 页，请到 WebUI 查看")],
                    ))
                yield event.chain_result(nodes)
            else:
                # Direct image mode
                chain = []
                for i, page_path in enumerate(pages[:max_pages]):
                    url = self.client.build_image_url(page_path)
                    chain.append(Comp.Image.fromURL(url))
                if len(pages) > max_pages:
                    chain.append(Comp.Plain(f"... 还有 {len(pages) - max_pages} 页，请到 WebUI 查看"))
                yield event.chain_result(chain)

        except SuwayomiError as e:
            yield event.plain_result(f"阅读失败: {e}")
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] read_chapter error: {e}")
            yield event.plain_result("阅读章节失败。")
```

- [ ] **Step 2: Verify syntax**

Run: `cd D:\Projects\AstrBot\data\plugins\astrbot_suwayomi_server && python -c "import ast; ast.parse(open('main.py').read()); print('OK')"`
Expected: OK

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: chapter reading command with image and forward message modes"
```

---

### Task 10: Download Command

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add download command**

Append after `read_chapter`:

```python
    @manga_group.command("下载")
    async def download_chapter(self, event: AstrMessageEvent, manga_name_or_id: str, chapter_num: float):
        '''下载漫画章节。用法: 漫画下载 <漫画名或ID> <章节号>'''
        try:
            manga, err = await self._resolve_manga(event, manga_name_or_id)
            if err:
                yield event.plain_result(err)
                return

            chapters = await self.client.get_chapters(manga.id)
            target = None
            for ch in chapters:
                if abs(ch.chapter_number - chapter_num) < 0.01:
                    target = ch
                    break

            if target is None:
                yield event.plain_result(f"未找到「{manga.title}」第 {chapter_num} 话。")
                return

            await self.client.enqueue_download([target.id])
            num = int(chapter_num) if chapter_num == int(chapter_num) else chapter_num
            yield event.plain_result(f"✅ 已将「{manga.title} #{num}」加入下载队列，可在 WebUI 查看进度。")

        except SuwayomiError as e:
            yield event.plain_result(f"下载失败: {e}")
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] download error: {e}")
            yield event.plain_result("下载失败。")
```

- [ ] **Step 2: Verify syntax**

Run: `cd D:\Projects\AstrBot\data\plugins\astrbot_suwayomi_server && python -c "import ast; ast.parse(open('main.py').read()); print('OK')"`
Expected: OK

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: chapter download command"
```

---

### Task 11: Update Push System

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add update check and manual trigger command**

Add the `_check_updates` method and `update_cmd` command:

```python
    async def _check_updates(self, event: AstrMessageEvent | None):
        """Check for manga updates and push to subscribers. event=None for background runs."""
        async with self._update_lock:
            all_subs = await self.sub_mgr.get_all_subscriptions()
            if not all_subs:
                if event:
                    await event.send(event.plain_result("📭 没有订阅的漫画，无需检查更新。"))
                return

            updated_mangas: list[tuple[str, list[str], list[str]]] = []  # (title, new_chapters, subscribers)

            for manga_id_str, info in all_subs.items():
                manga_id = int(manga_id_str)
                title = info.get("title", f"ID:{manga_id}")
                latest_stored = info.get("latest_chapter_id", 0)
                subscribers = info.get("subscribers", [])

                if not subscribers:
                    continue

                try:
                    chapters = await self.client.get_chapters(manga_id)
                    if not chapters:
                        continue

                    # Find chapters newer than latest_stored
                    new_chapters = []
                    max_id = latest_stored
                    for ch in chapters:
                        if ch.id > latest_stored:
                            new_chapters.append(ch)
                            if ch.id > max_id:
                                max_id = ch.id

                    if new_chapters:
                        await self.sub_mgr.update_latest_chapter(manga_id, max_id)
                        ch_names = []
                        for ch in new_chapters:
                            num = int(ch.chapter_number) if ch.chapter_number == int(ch.chapter_number) else ch.chapter_number
                            ch_names.append(f"#{num}")
                        updated_mangas.append((title, ch_names, subscribers))

                except Exception as e:
                    logger.warning(f"[{PLUGIN_NAME}] 检查漫画 {title} (ID:{manga_id}) 更新失败: {e}")
                    continue

            if not updated_mangas:
                if event:
                    await event.send(event.plain_result("✅ 所有订阅的漫画暂无更新。"))
                return

            # Push updates to subscribers
            from astrbot.api.event import MessageChain
            import astrbot.api.message_components as Comp

            sent_umo: set[str] = set()
            for title, ch_names, subscribers in updated_mangas:
                msg = f"📢「{title}」更新了！\n新增章节：{', '.join(ch_names)}\n发送「漫画阅读 {title} {ch_names[-1].lstrip('#')}」开始阅读"
                chain = MessageChain().message(msg)
                for umo in subscribers:
                    if umo not in sent_umo:
                        try:
                            await self.context.send_message(umo, chain)
                            sent_umo.add(umo)
                        except Exception as e:
                            logger.warning(f"[{PLUGIN_NAME}] 推送到 {umo} 失败: {e}")

            if event:
                summary_lines = [f"✅ 发现 {len(updated_mangas)} 部漫画更新："]
                for title, ch_names, _ in updated_mangas:
                    summary_lines.append(f"  • {title}: {', '.join(ch_names)}")
                await event.send(event.plain_result("\n".join(summary_lines)))

    @manga_group.command("更新")
    async def manual_update(self, event: AstrMessageEvent):
        '''手动检查漫画更新'''
        try:
            await self._check_updates(event)
        except Exception as e:
            logger.error(f"[{PLUGIN_NAME}] manual_update error: {e}")
            yield event.plain_result("更新检查失败。")
```

- [ ] **Step 2: Verify syntax**

Run: `cd D:\Projects\AstrBot\data\plugins\astrbot_suwayomi_server && python -c "import ast; ast.parse(open('main.py').read()); print('OK')"`
Expected: OK

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: background update push system and manual update command"
```

---

### Task 12: Final Review and Smoke Test

**Files:**
- Review: all files

- [ ] **Step 1: Run all tests**

Run: `cd D:\Projects\AstrBot\data\plugins\astrbot_suwayomi_server && python -m pytest tests/ -v`
Expected: all tests PASS

- [ ] **Step 2: Verify complete main.py compiles**

Run: `cd D:\Projects\AstrBot\data\plugins\astrbot_suwayomi_server && python -c "import ast; ast.parse(open('main.py').read()); print('OK')"`
Expected: OK

- [ ] **Step 3: Verify file structure matches spec**

Run: `cd D:\Projects\AstrBot\data\plugins\astrbot_suwayomi_server && Get-ChildItem -Recurse -File -Exclude __pycache__,.git,.venv | Select-Object FullName`
Expected: matches spec file map

- [ ] **Step 4: Final commit with all cleanups**

```bash
git add -A
git commit -m "feat: complete Suwayomi-Server AstrBot plugin v1.0.0"
```
