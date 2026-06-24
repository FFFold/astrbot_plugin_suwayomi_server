# AstrBot Suwayomi-Server Plugin Design Spec

## Overview

An AstrBot plugin that integrates Suwayomi-Server as a manga backend, providing manga search, chapter reading, chapter download, and subscription-based update push notifications to chat users.

Suwayomi-Server management (library curation, extension installation, source configuration) is out of scope — handled by the deployer via Suwayomi WebUI. The plugin is a pure user-facing service layer.

## Architecture

**Pattern**: Command-driven + local polling push (Plan A).

- Users interact via chat commands prefixed with `漫画`
- A background `asyncio` task periodically checks Suwayomi for manga updates
- Subscription state and read markers stored in AstrBot KV storage
- All Suwayomi interaction via a single async GraphQL HTTP client (`aiohttp`)

## Project Structure

```
astrbot_suwayomi_server/
├── main.py                    # Plugin entry point (Star subclass)
├── metadata.yaml              # Plugin metadata
├── _conf_schema.json          # Configuration schema
├── requirements.txt           # aiohttp
├── suwayomi/
│   ├── __init__.py
│   ├── client.py              # Suwayomi GraphQL HTTP client
│   └── models.py              # Data models (Manga, Chapter, Source, SearchResult)
└── utils/
    ├── __init__.py
    └── subscription.py        # Subscription management (KV storage wrapper)
```

## Configuration

Defined in `_conf_schema.json`, loaded as `AstrBotConfig` in `__init__`:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `server_url` | string | `http://localhost:9330` | Suwayomi-Server base URL |
| `auth_mode` | string | `none` | `none` / `basic` / `jwt` |
| `username` | string | `""` | Auth username (for basic/jwt) |
| `password` | string | `""` | Auth password (for basic/jwt) |
| `check_interval` | int | `60` | Update check interval in minutes |
| `max_pages` | int | `30` | Max pages to send per chapter read |
| `send_mode` | string | `image` | `image` (inline images) / `forward` (merged forward, aiocqhttp) |
| `default_source_id` | long | `0` | Default search source ID (0 = search all installed sources) |

## Command Structure

All commands under command group `漫画`:

| Command | Description |
|---------|-------------|
| `漫画搜索 <关键词> [源名]` | Search manga across sources |
| `漫画源` | List all installed sources |
| `漫画订阅 <编号>` | Subscribe to a manga from search results |
| `漫画取消订阅 <漫画ID或名>` | Unsubscribe from a manga |
| `漫画我的订阅` | List current session's subscriptions |
| `漫画更新` | Manually trigger update check |
| `漫画章节 <漫画名或ID>` | List chapters of a manga |
| `漫画阅读 <漫画名或ID> <章节号>` | Read a chapter (send page images) |
| `漫画下载 <漫画名或ID> <章节号>` | Enqueue chapter download |

### Interaction Flow Example

```
User: 漫画搜索 一拳超人
Bot:  🔍 搜索结果（源: MangaDex）:
      [1] 一拳超人 - 连载中 | 200话
      [2] 一拳超人 重制版 - 连载中 | 150话
      回复「漫画订阅 1」订阅

User: 漫画订阅 1
Bot:  ✅ 已订阅「一拳超人」，有新章节时会推送

User: 漫画阅读 一拳超人 198
Bot:  [sends all page images as Comp.Image in one message chain]
```

## Suwayomi Client (`suwayomi/client.py`)

Async GraphQL HTTP client based on `aiohttp`.

### Core Methods

```python
class SuwayomiClient:
    async def query(self, query: str, variables: dict = None) -> dict
    async def get_sources(self) -> list[Source]
    async def search_manga(self, source_id: int, query: str, page: int = 1) -> SearchResult
    async def get_popular(self, source_id: int, page: int = 1) -> SearchResult
    async def get_manga(self, manga_id: int) -> Manga
    async def get_chapters(self, manga_id: int) -> list[Chapter]
    async def fetch_chapter_pages(self, chapter_id: int) -> list[str]
    async def enqueue_download(self, chapter_ids: list[int]) -> None
    async def update_library(self) -> None
    async def get_library_mangas(self) -> list[Manga]
```

### GraphQL Queries Used

- **Search**: `fetchSourceManga` mutation with `type: SEARCH`
- **Manga details**: `manga(id:)` query with fields: id, title, status, chapters { totalCount }
- **Chapter list**: `manga(id:) { chapters { nodes { id, name, chapterNumber, isRead, isDownloaded } } }`
- **Chapter pages**: `fetchChapterPages(input: { chapterId })` mutation returns `pages` (list of relative URL paths)
- **Download**: `enqueueChapterDownloads(input: { ids })` mutation
- **Library update**: `updateLibrary(input: { categories: null })` mutation
- **Sources**: `sources { nodes { id, name, lang, displayName } }` query

### Authentication Handling

- `none`: No auth headers
- `basic`: `Authorization: Basic base64(username:password)`
- `jwt`: Login via `login` mutation to get accessToken/refreshToken. Add `Authorization: Bearer <token>` header. Auto-refresh on 401.

### Image URL Resolution

Chapter page URLs from the API are relative paths like `/api/v1/manga/42/chapter/5/page/0`. The client prepends `server_url` to form full URLs. AstrBot's `Comp.Image.fromURL` fetches the image directly from Suwayomi.

## Subscription Management (`utils/subscription.py`)

### Data Model (KV Storage)

Key: `subscriptions`

Value structure:
```json
{
  "<manga_id>": {
    "title": "一拳超人",
    "source_id": 1234567890,
    "latest_chapter_id": 200,
    "subscribers": ["umo_hash_1", "umo_hash_2"]
  }
}
```

Subscribers identified by `unified_msg_origin` string (unique per chat session).

### Operations

- `subscribe(manga_id, title, source_id, umo)` — add subscriber
- `unsubscribe(manga_id, umo)` — remove subscriber
- `get_subscriptions(umo)` — return all manga subscribed by a session
- `get_all_subscriptions()` — return full subscription dict (for update checker)
- `update_latest_chapter(manga_id, chapter_id)` — update marker

## Update Push System

### Mechanism

- Background `asyncio.create_task` started in `__init__`, cancelled in `terminate`
- Loop: `await asyncio.sleep(check_interval * 60)` → check → push
- Shared `asyncio.Lock` prevents concurrent execution with manual `漫画更新` command

### Check Flow

```
1. Load all subscriptions from KV
2. For each subscribed manga_id:
   a. Call get_manga(manga_id) to get latest chapter info
   b. Compare latest chapter ID with stored latest_chapter_id
   c. If new chapters found → record them, update marker
   d. If manga deleted/unavailable → remove subscription, log warning
3. For each manga with updates, for each subscriber:
   a. Send push message via context.send_message(umo, chain)
4. If called manually (漫画更新), also yield summary to the event
```

### Push Message Format

```
📢 「一拳超人」更新了！
新增章节：#201, #202, #203
发送「漫画阅读 一拳超人 201」开始阅读
```

## Manga Name Resolution

When user provides a manga name instead of ID:

1. Try parsing as integer → direct `manga(id=N)` query
2. Not a number → search by title:
   a. First check user's subscriptions for exact title match
   b. If not found → query: `mangas(condition: { title: { ilike: "%关键词%" } }, first: 10)`
   c. 0 results → "未找到该漫画"
   d. 1 result → use directly
   e. Multiple results → list and ask user to choose by number

### Chapter Number Resolution

Chapter number maps to `chapterNumber: Float` field in ChapterType. Parse user input as float, match against chapter list.

## Chapter Reading

### Flow

1. Resolve manga (by name or ID) + chapter number → get chapter_id
2. Call `fetchChapterPages(chapter_id)` → list of relative page URLs
3. Truncate to `max_pages`
4. Build message chain:
   - `send_mode == "image"`: list of `Comp.Image.fromURL(full_url)` + optional truncation notice
   - `send_mode == "forward"`: `Comp.Node` wrapped forward message (aiocqhttp); fallback to image mode on other platforms
5. Yield `event.chain_result(chain)`

### Error Handling

- Page image load failure → skip page, append "第 N 页加载失败" notice
- Chapter has 0 pages → "该章节无可用页面"

## Chapter Download

1. Resolve manga + chapter → chapter_id
2. Call `enqueueChapterDownloads(ids=[chapter_id])`
3. Reply: "✅ 已将「漫画名 #章节号」加入下载队列"

## Error Handling Strategy

| Scenario | Response |
|----------|----------|
| Suwayomi unreachable | "漫画服务暂时不可用，请稍后重试" |
| GraphQL error | Show `errors[0].message` to user, log full response |
| JWT expired | Auto-refresh token; if fails, prompt reconfigure |
| Search returns 0 results | "未找到相关漫画，请确认关键词或源名" |
| Subscribed manga deleted | Auto-remove subscription, log warning |
| Image fetch failure | Skip page with notice, don't abort chapter |

## Technical Choices

| Component | Choice | Rationale |
|-----------|--------|-----------|
| HTTP client | `aiohttp` | AstrBot recommended async library |
| Data storage | AstrBot KV API | Lightweight, no extra deps |
| Scheduler | `asyncio.create_task` + sleep | Lifecycle-managed within plugin |
| Message components | `Comp.Image.fromURL` | Universal platform support, no local caching |
| GraphQL | Raw HTTP POST with string queries | No graphql-core dependency needed |
