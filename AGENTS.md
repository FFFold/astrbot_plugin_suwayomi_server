# AGENTS.md

## Quick Reference

**Project**: AstrBot plugin integrating Suwayomi-Server for manga search, reading, chapter packaging/download, and subscription updates.
**Language**: Python 3.12+ | **Package manager**: uv | **Framework**: AstrBot plugin system

## Documentation

- [贡献指南](CONTRIBUTING.md) — 开发环境搭建、开发流程、提交规范、添加新命令
- [开发指南](docs/dev/development.md) — 架构详解、设计决策、数据流
- [Suwayomi API 参考](docs/dev/suwayomi-api.md) — GraphQL API 文档
- [配置教程](docs/setup.md) — Suwayomi-Server 部署和插件配置
- [变更日志](CHANGELOG.md) — 版本更新记录
- [文档更新清单](docs/dev/doc-update-checklist.md) — 各类变更需同步更新的文件列表

## Commands

```bash
# Unit tests (no network needed)
uv run pytest tests/test_pack.py tests/test_models.py tests/test_client.py tests/test_subscription.py tests/test_web_api.py tests/test_batch_subscribe.py tests/test_push.py tests/test_service.py tests/test_ai_service.py tests/test_ai_tools.py -v

# Integration tests (requires live Suwayomi-Server)
uv run pytest tests/test_live_api.py tests/test_live_web_api.py -v -s
# Custom server: SUWAYOMI_URL=http://host:4567 uv run pytest tests/test_live_api.py tests/test_live_web_api.py -v -s

# All tests
uv run pytest -v

# Syntax check
python -c "import ast; ast.parse(open('main.py', encoding='utf-8').read()); print('OK')"
```

## Architecture

```
main.py (SuwayomiPlugin — thin dispatch layer)
  ├── suwayomi/client.py (SuwayomiClient - async GraphQL HTTP)
  ├── suwayomi/models.py (Source, Manga, Chapter, SearchResult dataclasses)
  ├── suwayomi/service.py (resolve_manga, resolve_chapter, get_or_fetch_chapters, fmt helpers)
  ├── suwayomi/ai_service.py (structured, side-effect-free Agent search/chapter/subscription service)
  ├── suwayomi/ai_tools.py (FunctionTool schemas and registration factory)
  ├── suwayomi/updater.py (check_updates, run_update_loop)
  ├── utils/downloader.py (download_one, download_images, fetch_pages_local)
  ├── utils/pack.py (pack_zip, pack_cbz, pack_pdf — image packaging)
  ├── utils/pusher.py (push_chapter_images, push_chapter_file, schedule_cleanup)
  ├── utils/subscription.py (SubscriptionManager - AstrBot KV storage)
  ├── web/api.py (WebUI API handlers — standalone functions, dependency-injected)
  └── pages/dashboard/ (WebUI: 仪表盘 + 订阅管理 + 配置)
```

- `main.py`: Plugin entry, all commands under `@filter.command_group("漫画")`, six AstrBot Agent tools, background update loop, WebUI API registration. Thin dispatch layer — all business logic delegated to service/updater/downloader/pusher modules.
  - `suwayomi/client.py`: All Suwayomi interaction via `POST /api/graphql`; supports none/basic/jwt auth. Exposes `auth_headers` property for image download auth.
- `suwayomi/models.py`: Pure dataclasses with `from_dict()` factory methods
- `suwayomi/service.py`: Business logic — manga/chapter resolution, chapter fetching/caching, text normalization, status emoji mapping. All functions are standalone with dependency-injected parameters (client, sub_mgr, get_kv_data, etc.)
- `suwayomi/ai_service.py`: Structured AI-facing search, chapter lookup, subscribe/unsubscribe, and subscription listing. Returns stable manga/chapter IDs and never sends messages.
- `suwayomi/ai_tools.py`: Explicit JSON Schemas for six tools — `suwayomi_search_manga`, `suwayomi_get_chapters`, `suwayomi_send_chapter`, `suwayomi_subscribe_manga`, `suwayomi_get_subscriptions`, `suwayomi_unsubscribe_manga` — registered through `context.add_llm_tools()`; custom `call()` dispatch keeps event binding stable during initial load and config-driven re-registration.
- `suwayomi/updater.py`: Update engine — `check_updates()` scans all subscriptions for new chapters, pushes notifications, triggers auto-push. `run_update_loop()` is the background task wrapper. Imported by `main.py` with pre-bound push callbacks.
- `utils/downloader.py`: Image download pipeline — `download_one()` with exponential backoff, `download_images()` parallel batch download (accepts `headers` for auth), `fetch_pages_local()` downloads chapter pages to temp dir (passes `client.auth_headers`).
- `utils/pack.py`: Pack images into ZIP, CBZ, or PDF files; `parse_download_args()` for command arg parsing
- `utils/pusher.py`: Push delivery — `push_chapter_images()` sends images inline or via forward, `push_chapter_file()` sends packaged file. Also exports `schedule_cleanup()` for delayed temp dir cleanup (replaces 4 duplicated asyncio tasks) and `is_aiocqhttp_target()` for platform detection.
- `utils/subscription.py`: Persists subscriptions via AstrBot's `get_kv_data()`/`put_kv_data()`. Also manages per-session push preferences (`set_push_default`/`get_push_default`/`clear_push_default`) stored under the `suwayomi_push_defaults` KV key.
- `web/api.py`: 8 API handlers for admin WebUI (status, subscriptions CRUD, config, sources, update); each receives `client`/`sub_mgr`/`config` as params for testability
- `pages/dashboard/`: AstrBot Plugin Pages — single HTML file with 3 tabs (仪表盘/订阅管理/设置), vanilla JS + CSS, communicates via Bridge SDK

## Critical Quirks

1. **Source ID is string, not int**: Suwayomi's `source` field is `LongString` scalar. GraphQL vars must be `$sid:LongString!`, values must be strings like `"524579092615598717"`.

2. **API returns numbers as strings**: JSON fields like `"id": "287"` need explicit `int()`/`float()` conversion in `from_dict()`.

3. **Use `filter` not `condition` for title search**: `condition: {title: "..."}` is exact match only. Use `filter: {title: {includes: "..."}}` for substring search.

4. **`Long` type doesn't exist**: Suwayomi GraphQL rejects `Long` type declarations. Use `LongString`.

5. **Source ID `"0"` crashes searches**: Local source causes NullPointerException. Skip it when iterating sources.

6. **Background task startup (dual path)**: Both `__init__` and `@filter.on_astrbot_loaded()` start the background update loop. `__init__` tries first via `asyncio.get_running_loop()` — if the loop is already running (hot reload), it starts immediately. If not (fresh startup), `on_astrbot_loaded()` serves as the fallback. The `_bg_task is None` guard prevents duplicates. See `_try_start_bg_loop()` and `_start_bg_task()` in `main.py`.

7. **All command args are strings**: AstrBot passes raw strings, not typed values. Explicit `float()`/`int()` conversion required in command handlers. Use `str` type hints with manual conversion.

8. **Duplicate chapter numbers**: Some manga have multiple chapters with same number (e.g., appendices). Plugin detects this and prompts users to use `ID:xxx` syntax (case-insensitive, supports both `:` and `：`) for disambiguation.

9. **QQ forward messages**: Use `Comp.Nodes([node1, node2, ...])` wrapper. Passing `[Node, Node, ...]` directly to `chain_result()` sends each as a separate forward.

10. **Command format**: AstrBot command groups use space separation. User types `/漫画 搜索`, not `/漫画搜索`. All user-facing text must use `「漫画 搜索」` format (with space).

11. **Chapter data is lazy-loaded**: `fetchSourceManga` (search) only returns metadata. Chapters must be fetched separately via `fetchChapters` mutation. Use `_get_or_fetch_chapters()` helper which handles caching: reads from DB first, fetches from source if stale or empty. Cache duration is controlled by `chapter_cache_hours` config.

12. **AstrBot arg splitting**: AstrBot's command handler splits arguments by spaces, so trailing keywords like `zip`/`pdf`/`cbz` or `--刷新` may be lost. Always parse from `event.message_str` for commands with optional trailing args.

13. **PLUGIN_NAME must match metadata name**: AstrBot's Bridge SDK constructs WebUI API URLs using the plugin's `name` from `metadata.yaml` (e.g. `astrbot_plugin_suwayomi_server`), NOT the directory name on disk (e.g. `astrbot_suwayomi_server`). The `PLUGIN_NAME` constant in `main.py` and `web/api.py` must match the metadata name, or all WebUI API calls will return "未找到该路由".

14. **Sandbox iframe blocks native dialogs**: AstrBot Plugin Pages run in a sandboxed iframe with `allow-scripts allow-forms allow-downloads` (no `allow-modals`). Native `confirm()`, `alert()`, `prompt()` are silently blocked — `confirm()` returns `false` without showing a dialog. Use custom DOM-based modal dialogs instead (see `showConfirm()` in `app.js`).

15. **`LibraryUpdateStatus` has no `state` or `isRunning` field directly**: The `updateLibrary` mutation's `updateStatus` field returns a `LibraryUpdateStatus` type with fields `categoryUpdates`, `jobsInfo`, and `mangaUpdates`. To check if the updater is running, use `updateStatus { jobsInfo { isRunning } }`. Both `{updateStatus{state}}` and `{updateStatus{isRunning}}` will fail with `FieldUndefined` validation errors.

16. **Image downloads must carry auth headers**: When Suwayomi-Server has auth enabled, image downloads via `/api/v1/manga/.../page/...` REST endpoint require authentication. `download_images()` creates a new `aiohttp.ClientSession` — always pass `headers=client.auth_headers` to carry the auth. Use `SuwayomiClient.auth_headers` property (returns Basic or cached JWT token). The `image_fetch_mode="url"` path is **irreparably broken** for authenticated servers because AstrBot Core's HTTP client has no way to inject auth headers.

## Key Helper Methods

- `_check_updates(force=False)` — Check all subscriptions for new chapters. `force=True` bypasses chapter cache and syncs title from source. Used by both manual `/漫画 更新` and background update loop (both always force). Pushes notifications to all subscribers.
- `_get_or_fetch_chapters(manga_id, force=False)` — Get chapters from DB, auto-fetch from source if stale or empty. `force=True` bypasses cache. Used by chapter list command (respects cache) and `_check_updates` (always forces).
- `_get_chapter_timestamp(manga_id)` / `_set_chapter_timestamp(manga_id)` — Manage per-manga chapter fetch timestamps in KV storage.
- `_fmt_chapter_label(ch, num_counts)` — Format chapter display: `#num name` or `#num name (ID:xxx)` for duplicates. Shared by chapter list and update notifications.
- `_fmt_chapter_display(ch)` — Return human-readable chapter name for messages. Uses `ch.name` if non-empty, falls back to `第X话`. Used by push, read, download, and updater.
- `_fmt_chapter_num(num)` — Format chapter number as `int | float | "?"`. Still used internally by `fmt_chapter_display` and for command hint numbers.
- `_resolve_manga(event, name_or_id, cmd)` — Resolve manga by ID or fuzzy name. Returns `(Manga, None)` or `(None, error_msg)`. `cmd` is used in disambiguation hints (e.g., "章节", "阅读", "下载").
- `_resolve_chapter(chapters, chapter_num, manga_name_or_id, cmd)` — Resolve chapter by ID or number string. Returns `(Chapter, None)` or `(None, error_msg)`. Shared by read and download.
- `_fetch_pages_local(chapter_id, max_pages)` — Fetch page URLs and download images to temp dir. Returns `(total_pages, page_urls, local_paths)`. Shared by read and download. Passes `client.auth_headers` for authorized servers.
- `_download_images(urls)` — Parallel download with retry. Returns local file paths. Accepts optional `headers` dict for auth.
- `_download_one(session, url, dest)` — Single image download with exponential backoff retry.
- `_push_chapter_images(umo, title, chapter)` — Push chapter as images (reuses read send logic, respects `send_mode` for forward mode). Used by auto-push. Chapter label uses `ch.name` automatically.
- `_push_chapter_file(umo, title, chapter)` — Push chapter as packaged file (reuses download logic). Used by auto-push. Chapter label uses `ch.name` automatically.
- `_search_best_match(name, source_filter)` — Search manga name across sources, return first match. Used by batch subscribe.
- `_prepare_chapter_delivery(event, chapter)` — Build the chapter image result for `/漫画 阅读` and explicitly requested AI image sending. Returns `(result, total_pages, delivered_pages, tmp_dir)`. Returns `None` as result when all images fail to download (e.g. auth misconfiguration), so callers can surface a meaningful error.
- `_prepare_chapter_file_delivery(event, manga, chapter, fmt)` — Download all pages and build the AI Tool's PDF-default file result (PDF/ZIP/CBZ).
- AI tools keep recent chapter candidates isolated by `(unified_msg_origin, sender_id)` for 10 minutes. The send tool only accepts a previously exposed `(manga_id, chapter_id)` pair, defaults to PDF unless the user names another supported format. The `asyncio.Lock` per scope prevents concurrent sends; failed sends can be retried.
- `_ai_subscribe_manga_tool(event, manga_id, confirmed_user_intent, push_enabled=None)` — AI Tool: subscribe manga to current session, optionally set auto-push. `push_enabled=None` inherits session preference (set via `/漫画 推送 开`), `True`/`False` overrides explicitly. Already-subscribed case supports both upgrade and downgrade. Delegates to `subscribe_manga_for_agent()`.
- `_ai_get_subscriptions_tool(event)` — AI Tool: return current session's subscription list with `push_enabled` status. Delegates to `get_subscriptions_for_agent()`.
- `_ai_unsubscribe_manga_tool(event, manga_id, confirmed_user_intent)` — AI Tool: unsubscribe manga from current session, idempotent. Delegates to `unsubscribe_manga_for_agent()`.

## Config Options

完整配置项参考 [README 配置表](README.md#%E9%85%8D%E7%BD%AE)。

## Adding New Commands

1. Add method to `SuwayomiPlugin` class in `main.py`
2. Decorate with `@manga_group.command("命令名")`
3. First param: `event: AstrMessageEvent`
4. Return text: `yield event.plain_result(...)`
5. Return rich media: `yield event.chain_result([...])`
6. For immediate feedback before heavy work: `await event.send(event.plain_result(...))`
7. Docstring = user-facing help text
8. User prompts use `「漫画 命令名」` format (with space)

## File Conventions

- `metadata.yaml`: AstrBot plugin metadata (name, version, platforms)
- `_conf_schema.json`: AstrBot WebUI config form schema
- `requirements.txt`: Runtime deps (currently `aiohttp>=3.9.0`, `img2pdf>=0.5.0`, `opencc-python-reimplemented>=0.1.7`, and `pydantic>=2.12.5`)
- `pyproject.toml`: Dev deps (pytest, pytest-asyncio), gitignored
- Tests in `tests/` - unit tests are synchronous or use `@pytest.mark.asyncio`; `test_ai_service.py` covers structured Agent search, chapter selection, and subscription management, while `test_ai_tools.py` guards `call()` dispatch across initial load and config re-sync for all six tools
- `test_live_api.py`: Integration tests for Suwayomi client, skipped by default, need live server
- `test_live_web_api.py`: Integration tests for WebUI API handlers, skipped by default, need live server
- Version is in `metadata.yaml`, not `pyproject.toml`

## Documentation Update Checklist

各类变更（版本发布、新命令、新配置、架构变更等）需同步更新的文件清单见 [docs/dev/doc-update-checklist.md](docs/dev/doc-update-checklist.md)。
