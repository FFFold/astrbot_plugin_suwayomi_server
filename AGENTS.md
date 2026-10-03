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
uv run pytest tests/test_pack.py tests/test_models.py tests/test_client.py tests/test_downloader.py tests/test_list_chapters.py tests/test_cards.py tests/test_card_commands.py tests/test_subscription.py tests/test_web_api.py tests/test_batch_subscribe.py tests/test_push.py tests/test_service.py tests/test_updater.py tests/test_ai_service.py tests/test_ai_tools.py tests/test_live_skip.py tests/test_t2i.py tests/test_config.py tests/test_config_reset.py tests/test_ranking.py tests/test_bangumi.py tests/test_search_ranking.py -v

# Integration tests (requires live Suwayomi-Server)
uv run pytest tests/test_live_api.py tests/test_live_web_api.py -v -s
# Custom server: SUWAYOMI_URL=http://host:4567 uv run pytest tests/test_live_api.py tests/test_live_web_api.py -v -s
# Note: live tests auto-skip (3s probe) when the server is unreachable, so plain `uv run pytest` is always green without a server.

# Integration tests for standalone T2I endpoint (auto-skips when unreachable)
uv run pytest tests/test_live_t2i.py -v -s
# Custom endpoint: T2I_ENDPOINT=http://host:8999 uv run pytest tests/test_live_t2i.py -v -s

# All tests
uv run pytest -v

# Syntax check
python -c "import ast; ast.parse(open('main.py', encoding='utf-8').read()); print('OK')"
```

## Architecture

```
main.py (SuwayomiPlugin — thin dispatch layer)
  ├── suwayomi/client.py (SuwayomiClient - async GraphQL HTTP)
  ├── suwayomi/config.py (grouped config schema + legacy flat migration helpers)
  ├── suwayomi/models.py (Source, Manga, Chapter, SearchResult dataclasses)
  ├── suwayomi/service.py (resolve_manga, resolve_chapter, get_or_fetch_chapters, fmt helpers)
  ├── suwayomi/ranking.py (pure search-result scoring: normalize + 5-tier evidence + stable rank; shared by command/AI/batch paths)
  ├── suwayomi/bangumi.py (bgm.tv alias resolution for search expansion: top-5 subjects + JP-variant retry + probe builder + alias-boost arbiter + mirror fallback chain)
  ├── suwayomi/cards.py (T2I card template, data prep, embed_covers, render_card, CardCache)
  ├── suwayomi/t2i.py (standalone astrbot-t2i-service client for t2i_source=custom)
  ├── suwayomi/ai_service.py (structured, side-effect-free Agent search/chapter/subscription service)
  ├── suwayomi/ai_tools.py (FunctionTool schemas and registration factory)
  ├── suwayomi/updater.py (check_updates, run_update_loop)
  ├── utils/downloader.py (download_one, download_images, download_cover, fetch_pages_local)
  ├── utils/pack.py (pack_zip, pack_cbz, pack_pdf — image packaging)
  ├── utils/pusher.py (push_chapter_images, push_chapter_file, schedule_cleanup)
  ├── utils/subscription.py (SubscriptionManager - AstrBot KV storage)
  ├── web/api.py (WebUI API handlers — standalone functions, dependency-injected)
  └── pages/dashboard/ (WebUI: 仪表盘 + 订阅管理 + 配置)
```

- `main.py`: Plugin entry, all commands under `@filter.command_group("漫画")`, six AstrBot Agent tools, background update loop, WebUI API registration. Thin dispatch layer — all business logic delegated to service/updater/downloader/pusher modules.
  - `suwayomi/client.py`: All Suwayomi interaction via `POST /api/graphql`; supports none/basic/jwt auth. Exposes `auth_headers` property for image download auth.
  - `suwayomi/config.py`: Config is stored grouped (server/cards/reading/pack/push/ai/advanced, matching `_conf_schema.json` and the WebUI settings page). All reads go through `get_config_value()` and writes through `set_config_value()` — both fall back to legacy flat keys. `_conf_schema.json` keeps all legacy flat keys as `invisible: true` so AstrBot Core's config sync never deletes user values; `migrate_legacy_config()` runs in `__init__` on **every load**, stateless and idempotent: non-default legacy values are synced into groups (Core-refilled default placeholders are left untouched, never clobbering grouped config), returns whether a save is needed.
- `suwayomi/cards.py`: T2I 结果卡片渲染（`result_cards_enabled` 配置，默认关闭）。`CARD_TEMPLATE` 为单个 Jinja2 模板（远程 T2I 端点原生渲染）；`build_*` 纯函数准备 tmpldata（用户文本统一 `html.escape`，漫画简介经 `clean_description` 清洗后一并转义）；`embed_covers` 复用 `download_images` 并发下载封面→PIL 压缩→base64 嵌入（失败显示占位块）；`render_card` 用 `asyncio.wait_for` 包裹 `html_render(return_url=False)`（880px 画布 × 1.8 设备像素比输出高清图），异常/超时返回 None 供调用方回退纯文本；`CardCache` 以 sha1(tmpldata) 为键 TTL 缓存，`clear()` 供配置变更时丢弃旧渲染器产物。`main.py` 的 `_result_cards_enabled()` 在渲染失败后进入 5 分钟冷却（`_card_cooldown_until`），期间命令直接回退文本；`_card_render_fn()` 决定渲染器来源（见 `suwayomi/t2i.py`）；WebUI 保存配置后 `_reset_after_config_change()` 清空卡片缓存与冷却（缓存键不含渲染器，冷却会掩盖已修好的端点）。
- `suwayomi/t2i.py`: 独立 T2I 端点客户端（`t2i_source="custom"` 时启用）。`normalize_endpoint()` 镜像 AstrBot 核心 URL 规则（去尾斜杠、补 `/text2img`、容忍粘贴的 `/generate`；非字符串输入安全返回空串，仅精确匹配 `/text2img` 路径段以避免 `/nottext2img` 误判）；`render_custom_template()` POST `{base}/generate`（`{tmpl, tmpldata, options, json:false}`）并把图片字节写入临时文件（按 Content-Type 选 `.jpg`/`.png`），非 200/空响应抛异常；`make_endpoint_renderer()` 返回与 `Star.html_render` 同签名的可调用对象，供 `render_card_cached` 直接注入。留空端点由 `main._card_render_fn()` 回退系统渲染器并打印一次性警告。
- `suwayomi/models.py`: Pure dataclasses with `from_dict()` factory methods
- `suwayomi/service.py`: Business logic — manga/chapter resolution, chapter fetching/caching, text normalization, status emoji mapping. All functions are standalone with dependency-injected parameters (client, sub_mgr, get_kv_data, etc.)
- `suwayomi/ai_service.py`: Structured AI-facing search, chapter lookup, subscribe/unsubscribe, and subscription listing. Returns stable manga/chapter IDs and never sends messages.
- `suwayomi/ai_tools.py`: Explicit JSON Schemas for six tools — `suwayomi_search_manga`, `suwayomi_get_chapters`, `suwayomi_send_chapter`, `suwayomi_subscribe_manga`, `suwayomi_get_subscriptions`, `suwayomi_unsubscribe_manga` — registered through `context.add_llm_tools()`; custom `call()` dispatch keeps event binding stable during initial load and config-driven re-registration.
- `suwayomi/updater.py`: Update engine — `check_updates()` scans all subscriptions for new chapters (parallel, `_UPDATE_CONCURRENCY=5` Semaphore), pushes notifications, triggers auto-push, records `suwayomi_last_update_check` timestamp. `run_update_loop()` is the background task wrapper. Imported by `main.py` with pre-bound push callbacks.
- `utils/downloader.py`: Image download pipeline — `download_one()` with exponential backoff, `download_images()` parallel batch download (accepts `headers` for auth), `download_cover()` downloads a single manga cover to temp dir (used by `/漫画 章节`), `fetch_pages_local()` downloads chapter pages to temp dir (passes `client.auth_headers`).
- `utils/pack.py`: Pack images into ZIP, CBZ, or PDF files; `parse_download_args()` for command arg parsing; shared helpers `sanitize_filename()`, `normalize_pack_format()`, `build_chapter_output_path()`, `pack_images()` used by download/push/AI-send.
- `utils/pusher.py`: Push delivery — `push_chapter_images()` sends images inline or via forward, `push_chapter_file()` sends packaged file. Also exports `schedule_cleanup()` for delayed temp dir cleanup (tracked in `_cleanup_tasks`, cancelled via `cancel_pending_cleanups()` on terminate), `is_aiocqhttp_target()` for platform detection, and `build_image_chain()` — the single shared builder for image/forward message chains (read, auto-push, AI send).
- `utils/subscription.py`: Persists subscriptions via AstrBot's `get_kv_data()`/`put_kv_data()`. All write operations are serialized by an internal `asyncio.Lock` (read-modify-write of the whole dict must not interleave). Also manages per-session push preferences (`set_push_default`/`get_push_default`/`clear_push_default`) stored under the `suwayomi_push_defaults` KV key.
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

11. **Chapter data is lazy-loaded**: `fetchSourceManga` (search) only returns metadata. Chapters must be fetched separately via `fetchChapters` mutation. Use `service.get_or_fetch_chapters()` which handles caching: reads from DB first, fetches from source if stale or empty. Cache duration is controlled by `chapter_cache_hours` config.

12. **AstrBot arg splitting**: AstrBot's command handler splits arguments by spaces, so trailing keywords like `zip`/`pdf`/`cbz` or `--刷新` may be lost. Always parse from `event.message_str` for commands with optional trailing args.

13. **PLUGIN_NAME must match metadata name**: AstrBot's Bridge SDK constructs WebUI API URLs using the plugin's `name` from `metadata.yaml` (e.g. `astrbot_plugin_suwayomi_server`), NOT the directory name on disk (e.g. `astrbot_suwayomi_server`). The `PLUGIN_NAME` constant in `main.py` and `web/api.py` must match the metadata name, or all WebUI API calls will return "未找到该路由".

14. **Sandbox iframe blocks native dialogs**: AstrBot Plugin Pages run in a sandboxed iframe with `allow-scripts allow-forms allow-downloads` (no `allow-modals`). Native `confirm()`, `alert()`, `prompt()` are silently blocked — `confirm()` returns `false` without showing a dialog. Use custom DOM-based modal dialogs instead (see `showConfirm()` in `app.js`).

15. **`LibraryUpdateStatus` has no `state` or `isRunning` field directly**: The `updateLibrary` mutation's `updateStatus` field returns a `LibraryUpdateStatus` type with fields `categoryUpdates`, `jobsInfo`, and `mangaUpdates`. To check if the updater is running, use `updateStatus { jobsInfo { isRunning } }`. Both `{updateStatus{state}}` and `{updateStatus{isRunning}}` will fail with `FieldUndefined` validation errors.

16. **Image downloads must carry auth headers**: When Suwayomi-Server has auth enabled, image downloads via `/api/v1/manga/.../page/...` REST endpoint require authentication. `download_images()` creates a new `aiohttp.ClientSession` — always pass `headers=client.auth_headers` to carry the auth. Use `SuwayomiClient.auth_headers` property (returns Basic or cached JWT token). The `image_fetch_mode="url"` path is **irreparably broken** for authenticated servers because AstrBot Core's HTTP client has no way to inject auth headers.

17. **Card rendering has two T2I sources, one entry point**: All card rendering funnels through `main._render_card_result()` → `main._card_render_fn()`. `t2i_source="system"` (default) returns `self.html_render` (AstrBot Core's `HtmlRenderer`, whose endpoint comes from AstrBot's *global* config); `t2i_source="custom"` returns a standalone renderer from `suwayomi/t2i.py` bound to `t2i_endpoint`. Never call `self.html_render` directly for cards — bypassing `_card_render_fn()` silently ignores the user's choice. `suwayomi/t2i.py` does **not** use AstrBot's `download_image_by_url` (it injects Shiki/`t2i_active_template` logic that only makes sense for the core path); it POSTs the raw template and saves bytes itself.

18. **AstrBot's T2I endpoint is a module-level singleton**: `astrbot/core/__init__.py` builds `html_renderer = HtmlRenderer(astrbot_config.get("t2i_endpoint", ...))` at *import* time from the global config, and `Star.html_render` just forwards to it. Changing the global `t2i_endpoint` in the AstrBot WebUI therefore requires an **AstrBot restart** to take effect (documented in `docs/setup.md`). AstrBot's default is the overseas official endpoint `https://t2i.soulter.top/text2img`, plus a randomly-shuffled pool fetched from `api.soulter.top/astrbot/t2i-endpoints` — the reason the plugin offers a self-hosted `t2i_endpoint`. In contrast, the plugin's own `t2i_source`/`t2i_endpoint` are read per render, so they apply **without** a restart (the WebUI save path resets `_t2i_endpoint_warned`).

## Key Helpers

业务逻辑自 0.4.7 起从插件类迁出为依赖注入式独立函数（`main.py` 仅薄调度）。常用入口（均为模块级函数，非 `self.` 方法）：

- `service.resolve_manga(client, sub_mgr, umo, name_or_id, cmd)` — 按 ID/订阅名/标题模糊解析漫画。返回 `(Manga, None)` 或 `(None, error_msg)`；多结果时返回带 ID 的引导列表
- `service.resolve_chapter(chapters, chapter_num, manga_name_or_id, cmd)` — 按编号或 `ID:xxx` 解析章节（重号时提示用 ID 消歧）
- `service.get_or_fetch_chapters(client, get_kv_data, put_kv_data, config, manga_id, force)` — 章节缓存读取/源拉取；`force=True` 绕过缓存（更新检查恒 force）
- `service.get_chapter_timestamp(...)` / `service.set_chapter_timestamp(...)` — KV 中的章节拉取时间戳
- `service.fmt_chapter_display(ch)` / `service.fmt_chapter_label(ch, num_counts)` — 章节的展示名 / `#num name (ID:xxx)` 标签；内部统一过 `sanitize_for_message` 清洗（源站文本防注入）
- `service.search_best_match(client, config, name, source_filter)` — 批量订阅用：多源搜索 + 源内 `rank_items` 选优
- `service.refresh_truncated_titles(client, mangas)` — 并发刷新源站截断标题（原地替换）
- `ranking.rank_items(query, items, title_of)` — 相关度打分排序（命令/AI/批量共用）
- `downloader.download_images(urls, ...)` / `downloader.fetch_pages_local(client, chapter_id, max_pages, ...)` — 并行下载；文件打包路径统一传 `get_file_delivery_max_pages(config)`（配置 `file_delivery_max_pages`，默认 300）
- `pusher.push_chapter_images(...)` / `pusher.push_chapter_file(...)` — 自动推送（图片/文件）；`build_image_chain` 为阅读、推送、AI 发送共用的消息链构建器
- `main._prepare_chapter_delivery(event, chapter)` / `main._prepare_chapter_file_delivery(event, manga, chapter, fmt)` — 插件方法：构建阅读图片结果 / 打包文件结果（全页下载失败时返回 None 供调用方报错）
- AI 工具按 `(unified_msg_origin, sender_id)` 隔离最近章节候选 10 分钟；发送工具只接受已暴露的 `(manga_id, chapter_id)` 对，per-scope `asyncio.Lock` 防并发发送，失败可重试
- `main._ai_subscribe_manga_tool / _ai_get_subscriptions_tool / _ai_unsubscribe_manga_tool` — AI 订阅管理工具的插件侧 handler（业务在 `ai_service.py`，见架构图）

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
- `requirements.txt`: Runtime deps (currently `aiohttp>=3.9.0`, `img2pdf>=0.5.0`, `opencc-python-reimplemented>=0.1.7`, `pillow>=10.0.0`, and `pydantic>=2.12.5,<3`)
- `pyproject.toml`: Dev deps (pytest, pytest-asyncio), gitignored（不入库——环境搭建用 `uv venv` + `uv pip install -r requirements.txt pytest pytest-asyncio`，勿用 `uv sync`）
- Tests in `tests/` - unit tests are synchronous or use `@pytest.mark.asyncio`; `test_ai_service.py` covers structured Agent search, chapter selection, and subscription management, while `test_ai_tools.py` guards `call()` dispatch across initial load and config re-sync for all six tools; `test_downloader.py` covers image/cover download helpers; `test_list_chapters.py` covers `/漫画 章节` cover logic and error paths; `test_config.py` covers grouped config read/write, legacy flat migration and schema/definition consistency
- `test_live_api.py`: Integration tests for Suwayomi client, auto-skipped when server unreachable. Covers sources/search/chapters/pages, AI search & chapter selection（相关度降序）, 截断标题刷新（`fetchManga` 持久化 + `refresh_truncated_titles`）, Bangumi 别名解析与探针源站命中, 文件打包页数上限, 封面下载, plus the real command main path (`test_download_and_pack_chapter`: fetch pages → download images → pack zip/pdf/cbz; `test_search_command_ranking_and_cache_live`: 搜索命令排序与编号缓存; `test_check_updates_detects_new_chapters_live`: real scan → notify → watermark → last-check timestamp). Manga sources rate-limit consecutive fetches, so search tests retry and skip when throttled (`_search_zh_for_agent` / `_search_zh_candidates`)
- `test_live_web_api.py`: Integration tests for WebUI API handlers, auto-skipped when server unreachable
- Version is in `metadata.yaml`, not `pyproject.toml`

## Documentation Update Checklist

各类变更（版本发布、新命令、新配置、架构变更等）需同步更新的文件清单见 [docs/dev/doc-update-checklist.md](docs/dev/doc-update-checklist.md)。
