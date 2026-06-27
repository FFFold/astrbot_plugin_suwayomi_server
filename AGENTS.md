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
# Unit tests (84 tests, no network needed)
uv run pytest tests/test_pack.py tests/test_models.py tests/test_client.py tests/test_subscription.py tests/test_web_api.py -v

# Integration tests (requires live Suwayomi-Server)
uv run pytest tests/test_live_api.py tests/test_live_web_api.py -v -s
# Custom server: SUWAYOMI_URL=http://host:9330 uv run pytest tests/test_live_api.py tests/test_live_web_api.py -v -s

# All tests
uv run pytest -v

# Syntax check
python -c "import ast; ast.parse(open('main.py', encoding='utf-8').read()); print('OK')"
```

## Architecture

```
main.py (SuwayomiPlugin)
  ├── suwayomi/client.py (SuwayomiClient - async GraphQL HTTP)
  ├── suwayomi/models.py (Source, Manga, Chapter, SearchResult dataclasses)
  ├── utils/pack.py (pack_zip, pack_cbz, pack_pdf — image packaging)
  ├── utils/subscription.py (SubscriptionManager - AstrBot KV storage)
  ├── web/api.py (WebUI API handlers — standalone functions, dependency-injected)
  └── pages/dashboard/ (WebUI: 仪表盘 + 订阅管理 + 配置)
```

- `main.py`: Plugin entry, all 13 commands under `@filter.command_group("漫画")`, background update loop, WebUI API registration
- `suwayomi/client.py`: All Suwayomi interaction via `POST /api/graphql`; supports none/basic/jwt auth
- `suwayomi/models.py`: Pure dataclasses with `from_dict()` factory methods
- `utils/pack.py`: Pack images into ZIP, CBZ, or PDF files; `parse_download_args()` for command arg parsing
- `utils/subscription.py`: Persists subscriptions via AstrBot's `get_kv_data()`/`put_kv_data()`
- `web/api.py`: 8 API handlers for admin WebUI (status, subscriptions CRUD, config, sources, update); each receives `client`/`sub_mgr`/`config` as params for testability
- `pages/dashboard/`: AstrBot Plugin Pages — single HTML file with 3 tabs (仪表盘/订阅管理/设置), vanilla JS + CSS, communicates via Bridge SDK

## Critical Quirks

1. **Source ID is string, not int**: Suwayomi's `source` field is `LongString` scalar. GraphQL vars must be `$sid:LongString!`, values must be strings like `"524579092615598717"`.

2. **API returns numbers as strings**: JSON fields like `"id": "287"` need explicit `int()`/`float()` conversion in `from_dict()`.

3. **Use `filter` not `condition` for title search**: `condition: {title: "..."}` is exact match only. Use `filter: {title: {includes: "..."}}` for substring search.

4. **`Long` type doesn't exist**: Suwayomi GraphQL rejects `Long` type declarations. Use `LongString`.

5. **Source ID `"0"` crashes searches**: Local source causes NullPointerException. Skip it when iterating sources.

6. **Background task startup**: Use `@filter.on_astrbot_loaded()` not `__init__` for `asyncio.create_task()` - event loop may not be running during plugin load.

7. **All command args are strings**: AstrBot passes raw strings, not typed values. Explicit `float()`/`int()` conversion required in command handlers. Use `str` type hints with manual conversion.

8. **Duplicate chapter numbers**: Some manga have multiple chapters with same number (e.g., appendices). Plugin detects this and prompts users to use `ID:xxx` syntax (case-insensitive) for disambiguation.

9. **QQ forward messages**: Use `Comp.Nodes([node1, node2, ...])` wrapper. Passing `[Node, Node, ...]` directly to `chain_result()` sends each as a separate forward.

10. **Command format**: AstrBot command groups use space separation. User types `/漫画 搜索`, not `/漫画搜索`. All user-facing text must use `「漫画 搜索」` format (with space).

11. **Chapter data is lazy-loaded**: `fetchSourceManga` (search) only returns metadata. Chapters must be fetched separately via `fetchChapters` mutation. Use `_get_or_fetch_chapters()` helper which handles caching: reads from DB first, fetches from source if stale or empty. Cache duration is controlled by `chapter_cache_hours` config.

12. **AstrBot arg splitting**: AstrBot's command handler splits arguments by spaces, so trailing keywords like `zip`/`pdf`/`cbz` or `--刷新` may be lost. Always parse from `event.message_str` for commands with optional trailing args.

13. **PLUGIN_NAME must match metadata name**: AstrBot's Bridge SDK constructs WebUI API URLs using the plugin's `name` from `metadata.yaml` (e.g. `astrbot_plugin_suwayomi_server`), NOT the directory name on disk (e.g. `astrbot_suwayomi_server`). The `PLUGIN_NAME` constant in `main.py` and `web/api.py` must match the metadata name, or all WebUI API calls will return "未找到该路由".

14. **Sandbox iframe blocks native dialogs**: AstrBot Plugin Pages run in a sandboxed iframe with `allow-scripts allow-forms allow-downloads` (no `allow-modals`). Native `confirm()`, `alert()`, `prompt()` are silently blocked — `confirm()` returns `false` without showing a dialog. Use custom DOM-based modal dialogs instead (see `showConfirm()` in `app.js`).

## Key Helper Methods

- `_check_updates(force=False)` — Check all subscriptions for new chapters. `force=True` bypasses chapter cache and syncs title from source. Used by both manual `/漫画 更新` and background update loop (both always force). Pushes notifications to all subscribers.
- `_get_or_fetch_chapters(manga_id, force=False)` — Get chapters from DB, auto-fetch from source if stale or empty. `force=True` bypasses cache. Used by chapter list command (respects cache) and `_check_updates` (always forces).
- `_get_chapter_timestamp(manga_id)` / `_set_chapter_timestamp(manga_id)` — Manage per-manga chapter fetch timestamps in KV storage.
- `_fmt_chapter_label(ch, num_counts)` — Format chapter display: `#num name` or `#num name (ID:xxx)` for duplicates. Shared by chapter list and update notifications.
- `_resolve_manga(event, name_or_id, cmd)` — Resolve manga by ID or fuzzy name. Returns `(Manga, None)` or `(None, error_msg)`. `cmd` is used in disambiguation hints (e.g., "章节", "阅读", "下载").
- `_resolve_chapter(chapters, chapter_num, manga_name_or_id, cmd)` — Resolve chapter by ID or number string. Returns `(Chapter, None)` or `(None, error_msg)`. Shared by read and download.
- `_fetch_pages_local(chapter_id, max_pages)` — Fetch page URLs and download images to temp dir. Returns `(total_pages, page_urls, local_paths)`. Shared by read and download.
- `_download_images(urls)` — Parallel download with retry. Returns local file paths.
- `_download_one(session, url, dest)` — Single image download with exponential backoff retry.
- `_push_chapter_images(umo, title, chapter)` — Push chapter as inline images (reuses read logic). Used by auto-push.
- `_push_chapter_file(umo, title, chapter)` — Push chapter as packaged file (reuses download logic). Used by auto-push.

## Config Options

Key non-obvious config values (in `_conf_schema.json`):
- `image_fetch_mode`: `url` (direct reference) or `download` (download to temp first, more reliable)
- `download_concurrency`: Parallel download count (default 6)
- `download_retries`: Retry count per image with exponential backoff (default 3)
- `download_format`: `zip` (ZIP archive), `pdf` (PDF document), or `cbz` (comic book archive). Default `zip`.
- `send_mode`: `image` (direct) or `forward` (QQ merged forward, uses `Comp.Nodes` wrapper)
- `chapter_cache_hours`: Hours before auto-refreshing chapters from source (default 6). `0` = never auto-refresh, `-1` = always refresh
- `auto_push_mode`: `image` (inline images, reuses read logic) or `file` (packaged file, reuses download logic). Default `image`.
- `temp_dir`: Custom temp directory for image downloads. Leave empty for system default. Set to shared directory for Docker environments.

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
- `requirements.txt`: Runtime deps (currently `aiohttp>=3.9.0`, `img2pdf>=0.5.0`, and `opencc-python-reimplemented>=0.1.7`)
- `pyproject.toml`: Dev deps (pytest, pytest-asyncio), gitignored
- Tests in `tests/` - unit tests are synchronous or use `@pytest.mark.asyncio`
- `test_live_api.py`: Integration tests for Suwayomi client, skipped by default, need live server
- `test_live_web_api.py`: Integration tests for WebUI API handlers, skipped by default, need live server
- Version is in `metadata.yaml`, not `pyproject.toml`

## Documentation Update Checklist

各类变更（版本发布、新命令、新配置、架构变更等）需同步更新的文件清单见 [docs/dev/doc-update-checklist.md](docs/dev/doc-update-checklist.md)。
