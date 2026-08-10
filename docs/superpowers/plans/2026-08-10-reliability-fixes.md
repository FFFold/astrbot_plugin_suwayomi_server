# 可靠性与重构修复实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复代码评审清单中的 14 项问题：测试可靠性、并发竞态、错误提示、校验、去重重构、性能与 CI。

**Architecture:** 按"高优先级（测试/并发）→ 中优先级（正确性/健壮性）→ 低优先级（重构/性能/CI）"顺序实施。每项修复遵循 TDD：先写失败测试，再最小实现，最后提交。分支：`fix/reliability-and-refactor`。

**Tech Stack:** Python 3.12+, pytest, pytest-asyncio, aiohttp

---

## 文件结构

- Create: `tests/helpers.py` — 集成测试探活助手
- Create: `tests/test_live_skip.py` — 探活助手单测（本地 HTTP 服务器，离线）
- Create: `tests/test_updater.py` — updater 单测（此前无覆盖）
- Create: `tests/test_downloader.py` — downloader 单测（此前无覆盖）
- Create: `.github/workflows/ci.yml` — CI
- Modify: `tests/test_live_api.py`, `tests/test_live_web_api.py` — 无服务器时自动跳过
- Modify: `utils/subscription.py` — 写操作加锁
- Modify: `suwayomi/service.py` — 时间戳锁、章节号解析、投递失败提示、TTL 缓存助手
- Modify: `suwayomi/updater.py` — 并行化 + last_update_check
- Modify: `web/api.py` — 枚举校验
- Modify: `suwayomi/ai_service.py` — 复用解析助手、AiInteractionState 上限
- Modify: `utils/downloader.py` — temp_dir 自动创建
- Modify: `utils/pusher.py` — 清理任务跟踪、共享图片链构建器
- Modify: `utils/pack.py` — sanitize_filename / pack_images / normalize_pack_format / build_chapter_output_path
- Modify: `suwayomi/client.py` — 源列表 TTL 缓存
- Modify: `main.py` — 使用共享助手、terminate 取消清理任务、失败提示
- Modify: `tests/test_service.py`, `tests/test_subscription.py`, `tests/test_client.py`, `tests/test_push.py`, `tests/test_pack.py`, `tests/test_web_api.py`, `tests/test_ai_service.py`
- Modify: `CHANGELOG.md`, `AGENTS.md`

---

### Task 1: Live 集成测试无服务器时自动跳过

**Files:**
- Create: `tests/helpers.py`
- Create: `tests/test_live_skip.py`
- Modify: `tests/test_live_api.py` (模块顶部), `tests/test_live_web_api.py` (模块顶部)

- [ ] **Step 1: 编写失败测试**

`tests/test_live_skip.py`:

```python
"""Tests for the live-server probe helper (offline, uses a local HTTP server)."""
import pytest
import pytest_asyncio
from aiohttp import web

from tests.helpers import server_reachable


@pytest_asyncio.fixture
async def local_graphql_server():
    app = web.Application()

    async def handler(request):
        return web.json_response({"data": {"__typename": "Query"}})

    app.router.add_post("/api/graphql", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    await runner.cleanup()


@pytest.mark.asyncio
async def test_server_reachable_true(local_graphql_server):
    assert await server_reachable(local_graphql_server) is True


@pytest.mark.asyncio
async def test_server_reachable_false_on_unreachable_port():
    assert await server_reachable("http://127.0.0.1:1", timeout=1.0) is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_live_skip.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tests.helpers'`

- [ ] **Step 3: 实现探活助手**

`tests/helpers.py`:

```python
"""Shared helpers for live integration tests."""
from __future__ import annotations

import asyncio

import aiohttp


async def server_reachable(url: str, timeout: float = 3.0) -> bool:
    """Return True if a Suwayomi-Server GraphQL endpoint responds at url."""
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=timeout)
        ) as session:
            async with session.post(
                f"{url.rstrip('/')}/api/graphql",
                json={"query": "{__typename}"},
            ) as resp:
                return resp.status < 500
    except Exception:
        return False


def server_reachable_sync(url: str, timeout: float = 3.0) -> bool:
    """Sync wrapper for module-level pytest.skipif evaluation."""
    try:
        return asyncio.run(server_reachable(url, timeout))
    except RuntimeError:
        return False
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_live_skip.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: 给两个 live 测试文件加 pytestmark**

`tests/test_live_api.py` 模块级（`SERVER_URL` 定义之后）:

```python
import pytest
from tests.helpers import server_reachable_sync

pytestmark = pytest.mark.skipif(
    not server_reachable_sync(SERVER_URL),
    reason="Suwayomi-Server 不可达，跳过集成测试（可用 SUWAYOMI_URL 指定地址）",
)
```

`tests/test_live_web_api.py` 同样添加（该文件头部已 `import pytest`，补 `from tests.helpers import server_reachable_sync`）。

- [ ] **Step 6: 验证全量测试不再因 live 失败**

Run: `uv run pytest -q`
Expected: 无 live 相关失败；本机无服务器时 live 测试显示 `skipped`。

- [ ] **Step 7: Commit**

```bash
git add tests/helpers.py tests/test_live_skip.py tests/test_live_api.py tests/test_live_web_api.py
git commit -m "test: auto-skip live integration tests when server unreachable"
```

---

### Task 2: SubscriptionManager 写操作加锁（防并发丢更新）

**Files:**
- Modify: `utils/subscription.py`
- Modify: `tests/test_subscription.py`

- [ ] **Step 1: 编写失败测试**

`tests/test_subscription.py` 追加（文件头补 `import asyncio`）:

```python
@pytest.mark.asyncio
async def test_concurrent_updates_preserve_both_changes(kv):
    """Concurrent read-modify-write on different mangas must not lose updates."""
    mgr = SubscriptionManager(kv)
    await mgr.subscribe(1, "A", 10, "u1")
    await mgr.subscribe(2, "B", 20, "u1")

    orig_get = kv.get_kv_data
    orig_put = kv.put_kv_data

    async def slow_get(key, default=None):
        await asyncio.sleep(0.02)
        return await orig_get(key, default)

    async def slow_put(key, value):
        await asyncio.sleep(0.02)
        await orig_put(key, value)

    kv.get_kv_data = slow_get
    kv.put_kv_data = slow_put

    await asyncio.gather(
        mgr.set_auto_push(1, "u1", True),
        mgr.update_latest_chapter(2, 999),
    )

    assert await mgr.get_auto_push(1, "u1") is True
    assert (await mgr.get_all_subscriptions())["2"]["latest_chapter_id"] == 999
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_subscription.py::test_concurrent_updates_preserve_both_changes -v`
Expected: FAIL（两个操作基于同一旧快照，后写者覆盖先写者）。

- [ ] **Step 3: 实现加锁**

`utils/subscription.py` `__init__` 中加：

```python
self._write_lock = asyncio.Lock()
```

在以下方法的**整个 load→modify→save 序列**外包 `async with self._write_lock:`（方法体整体缩进）：
`run_migration`, `set_push_default`, `clear_push_default`, `subscribe`, `unsubscribe`, `delete_manga`, `update_latest_chapter`, `update_title`, `set_auto_push`, `set_auto_push_all`。

`_load`/`_save`/`get_*` 不加锁。文件头补 `import asyncio`。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_subscription.py -q`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add utils/subscription.py tests/test_subscription.py
git commit -m "fix: serialize subscription KV read-modify-write with a lock"
```

---

### Task 3: 章节时间戳 KV 读写加锁（防并行覆盖）

**Files:**
- Modify: `suwayomi/service.py`
- Modify: `tests/test_service.py`

- [ ] **Step 1: 编写失败测试**

`tests/test_service.py` 追加（文件头补 `import asyncio`）:

```python
class TestChapterTimestampConcurrency:

    @pytest.mark.asyncio
    async def test_concurrent_set_chapter_timestamp_preserves_all(self):
        from suwayomi.service import set_chapter_timestamp

        store: dict = {}

        async def get_kv(key, default=None):
            await asyncio.sleep(0.02)
            return store.get(key, default)

        async def put_kv(key, value):
            await asyncio.sleep(0.02)
            store[key] = value

        await asyncio.gather(
            set_chapter_timestamp(get_kv, put_kv, 1),
            set_chapter_timestamp(get_kv, put_kv, 2),
        )
        data = store["suwayomi_chapter_timestamps"]
        assert "1" in data and "2" in data
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_service.py::TestChapterTimestampConcurrency -v`
Expected: FAIL（第二个写者覆盖第一个，`"1"` 缺失）。

- [ ] **Step 3: 实现加锁**

`suwayomi/service.py` 模块级加：

```python
_ts_lock = asyncio.Lock()
```

`get_chapter_timestamp` 和 `set_chapter_timestamp` 的函数体改为在 `async with _ts_lock:` 内执行。文件头补 `import asyncio`。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_service.py -q`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add suwayomi/service.py tests/test_service.py
git commit -m "fix: guard chapter timestamp KV read-modify-write with a lock"
```

---

### Task 4: updater 检查更新并行化 + last_update_check 统一写入

**Files:**
- Modify: `suwayomi/updater.py`
- Create: `tests/test_updater.py`

- [ ] **Step 1: 编写失败测试**

`tests/test_updater.py`:

```python
"""Tests for suwayomi/updater.py (no network)."""
import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock

from suwayomi.client import SuwayomiError
from suwayomi.models import Chapter
from suwayomi.updater import LAST_CHECK_KV_KEY, check_updates


class FakePlugin:
    def __init__(self):
        self._store = {}

    async def get_kv_data(self, key, default=None):
        return self._store.get(key, default)

    async def put_kv_data(self, key, value):
        self._store[key] = value


def _subs_entries(manga_ids, latest=0):
    """Build all_subs dict: one subscriber per manga."""
    return {
        str(mid): {
            "title": f"T{mid}",
            "source_id": 1,
            "latest_chapter_id": latest,
            "subscribers": {"u1": {"push_enabled": False}},
        }
        for mid in manga_ids
    }


def _chapters(manga_id, ids):
    return [
        Chapter(id=cid, url="", name=f"第{cid}话", chapter_number=float(cid),
                source_order=cid, upload_date=0, manga_id=manga_id)
        for cid in ids
    ]


class CountingClient:
    def __init__(self, chapters_by_manga, delay=0.05):
        self._chapters = chapters_by_manga
        self.delay = delay
        self.active = 0
        self.max_active = 0
        self.fetch_calls = 0

    async def fetch_chapters(self, manga_id):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.fetch_calls += 1
        await asyncio.sleep(self.delay)
        self.active -= 1
        return self._chapters[manga_id]

    async def get_manga(self, manga_id):
        raise SuwayomiError("skip title sync")

    async def update_library(self):
        return None


def _context():
    ctx = MagicMock()
    ctx.send_message = AsyncMock()
    return ctx


@pytest.mark.asyncio
async def test_check_updates_no_subscriptions_does_not_record_time():
    client = CountingClient({})
    plugin = FakePlugin()
    from utils.subscription import SubscriptionManager
    sub_mgr = SubscriptionManager(plugin)
    summary = await check_updates(
        client, sub_mgr, _context(), {"chapter_cache_hours": -1},
        plugin.get_kv_data, plugin.put_kv_data, asyncio.Lock(),
        AsyncMock(), AsyncMock(),
    )
    assert "没有订阅" in summary
    assert "suwayomi_last_update_check" not in plugin._store


@pytest.mark.asyncio
async def test_check_updates_no_updates_records_last_check():
    client = CountingClient({1: _chapters(1, [1, 2])})
    plugin = FakePlugin()
    from utils.subscription import SubscriptionManager
    sub_mgr = SubscriptionManager(plugin)
    await sub_mgr.subscribe(1, "T1", 1, "u1")
    await sub_mgr.update_latest_chapter(1, 2)
    summary = await check_updates(
        client, sub_mgr, _context(), {"chapter_cache_hours": -1},
        plugin.get_kv_data, plugin.put_kv_data, asyncio.Lock(),
        AsyncMock(), AsyncMock(),
    )
    assert "暂无更新" in summary
    assert plugin._store["suwayomi_last_update_check"] > 0


@pytest.mark.asyncio
async def test_check_updates_processes_parallel():
    client = CountingClient({i: _chapters(i, [i]) for i in range(1, 9)})
    plugin = FakePlugin()
    from utils.subscription import SubscriptionManager
    sub_mgr = SubscriptionManager(plugin)
    for i in range(1, 9):
        await sub_mgr.subscribe(i, f"T{i}", 1, "u1")
    ctx = _context()
    summary = await check_updates(
        client, sub_mgr, ctx, {"chapter_cache_hours": -1},
        plugin.get_kv_data, plugin.put_kv_data, asyncio.Lock(),
        AsyncMock(), AsyncMock(),
    )
    assert client.fetch_calls == 8
    assert client.max_active >= 2
    assert "8 部漫画更新" in summary
    assert ctx.send_message.await_count == 8


@pytest.mark.asyncio
async def test_check_updates_survives_single_manga_failure():
    async def broken_fetch(manga_id):
        if manga_id == 2:
            raise SuwayomiError("source exploded")
        return _chapters(manga_id, [manga_id])

    client = CountingClient({1: [], 2: [], 3: []})
    client.fetch_chapters = broken_fetch
    plugin = FakePlugin()
    from utils.subscription import SubscriptionManager
    sub_mgr = SubscriptionManager(plugin)
    for i in (1, 2, 3):
        await sub_mgr.subscribe(i, f"T{i}", 1, "u1")
    ctx = _context()
    summary = await check_updates(
        client, sub_mgr, ctx, {"chapter_cache_hours": -1},
        plugin.get_kv_data, plugin.put_kv_data, asyncio.Lock(),
        AsyncMock(), AsyncMock(),
    )
    assert "2 部漫画更新" in summary
    assert "T1" in summary and "T3" in summary
```

注：`LAST_CHECK_KV_KEY` 尚未定义，导入会失败——这是预期的 RED。

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_updater.py -v`
Expected: FAIL（`ImportError: cannot import name 'LAST_CHECK_KV_KEY'`）。

- [ ] **Step 3: 实现并行化与时间戳**

`suwayomi/updater.py`:

```python
_UPDATE_CONCURRENCY = 5
LAST_CHECK_KV_KEY = "suwayomi_last_update_check"
```

新增模块级 `_check_one_manga(...)`（把原 for 循环内每部漫画的处理逻辑原样搬入，返回 `tuple | None`；内部 try/except 保持）:

```python
async def _check_one_manga(
    client, sub_mgr, config, get_kv_data, put_kv_data,
    force, cache_hours, manga_id_str, info,
):
    manga_id = int(manga_id_str)
    title = info.get("title", f"ID:{manga_id}")
    latest_stored = info.get("latest_chapter_id", 0)
    subscribers = info.get("subscribers", {})

    if not subscribers:
        return None

    try:
        if force or cache_hours != 0:
            last_ts = await get_chapter_timestamp(get_kv_data, manga_id)
            if (
                force
                or last_ts == 0
                or cache_hours == -1
                or (time.time() - last_ts) > cache_hours * 3600
            ):
                try:
                    manga = await client.get_manga(manga_id)
                    if await sub_mgr.update_title(manga_id, manga.title):
                        logger.info(
                            f"[{_PLUGIN_NAME}] 漫画标题已更新: "
                            f"「{title}」->「{manga.title}」(ID:{manga_id})"
                        )
                        title = manga.title
                except Exception:
                    pass

        chapters = await get_or_fetch_chapters(
            client, get_kv_data, put_kv_data, config, manga_id, force=force
        )
        if not chapters:
            return None

        new_chapters = []
        max_id = latest_stored
        for ch in chapters:
            if ch.id > latest_stored:
                new_chapters.append(ch)
                if ch.id > max_id:
                    max_id = ch.id

        if not new_chapters:
            return None

        await sub_mgr.update_latest_chapter(manga_id, max_id)
        logger.info(
            f"[{_PLUGIN_NAME}] 发现更新: 「{title}」"
            f"新增 {len(new_chapters)} 章节"
        )
        num_count: dict[float, int] = {}
        for ch in chapters:
            num_count[ch.chapter_number] = (
                num_count.get(ch.chapter_number, 0) + 1
            )

        new_chapters.sort(key=lambda ch: ch.source_order)
        ch_info = [fmt_chapter_label(ch, num_count) for ch in new_chapters]
        return (manga_id, title, ch_info, new_chapters, subscribers)
    except Exception as e:
        logger.warning(
            f"[{_PLUGIN_NAME}] 检查漫画 {title} "
            f"(ID:{manga_id}) 更新失败: {e}"
        )
        return None
```

`check_updates` 中替换原 for 循环为：

```python
        sem = asyncio.Semaphore(_UPDATE_CONCURRENCY)

        async def _run(item):
            async with sem:
                return await _check_one_manga(
                    client, sub_mgr, config, get_kv_data, put_kv_data,
                    force, cache_hours, item[0], item[1],
                )

        results = await asyncio.gather(
            *(_run(item) for item in all_subs.items())
        )
        updated_mangas = [r for r in results if r is not None]
```

在 `if not updated_mangas:` 分支 return 之前与最终 summary return 之前各加：

```python
        await put_kv_data(LAST_CHECK_KV_KEY, time.time())
```

（`web/api.py` 的 `api_update` 中原有的时间戳写入保持不变，幂等无害；`main.py` 无需改动。）

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_updater.py tests/test_push.py -q`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add suwayomi/updater.py tests/test_updater.py
git commit -m "fix: parallelize update checks and record last check time in updater"
```

---

### Task 5: WebUI config POST 枚举白名单校验

**Files:**
- Modify: `web/api.py`
- Modify: `tests/test_web_api.py`

- [ ] **Step 1: 编写失败测试**

`tests/test_web_api.py` 追加（先阅读该文件现有 config 测试的 fixture 风格，复用 `mock_config`/rebuild 模式；若无现成 fixture 则定义：`config.get` 返回 dict，`config.save_config` 为 AsyncMock 或同步 MagicMock，rebuild_client 为 AsyncMock）:

```python
@pytest.mark.asyncio
async def test_config_post_rejects_invalid_enum(mock_config, mock_rebuild):
    result = await api_config_post(
        mock_config,
        {"server_url": "http://x:4567", "send_mode": "weird"},
        mock_rebuild,
    )
    assert result["success"] is True
    assert mock_config.get("send_mode") != "weird"


@pytest.mark.asyncio
async def test_config_post_accepts_valid_enum(mock_config, mock_rebuild):
    await api_config_post(
        mock_config,
        {"server_url": "http://x:4567", "send_mode": "forward"},
        mock_rebuild,
    )
    assert mock_config.get("send_mode") == "forward"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_web_api.py -q`
Expected: 新增测试 FAIL（当前无枚举校验，`send_mode` 被直接写入）。

- [ ] **Step 3: 实现枚举校验**

`web/api.py` 加：

```python
ENUM_CONFIG_KEYS = {
    "send_mode": {"image", "forward"},
    "image_fetch_mode": {"url", "download"},
    "auto_push_mode": {"image", "file"},
    "download_format": {"zip", "pdf", "cbz"},
}
```

`api_config_post` 循环内、`BOOLEAN_CONFIG_KEYS` 块之后加：

```python
        if key in ENUM_CONFIG_KEYS:
            if not isinstance(value, str) or value not in ENUM_CONFIG_KEYS[key]:
                continue
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_web_api.py -q`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add web/api.py tests/test_web_api.py
git commit -m "fix: whitelist enum values in WebUI config API"
```

---

### Task 6: 章节解析支持 第X话（命令与 AI 路径统一）

**Files:**
- Modify: `suwayomi/service.py`
- Modify: `suwayomi/ai_service.py`
- Modify: `tests/test_service.py`
- Modify: `tests/test_ai_service.py`

- [ ] **Step 1: 编写失败测试**

`tests/test_service.py` 的 `TestResolveChapter` 追加：

```python
    def test_by_number_with_prefix_suffix(self):
        chapters = [_chapter(100, "第5话", 5)]
        target, err = resolve_chapter(chapters, "第5话", "test", "阅读")
        assert err is None
        assert target is not None and target.id == 100

    def test_by_number_decimal_with_traditional_suffix(self):
        chapters = [_chapter(100, "第38.5话", 38.5)]
        target, err = resolve_chapter(chapters, "第38.5話", "test", "阅读")
        assert err is None
        assert target is not None and target.id == 100
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_service.py::TestResolveChapter -v`
Expected: 两个新增用例 FAIL（`float("第5话")` 抛 ValueError）。

- [ ] **Step 3: 实现共享解析助手**

`suwayomi/service.py`（`import re` 已加；新增）：

```python
_CHAPTER_NUM_SUFFIX_RE = re.compile(r"(?:话|話|章)$")


def parse_chapter_number_text(text: str) -> float | None:
    """Parse user input like '5', '第5话', '第38.5話' into a chapter number."""
    cleaned = str(text or "").strip()
    if cleaned.startswith("第"):
        cleaned = cleaned[1:]
    cleaned = _CHAPTER_NUM_SUFFIX_RE.sub("", cleaned).strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None
```

`resolve_chapter` 中替换：

```python
    try:
        chapter_num_f = float(chapter_num)
    except ValueError:
        return None, "章节号无效。示例: 1, 38.5 或 ID:123"
```

为：

```python
    chapter_num_f = parse_chapter_number_text(chapter_num)
    if chapter_num_f is None:
        return None, "章节号无效。示例: 1, 38.5, 第5话 或 ID:123"
```

- [ ] **Step 4: AI 路径复用同一助手**

`suwayomi/ai_service.py`：从 `.service` 导入 `parse_chapter_number_text`；`_select_chapter_candidates` 中替换手动清洗 + `float(cleaned)` 为：

```python
    number = parse_chapter_number_text(normalized)
    if number is None:
        return None, [], (
            "selector 应为 latest、list、章节号或 ID:数字；"
            f"当前值为 {selector!r}"
        )
```

删除原 `cleaned` 三行。

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/test_service.py tests/test_ai_service.py -q`
Expected: 全部 PASS。

- [ ] **Step 6: Commit**

```bash
git add suwayomi/service.py suwayomi/ai_service.py tests/test_service.py
git commit -m "fix: unify chapter number parsing to support 第X话 in commands"
```

---

### Task 7: temp_dir 不存在时自动创建

**Files:**
- Modify: `utils/downloader.py`
- Create: `tests/test_downloader.py`

- [ ] **Step 1: 编写失败测试**

`tests/test_downloader.py`:

```python
"""Tests for utils/downloader.py (no network)."""
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from utils.downloader import download_images, download_one


@pytest.mark.asyncio
async def test_download_images_creates_missing_custom_tmp(tmp_path, monkeypatch):
    target = tmp_path / "nested" / "tmp"

    async def fake_download_one(session, url, dest, retries=3):
        dest.write_bytes(b"x")
        return True

    monkeypatch.setattr("utils.downloader.download_one", fake_download_one)

    paths, tmp_dir = await download_images(
        ["http://x/1", "http://x/2"],
        custom_tmp=str(target),
        headers={},
    )

    assert target.is_dir()
    assert tmp_dir.parent == target
    assert len(paths) == 2 and all(p for p in paths)


@pytest.mark.asyncio
async def test_download_images_returns_empty_paths_on_failure(tmp_path, monkeypatch):
    async def failing(session, url, dest, retries=3):
        raise OSError("boom")

    monkeypatch.setattr("utils.downloader.download_one", failing)

    paths, tmp_dir = await download_images(
        ["http://x/1", "http://x/2"],
        custom_tmp=str(tmp_path),
    )

    assert paths == ["", ""]


@pytest.mark.asyncio
async def test_download_one_retries_then_succeeds(tmp_path):
    responses = [500, 200]

    async def fake_get(url, timeout=None):
        class Resp:
            status = responses.pop(0)
            headers = {"Content-Type": "image/jpeg"}

            async def read(self):
                return b"data"

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

        return Resp()

    session = AsyncMock()
    session.get = fake_get

    ok = await download_one(session, "http://x/1", tmp_path / "img", retries=2)

    assert ok is True
    assert (tmp_path / "img.jpg").exists()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_downloader.py -v`
Expected: 第一个用例 FAIL（`FileNotFoundError`）。

- [ ] **Step 3: 实现自动创建**

`utils/downloader.py` 的 `download_images` 内、`mkdtemp` 前加：

```python
    if custom_tmp:
        Path(custom_tmp).mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_downloader.py -v`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add utils/downloader.py tests/test_downloader.py
git commit -m "fix: auto-create custom temp_dir for image downloads"
```

---

### Task 8: 清理任务跟踪与 terminate 取消

**Files:**
- Modify: `utils/pusher.py`
- Modify: `main.py`
- Modify: `tests/test_push.py`

- [ ] **Step 1: 编写失败测试**

`tests/test_push.py` 追加（文件头 `import asyncio`，`import utils.pusher as pusher_module`）:

```python
class TestScheduleCleanup:

    @pytest.mark.asyncio
    async def test_cleanup_removes_dir_after_delay(self, tmp_path):
        d = tmp_path / "d"
        d.mkdir()
        pusher_module.schedule_cleanup(d, delay=0.05)
        assert d.exists()
        await asyncio.sleep(0.15)
        assert not d.exists()

    def test_cleanup_skips_none(self):
        assert pusher_module.schedule_cleanup(None) is None

    @pytest.mark.asyncio
    async def test_cancel_pending_cleanups(self, tmp_path):
        d = tmp_path / "d"
        d.mkdir()
        task = pusher_module.schedule_cleanup(d, delay=60)
        assert task is not None
        assert task in pusher_module._cleanup_tasks
        n = pusher_module.cancel_pending_cleanups()
        assert n >= 1
        await asyncio.sleep(0)
        assert len(pusher_module._cleanup_tasks) == 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_push.py::TestScheduleCleanup -v`
Expected: `_cleanup_tasks` 属性不存在 → AttributeError FAIL。

- [ ] **Step 3: 实现任务跟踪**

`utils/pusher.py`：

```python
_cleanup_tasks: set[asyncio.Task] = set()
```

`schedule_cleanup` 改为返回 task 并登记：

```python
def schedule_cleanup(tmp_dir: Path | None, delay: int = 60) -> asyncio.Task | None:
    if tmp_dir is None:
        return None

    async def _cleanup():
        await asyncio.sleep(delay)
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: shutil.rmtree(tmp_dir, ignore_errors=True)
            )
        except Exception:
            pass

    task = asyncio.create_task(_cleanup())
    _cleanup_tasks.add(task)
    task.add_done_callback(_cleanup_tasks.discard)
    return task


def cancel_pending_cleanups() -> int:
    """Cancel pending temp-dir cleanup tasks (called on plugin terminate)."""
    tasks = list(_cleanup_tasks)
    for task in tasks:
        task.cancel()
    return len(tasks)
```

- [ ] **Step 4: main.py terminate 调用**

`main.py`：导入处加 `cancel_pending_cleanups`；`terminate()` 内 `self._bg_task` 取消逻辑之后加：

```python
        cancel_pending_cleanups()
```

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/test_push.py -q`
Expected: 全部 PASS。

- [ ] **Step 6: Commit**

```bash
git add utils/pusher.py main.py tests/test_push.py
git commit -m "fix: track and cancel pending temp cleanup tasks on terminate"
```

---

### Task 9: 提取共享打包助手（去重）

**Files:**
- Modify: `utils/pack.py`
- Modify: `main.py`
- Modify: `utils/pusher.py`
- Modify: `tests/test_pack.py`

- [ ] **Step 1: 编写失败测试**

`tests/test_pack.py` 追加（按该文件现有结构；若已用 tmp_path fixture 则复用）:

```python
def test_sanitize_filename_strips_illegal_chars():
    assert sanitize_filename('a<b>:"c|d\\e/f*g?') == "abcdefg"


def test_sanitize_filename_truncates():
    assert len(sanitize_filename("x" * 100)) == 50


def test_sanitize_filename_empty_fallback():
    assert sanitize_filename("   ") == "untitled"


def test_normalize_pack_format():
    assert normalize_pack_format("pdf") == "pdf"
    assert normalize_pack_format("weird") == "zip"


def test_build_chapter_output_path(tmp_path):
    p = build_chapter_output_path(tmp_path, "a<b", "第1话", "pdf")
    assert p == tmp_path / "ab_第1话.pdf"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_pack.py -v`
Expected: 新增用例 FAIL（`ImportError: cannot import name 'sanitize_filename'`）。

- [ ] **Step 3: 实现助手**

`utils/pack.py` 追加：

```python
def sanitize_filename(name: str, max_len: int = 50) -> str:
    cleaned = "".join(c for c in str(name) if c not in r'<>:"/\|?*').strip()
    return cleaned[:max_len] or "untitled"


def normalize_pack_format(fmt: str) -> str:
    return fmt if fmt in ("pdf", "cbz", "zip") else "zip"


def build_chapter_output_path(directory: Path, title: str, label: str, fmt: str) -> Path:
    return directory / f"{sanitize_filename(title)}_{sanitize_filename(label)}.{fmt}"


def pack_images(image_paths: list[str], output: Path, fmt: str) -> None:
    if fmt == "pdf":
        pack_pdf(image_paths, output)
    elif fmt == "cbz":
        pack_cbz(image_paths, output)
    else:
        pack_zip(image_paths, output)
```

- [ ] **Step 4: 重构三个调用点**

`main.py` `download_chapter` 中替换：

```python
            safe_title = "".join(c for c in manga.title if c not in r'<>:"/\|?*')[:50]
            safe_label = "".join(c for c in str(num_label) if c not in r'<>:"/\|?*')
            ext_map = {"zip": "zip", "pdf": "pdf", "cbz": "cbz"}
            file_ext = ext_map.get(fmt, "zip")
            output_path = Path(valid_paths[0]).parent / f"{safe_title}_{safe_label}.{file_ext}"

            try:
                loop = asyncio.get_running_loop()
                if fmt == "pdf":
                    await loop.run_in_executor(None, pack_pdf, valid_paths, output_path)
                elif fmt == "cbz":
                    await loop.run_in_executor(None, pack_cbz, valid_paths, output_path)
                else:
                    await loop.run_in_executor(None, pack_zip, valid_paths, output_path)
            except Exception as e:
                ...
```

为：

```python
            file_ext = normalize_pack_format(fmt)
            output_path = build_chapter_output_path(
                Path(valid_paths[0]).parent, manga.title, str(num_label), file_ext
            )

            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, pack_images, valid_paths, output_path, fmt)
            except Exception as e:
                ...
```

`filename = output_path.name`（替换原 `filename = f"{safe_title}_{safe_label}.{file_ext}"`）。

`main.py` `_prepare_chapter_file_delivery` 同样替换（`safe_title`/`safe_label` 两行 + 分支打包），并保持 `filename = output_path.name`。更新 main.py 导入：`pack_images, build_chapter_output_path, normalize_pack_format`（移除不再使用的 `pack_pdf/pack_cbz/pack_zip` 若不再引用——`download_chapter` 与 `_prepare_chapter_file_delivery` 是仅有的引用点）。

`utils/pusher.py` `push_chapter_file` 同样替换（含 `ext_map` 三行），并更新导入。

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/test_pack.py tests/test_push.py -q && python -c "import ast; ast.parse(open('main.py', encoding='utf-8').read()); print('OK')"`
Expected: 全部 PASS + `OK`。

- [ ] **Step 6: Commit**

```bash
git add utils/pack.py main.py utils/pusher.py tests/test_pack.py
git commit -m "refactor: extract shared chapter packaging helpers"
```

---

### Task 10: 统一图片消息链构建（去重）

**Files:**
- Modify: `utils/pusher.py`
- Modify: `main.py`
- Modify: `tests/test_push.py`

- [ ] **Step 1: 编写失败测试**

`tests/test_push.py` 追加（使用 conftest 的 `astrbot.api.message_components` 全局 mock）：

```python
class TestBuildImageChain:

    @pytest.fixture(autouse=True)
    def reset_comp(self):
        Comp.reset_mock()
        yield

    def test_inline_with_header_and_tail(self):
        chain = build_image_chain(
            ["http://x/1", "http://x/2"], ["", ""], "download",
            send_mode="image", forward_platform=True,
            page_label="第1话", header="📖「T」第1话",
            total_pages=5, max_pages=2, tail_text="tail",
        )
        assert len(chain) == 4
        assert Comp.Plain.call_count == 2
        assert Comp.Image.fromURL.call_count == 2

    def test_forward_with_header(self):
        chain = build_image_chain(
            ["http://x/1"], [""], "download",
            send_mode="forward", forward_platform=True,
            page_label="第1话", header="📖「T」第1话",
            header_node_name="「T」第1话",
            total_pages=1, max_pages=30, tail_text="tail",
        )
        assert len(chain) == 1  # [Nodes]
        assert Comp.Nodes.call_count == 1
        nodes = Comp.Nodes.call_args.args[0]
        assert len(nodes) == 2  # header node + 1 page node

    def test_forward_without_header(self):
        chain = build_image_chain(
            ["http://x/1"], [""], "download",
            send_mode="forward", forward_platform=True,
            page_label="第1话", header=None,
            total_pages=1, max_pages=30, tail_text="tail",
        )
        nodes = Comp.Nodes.call_args.args[0]
        assert len(nodes) == 1

    def test_download_mode_uses_local_files(self):
        chain = build_image_chain(
            ["http://x/1"], ["/tmp/1.jpg"], "download",
            send_mode="image", forward_platform=False,
            page_label="第1话", header=None,
            total_pages=1, max_pages=30, tail_text="tail",
        )
        assert Comp.Image.fromFileSystem.call_count == 1
        assert Comp.Image.fromURL.call_count == 0
```

其中 `Comp` 来自 conftest mock（`import astrbot.api.message_components as Comp` 或 `from astrbot.api import message_components as Comp`）。

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_push.py::TestBuildImageChain -v`
Expected: FAIL（`ImportError: cannot import name 'build_image_chain'`）。

- [ ] **Step 3: 实现构建器**

`utils/pusher.py` 追加（含 `_PLUGIN_NAME` 已有的 warning 日志）：

```python
def build_image_chain(
    page_urls: list[str],
    local_paths: list[str],
    fetch_mode: str,
    *,
    send_mode: str,
    forward_platform: bool,
    page_label: str,
    header: str | None = None,
    header_node_name: str | None = None,
    total_pages: int,
    max_pages: int,
    tail_text: str,
) -> list:
    """Build the image/forward message chain shared by read, push and AI send."""

    def _img(idx: int) -> Comp.Image:
        if fetch_mode == "download" and idx < len(local_paths) and local_paths[idx]:
            return Comp.Image.fromFileSystem(local_paths[idx])
        if fetch_mode == "download":
            logger.warning(
                f"[{_PLUGIN_NAME}] 图片 {idx + 1} 下载失败，将使用 URL 直连"
                "（带认证的服务器可能无法加载，请检查认证配置）"
            )
        return Comp.Image.fromURL(page_urls[idx])

    if send_mode == "forward" and forward_platform:
        nodes: list[Comp.Node] = []
        if header is not None:
            nodes.append(Comp.Node(
                uin="0",
                name=header_node_name or page_label,
                content=[Comp.Plain(header)],
            ))
        for i in range(len(page_urls)):
            nodes.append(Comp.Node(
                uin="0",
                name=f"{page_label} - 第 {i + 1} 页",
                content=[_img(i)],
            ))
        if total_pages > max_pages:
            nodes.append(Comp.Node(
                uin="0",
                name="提示",
                content=[Comp.Plain(tail_text)],
            ))
        return [Comp.Nodes(nodes)]

    chain: list = []
    if header is not None:
        chain.append(Comp.Plain(header))
    chain.extend(_img(i) for i in range(len(page_urls)))
    if total_pages > max_pages:
        chain.append(Comp.Plain(tail_text))
    return chain
```

- [ ] **Step 4: 重构两个调用点**

`main.py` `_prepare_chapter_delivery`：删除 `_img` 闭包与整个 `if send_mode == "forward"...else...` 分支，替换为：

```python
        chain = build_image_chain(
            page_urls, local_paths, fetch_mode,
            send_mode=send_mode,
            forward_platform=event.get_platform_name() == "aiocqhttp",
            page_label=fmt_chapter_display(target),
            header=None,
            total_pages=total_pages,
            max_pages=max_pages,
            tail_text=f"... 还有 {total_pages - max_pages} 页，请到 WebUI 查看",
        )
        result = event.chain_result(chain)
```

`utils/pusher.py` `push_chapter_images`：删除 `_img` 闭包与 `try: if send_mode == "forward" ... else ...` 整块，替换为：

```python
        chain = build_image_chain(
            page_urls, local_paths, fetch_mode,
            send_mode=send_mode,
            forward_platform=is_aiocqhttp_target(context, umo),
            page_label=ch_label,
            header=f"📖「{title}」{ch_label}",
            header_node_name=f"「{title}」{ch_label}",
            total_pages=total_pages,
            max_pages=max_pages,
            tail_text=f"... 还有 {total_pages - max_pages} 页，请使用「漫画 阅读」查看",
        )
        try:
            await context.send_message(umo, MessageChain(chain=chain))
        except Exception as e:
            logger.warning(f"[{_PLUGIN_NAME}] 图片推送到{umo}失败: {e}")
            await context.send_message(
                umo,
                MessageChain().message(
                    f"📖「{title}」{ch_label}已更新，"
                    f"但图片发送失败，请使用「漫画 阅读」查看"
                ),
            )
```

注意保留 `push_chapter_images` 中 download 模式全失败时的提前 return 逻辑（含 `schedule_cleanup`）。

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/test_push.py -q && python -c "import ast; ast.parse(open('main.py', encoding='utf-8').read()); print('OK')"`
Expected: 全部 PASS + `OK`。

- [ ] **Step 6: Commit**

```bash
git add utils/pusher.py main.py tests/test_push.py
git commit -m "refactor: unify chapter image chain building across read and push"
```

---

### Task 11: 区分章节投递失败原因（错误提示）

**Files:**
- Modify: `suwayomi/service.py`
- Modify: `main.py`
- Modify: `tests/test_service.py`

- [ ] **Step 1: 编写失败测试**

`tests/test_service.py` 追加：

```python
class TestFmtDeliveryFailureMessage:

    def test_no_pages(self):
        from suwayomi.service import fmt_delivery_failure_message
        assert "暂无可用页面" in fmt_delivery_failure_message(0, "download", "none")

    def test_download_failed_with_auth(self):
        from suwayomi.service import fmt_delivery_failure_message
        msg = fmt_delivery_failure_message(30, "download", "jwt")
        assert "30" in msg and "jwt" in msg and "认证" in msg

    def test_download_failed_without_auth(self):
        from suwayomi.service import fmt_delivery_failure_message
        msg = fmt_delivery_failure_message(10, "download", "none")
        assert "10" in msg and "认证" not in msg

    def test_url_mode_with_auth(self):
        from suwayomi.service import fmt_delivery_failure_message
        msg = fmt_delivery_failure_message(5, "url", "basic")
        assert "URL 模式" in msg and "下载模式" in msg
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_service.py::TestFmtDeliveryFailureMessage -v`
Expected: FAIL（`ImportError: cannot import name 'fmt_delivery_failure_message'`）。

- [ ] **Step 3: 实现**

`suwayomi/service.py` 追加：

```python
def fmt_delivery_failure_message(total_pages: int, fetch_mode: str, auth_mode: str) -> str:
    """Explain why chapter delivery failed, distinguishing real causes."""
    if total_pages <= 0:
        return "该章节暂无可用页面。"
    if fetch_mode == "download":
        if auth_mode and auth_mode != "none":
            return (
                f"所有 {total_pages} 页图片下载失败。当前 Suwayomi 开启了 "
                f"{auth_mode} 认证，请检查认证用户名/密码是否正确。"
            )
        return (
            f"所有 {total_pages} 页图片下载失败，"
            "请检查 Suwayomi 服务是否正常运行，或尝试更换图片获取方式。"
        )
    if auth_mode and auth_mode != "none":
        return "图片 URL 模式不兼容带认证的 Suwayomi 服务器，请改用下载模式。"
    return "图片加载失败，请稍后重试。"
```

- [ ] **Step 4: main.py 使用**

`main.py` `read_chapter` 中替换：

```python
                result, _, _, tmp_dir = await self._prepare_chapter_delivery(event, target)
                if result is None:
                    if self.config.get("image_fetch_mode", "download") == "download" and self.client.auth_mode != "none":
                        yield event.plain_result(...)
                    else:
                        yield event.plain_result(f"{fmt_chapter_display(target)}暂无可用页面。")
                    return
```

为：

```python
                result, total_pages, _, tmp_dir = await self._prepare_chapter_delivery(event, target)
                if result is None:
                    fetch_mode = self.config.get("image_fetch_mode", "download")
                    yield event.plain_result(
                        fmt_delivery_failure_message(
                            total_pages, fetch_mode, self.client.auth_mode
                        )
                    )
                    return
```

`main.py` 导入处加 `fmt_delivery_failure_message`。

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/test_service.py -q && python -c "import ast; ast.parse(open('main.py', encoding='utf-8').read()); print('OK')"`
Expected: 全部 PASS + `OK`。

- [ ] **Step 6: Commit**

```bash
git add suwayomi/service.py main.py tests/test_service.py
git commit -m "fix: distinguish chapter delivery failure causes in user messages"
```

---

### Task 12: 源列表 TTL 缓存

**Files:**
- Modify: `suwayomi/client.py`
- Modify: `tests/test_client.py`

- [ ] **Step 1: 编写失败测试**

`tests/test_client.py` 追加：

```python
_SOURCE_NODE = {"id": "1", "name": "src", "lang": "zh", "displayName": "源", "supportsLatest": True}


@pytest.mark.asyncio
async def test_get_sources_cached_within_ttl(client):
    client._post_graphql = AsyncMock(return_value=(200, {"data": {"sources": {"nodes": [_SOURCE_NODE]}}}))
    s1 = await client.get_sources()
    s2 = await client.get_sources()
    assert s1 == s2
    assert client._post_graphql.await_count == 1


@pytest.mark.asyncio
async def test_get_sources_refetches_after_ttl(client, monkeypatch):
    clock = {"now": 1000.0}
    monkeypatch.setattr("suwayomi.client.time.time", lambda: clock["now"])
    client._post_graphql = AsyncMock(return_value=(200, {"data": {"sources": {"nodes": [_SOURCE_NODE]}}}))
    await client.get_sources()
    clock["now"] += 61
    await client.get_sources()
    assert client._post_graphql.await_count == 2
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_client.py::test_get_sources_cached_within_ttl -v`
Expected: FAIL（无缓存，`await_count == 2`）。

- [ ] **Step 3: 实现缓存**

`suwayomi/client.py`：文件头加 `import time`；`__init__` 加：

```python
        self._sources_cache: tuple[float, list[Source]] | None = None
```

模块级常量：

```python
_SOURCES_CACHE_TTL = 60
```

`get_sources` 改为：

```python
    async def get_sources(self) -> list[Source]:
        now = time.time()
        if self._sources_cache and now - self._sources_cache[0] < _SOURCES_CACHE_TTL:
            return self._sources_cache[1]
        data = await self._raw_query(
            'query{sources{nodes{id name lang displayName supportsLatest}}}'
        )
        sources = [Source.from_dict(s) for s in data["sources"]["nodes"]]
        self._sources_cache = (now, sources)
        return sources
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_client.py -q`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add suwayomi/client.py tests/test_client.py
git commit -m "perf: cache source list with TTL in client"
```

---

### Task 13: 内存上限（AiInteractionState + 搜索缓存）

**Files:**
- Modify: `suwayomi/ai_service.py`
- Modify: `suwayomi/service.py`
- Modify: `main.py`
- Modify: `tests/test_ai_service.py`
- Modify: `tests/test_service.py`

- [ ] **Step 1: 编写失败测试**

`tests/test_ai_service.py` 追加：

```python
def test_ai_interaction_state_evicts_oldest_beyond_max():
    state = AiInteractionState(ttl=600, max_entries=2)
    state.remember_chapters(("o", "u1"), 1, {10}, now=100.0)
    state.remember_chapters(("o", "u2"), 2, {20}, now=200.0)
    state.remember_chapters(("o", "u3"), 3, {30}, now=300.0)
    assert state.was_chapter_exposed(("o", "u1"), 1, 10, now=301.0) is False
    assert state.was_chapter_exposed(("o", "u2"), 2, 20, now=301.0) is True
    assert state.was_chapter_exposed(("o", "u3"), 3, 30, now=301.0) is True
```

`tests/test_service.py` 追加：

```python
class TestTtlCacheHelpers:

    def test_lookup_expires(self):
        from suwayomi.service import ttl_cache_lookup, ttl_cache_store
        cache = {}
        ttl_cache_store(cache, "a", 1, ttl=10, max_entries=4, now=100.0)
        assert ttl_cache_lookup(cache, "a", 10, now=105.0) == 1
        assert ttl_cache_lookup(cache, "a", 10, now=115.0) is None

    def test_store_evicts_oldest(self):
        from suwayomi.service import ttl_cache_lookup, ttl_cache_store
        cache = {}
        ttl_cache_store(cache, "a", 1, ttl=10, max_entries=2, now=1.0)
        ttl_cache_store(cache, "b", 2, ttl=10, max_entries=2, now=2.0)
        ttl_cache_store(cache, "c", 3, ttl=10, max_entries=2, now=3.0)
        assert ttl_cache_lookup(cache, "a", 10, now=4.0) is None
        assert ttl_cache_lookup(cache, "b", 10, now=4.0) == 2
        assert ttl_cache_lookup(cache, "c", 10, now=4.0) == 3
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_ai_service.py::test_ai_interaction_state_evicts_oldest_beyond_max tests/test_service.py::TestTtlCacheHelpers -v`
Expected: 第一个 FAIL（无上限）；第二个 FAIL（`ImportError`）。

- [ ] **Step 3: 实现**

`suwayomi/ai_service.py` `AiInteractionState`：

```python
    def __init__(self, ttl: int = 600, max_entries: int = 512):
        self.ttl = max(1, int(ttl))
        self.max_entries = max(1, int(max_entries))
```

`remember_chapters` 末尾追加：

```python
        if len(self._chapters) > self.max_entries:
            oldest = min(self._chapters, key=lambda k: self._chapters[k][0])
            del self._chapters[oldest]
```

`suwayomi/service.py` 追加：

```python
def ttl_cache_store(
    cache: dict[str, tuple[float, Any]],
    key: str,
    value: Any,
    ttl: float,
    max_entries: int,
    now: float | None = None,
) -> None:
    cache[key] = (now if now is not None else time.time(), value)
    if len(cache) > max_entries:
        oldest = min(cache, key=lambda k: cache[k][0])
        del cache[oldest]


def ttl_cache_lookup(
    cache: dict[str, tuple[float, Any]],
    key: str,
    ttl: float,
    now: float | None = None,
) -> Any:
    entry = cache.get(key)
    if entry is None:
        return None
    ts, value = entry
    if (now if now is not None else time.time()) - ts > ttl:
        cache.pop(key, None)
        return None
    return value
```

`service.py` 文件头补 `from typing import Any`。

- [ ] **Step 4: main.py 搜索缓存接入**

`main.py` 导入 `ttl_cache_lookup, ttl_cache_store`；模块常量 `_SEARCH_CACHE_MAX_ENTRIES = 64`；替换：

```python
    def _get_cached_manga(self, umo: str, key: str) -> Manga | None:
        cache = ttl_cache_lookup(self._search_cache, umo, _CACHE_TTL)
        if cache is None:
            return None
        return cache.get(key)

    def _set_search_cache(self, umo: str, cache: dict[str, Manga]):
        ttl_cache_store(self._search_cache, umo, cache, _CACHE_TTL, _SEARCH_CACHE_MAX_ENTRIES)
```

（删除 `time` 不再使用的导入若仅此处使用——`time` 在 main.py 中仅 `_get_cached_manga` 使用过，删除后不再需要，但需确认无其他引用。）

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/test_ai_service.py tests/test_service.py -q && python -c "import ast; ast.parse(open('main.py', encoding='utf-8').read()); print('OK')"`
Expected: 全部 PASS + `OK`。

- [ ] **Step 6: Commit**

```bash
git add suwayomi/ai_service.py suwayomi/service.py main.py tests/test_ai_service.py tests/test_service.py
git commit -m "perf: bound transient in-memory caches"
```

---

### Task 14: GitHub Actions CI

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: 编写 workflow**

`.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest pytest-asyncio
      - name: Run unit tests
        run: python -m pytest tests/ -q
```

说明：`pyproject.toml`/`uv.lock` 被 `.gitignore` 排除，CI 用 pip 安装；live 测试在 CI 中因服务器不可达自动跳过（Task 1）。

- [ ] **Step 2: 本地等价验证**

Run: `python -m pytest tests/ -q`（等效于 CI 命令；本机 `uv run pytest` 亦可）
Expected: 全部 PASS（live 自动跳过）。

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add GitHub Actions workflow running unit tests"
```

---

### Task 15: 文档同步

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `AGENTS.md`

- [ ] **Step 1: CHANGELOG 增加 Unreleased 段**

按现有 CHANGELOG 风格在顶部加：

```markdown
## Unreleased

### 修复
- live 集成测试在 Suwayomi-Server 不可达时自动跳过，不再使全量测试失败
- 订阅数据读写加锁，避免后台更新与用户操作并发时丢失更新
- 章节时间戳 KV 读写加锁，避免并行检查时互相覆盖
- 更新检查改为并行执行（并发上限 5），订阅多时显著提速
- 后台更新循环与手动更新后统一记录 last_update_check 时间戳
- WebUI 配置接口白名单校验枚举值（send_mode / image_fetch_mode / auto_push_mode / download_format）
- 「漫画 阅读 / 下载」支持 第X话 / 第X話 / 第X章 格式，与 AI 路径解析一致
- 配置的 temp_dir 不存在时自动创建
- 延迟清理临时目录的任务在插件卸载时取消，避免目录泄漏
- 章节投递失败时按真实原因提示（无页面 / 认证问题 / URL 模式不兼容）

### 重构
- 提取共享打包助手（文件名清洗、格式归一、打包分发），消除三处重复
- 统一阅读与自动推送的图片消息链构建
- 源列表增加 60s TTL 缓存，减少重复请求

### 性能
- 会话状态与搜索缓存增加条目上限，避免长期运行内存缓慢增长

### CI
- 新增 GitHub Actions workflow，push/PR 自动运行单元测试
```

- [ ] **Step 2: AGENTS.md 同步**

`Commands` 节更新：

```markdown
# All tests
uv run pytest -v
```

下方补一行说明：`集成测试（test_live_*）在 Suwayomi-Server 不可达时自动跳过，无需手动排除；本地调试用 SUWAYOMI_URL 指向真实服务器。`

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md AGENTS.md
git commit -m "docs: update CHANGELOG and AGENTS for reliability fixes"
```

---

### Task 16: 全量验证 + 子 Agent Review

- [ ] **Step 1: 全量测试与语法检查**

```bash
uv run pytest -q
python -c "import ast; ast.parse(open('main.py', encoding='utf-8').read()); print('OK')"
```

Expected: 全部 PASS（live 跳过）、`OK`。

- [ ] **Step 2: 子 Agent Review**

派发 general subagent 审阅分支全部更改（`git diff origin/main...HEAD`），重点：并发正确性（锁的覆盖范围）、行为等价性（重构后推送/阅读输出是否与原先一致）、边界情况。收集反馈并修复（TDD 优先，补测试）。

- [ ] **Step 3: 最终确认与提交**

修复后重跑全量测试；如有修复提交追加 commit。
