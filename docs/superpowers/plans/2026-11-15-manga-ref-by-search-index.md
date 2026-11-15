# 按搜索结果编号引用漫画 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `/漫画 章节|阅读|下载` 能消费 `/漫画 搜索` 的结果编号，并把漫画 ID 统一改为必须写作 `ID:数字`。

**Architecture:** `suwayomi/service.py` 新增纯函数 `parse_manga_ref` 把用户输入分类为 `id` / `index` / `name`；`resolve_manga` 按分类解析，`index` 分支通过注入的 `index_lookup(umo, key) -> (Manga|None, count)` 读取插件上既有的会话搜索缓存。命令层只在三处调用点透传回调，并把所有自产 ID 文案改成可解析的 `ID:数字`。

**Tech Stack:** Python 3.12、pytest / pytest-asyncio、uv；无新增依赖。

**Spec:** `docs/superpowers/specs/2026-11-15-manga-ref-by-search-index-design.md`

## Global Constraints

- Python 3.12+，不引入新依赖；测试用 `uv run pytest`。
- 用户可见文案一律中文，命令写法用「漫画 命令」格式。
- 漫画 ID 的**唯一**可解析形态是 `ID:数字`（NFKC 后忽略大小写、全角冒号、冒号后空格）。
- 搜索编号 = 会话内最近一次搜索展示过的下标（`_CACHE_TTL = 600` 秒，`str(n)` 为键）。
- 裸数字永不回退为漫画 ID；`取消订阅` 不消费搜索编号。
- 搜索结果**卡片**布局与 footer 不改；只允许文本模式追加提示。
- 引用第三方文本（标题/源名/用户输入回显）必须经 `sanitize_for_message` 并限长。
- 数据/错误文案里的 ID 一律写成 `ID:{n}`（无空格），保证可直接复制回命令。

## Review Focus

- **跨会话编号隔离**：A 会话的搜索编号不能给 B 会话用 → 未命中走「无有效搜索」文案（Task 3 测试覆盖）。
- **ID 探测失败**：未命中编号时用 `get_manga(n)` 判断 ID 是否存在，网络异常不得冒泡（Task 2 测试覆盖）。
- **边界**：缓存过期（600s）、编号越界（> 展示条数）都必须给出可执行提示，而不是「未找到该漫画」（Task 2/3 覆盖）。
- **取消订阅不能谎报成功**：未订阅的 `ID:N` 必须明确报未找到（Task 4 覆盖）。
- **纯数字标题**：`/漫画 章节 86` 现在解释为编号，不得崩溃；报错要能引导到 `ID:86` 或先搜索（Task 2 覆盖，README 说明）。

---

### Task 1: `parse_manga_ref` 纯函数

**Files:**
- Modify: `suwayomi/service.py`（模块级，放在 `resolve_manga` 之前）
- Test: `tests/test_service.py`

**Interfaces:**
- Produces: `parse_manga_ref(text: str) -> tuple[str, int | str]`，kind ∈ `{"id", "index", "name"}`；`name` 分支返回调用方原始文本（`str(text).strip()`，未做 NFKC）。

- [ ] **Step 1: 写失败测试**

在 `tests/test_service.py` 顶部导入 `parse_manga_ref`，新增参数化测试：

```python
@pytest.mark.parametrize("text,expected", [
    ("ID:1", ("id", 1)),
    ("id：1", ("id", 1)),
    ("ＩＤ：１", ("id", 1)),
    ("  ID: 151  ", ("id", 151)),
    ("3", ("index", 3)),
    ("007", ("index", 7)),
    ("３", ("index", 3)),
    ("第3话", ("name", "第3话")),
    ("86-不存在的战区-", ("name", "86-不存在的战区-")),
    ("", ("name", "")),
])
def test_parse_manga_ref(text, expected):
    assert parse_manga_ref(text) == expected


def test_parse_manga_ref_keeps_name_whitespace_trimmed():
    assert parse_manga_ref("  安达与岛村  ") == ("name", "安达与岛村")
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_service.py -k parse_manga_ref -v`
Expected: FAIL（`ImportError: cannot import name 'parse_manga_ref'`）

- [ ] **Step 3: 实现**

```python
_ID_REF_RE = re.compile(r"id\s*[:：]\s*(\d+)", re.IGNORECASE)


def parse_manga_ref(text: str) -> tuple[str, int | str]:
    """Classify a manga reference: ("id", n) | ("index", n) | ("name", text)."""
```

实现要点：`norm = unicodedata.normalize("NFKC", str(text)).strip()`；`_ID_REF_RE.fullmatch(norm)` → `("id", int(...))`；`re.fullmatch(r"\d+", norm)` → `("index", int(norm))`；其余 `("name", str(text).strip())`。`service.py` 已导入 `re`/`unicodedata`，缺则补。

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_service.py -k parse_manga_ref -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add suwayomi/service.py tests/test_service.py
git commit -m "feat(service): 新增漫画引用解析 parse_manga_ref"
```

---

### Task 2: `resolve_manga` 支持 `ID:` 与搜索编号

**Files:**
- Modify: `suwayomi/service.py:638-689`（`resolve_manga`）
- Test: `tests/test_resolve_manga.py`（新建）

**Interfaces:**
- Consumes: `parse_manga_ref`（Task 1）、`sanitize_for_message`、`normalize_zh`。
- Produces: `async def resolve_manga(client, sub_mgr, umo, name_or_id, cmd, *, index_lookup=None) -> tuple[Manga | None, str | None]`；`index_lookup: Callable[[str, str], tuple[Manga | None, int]]`（参数顺序 `(umo, key)`），`None` 表示不支持编号。
- Produces: 三类编号错误文案与 `ID:{n}` 格式的多结果清单（Task 4/5 依赖文案里的 `ID:` 形态）。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_resolve_manga.py`：

```python
"""Unit tests for resolve_manga reference parsing (no network)."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from suwayomi.models import Manga, Source
from suwayomi.service import resolve_manga

UMO = "aiocqhttp:group:g1"


def _manga(mid=151, title="安达与岛村"):
    return Manga(id=mid, source_id=2, url="", title=title, status="ONGOING")


class _Client:
    def __init__(self, mangas=None, by_title=None):
        self._mangas = mangas or {}
        self._by_title = by_title or []

    async def get_manga(self, manga_id):
        if int(manga_id) in self._mangas:
            return self._mangas[int(manga_id)]
        from suwayomi.client import SuwayomiError
        raise SuwayomiError("not found")

    async def search_manga_by_title(self, title, limit=10):
        return list(self._by_title)

    async def get_sources(self):
        return [Source(id="2", name="mh", lang="zh", display_name="拷贝漫画")]


def _subs(titles=()):
    sub_mgr = MagicMock()
    sub_mgr.get_subscriptions = AsyncMock(
        return_value=[{"manga_id": 1, "title": t} for t in titles]
    )
    return sub_mgr


@pytest.mark.asyncio
async def test_index_hit_returns_cached_manga_without_lookup():
    cached = _manga(302, "安达与岛村官方同人集")
    client = _Client()
    manga, err = await resolve_manga(
        client, _subs(), UMO, "3", "阅读",
        index_lookup=lambda umo, key: (cached, 5),
    )
    assert err is None and manga is cached


@pytest.mark.asyncio
async def test_index_miss_but_id_exists_points_to_id_syntax():
    client = _Client(mangas={3: _manga(3, "某漫画")})
    manga, err = await resolve_manga(
        client, _subs(), UMO, "3", "阅读",
        index_lookup=lambda umo, key: (None, 0),
    )
    assert manga is None
    assert "是漫画 ID" in err and "ID:3" in err and "阅读" in err


@pytest.mark.asyncio
async def test_index_out_of_range_reports_display_range():
    client = _Client()
    manga, err = await resolve_manga(
        client, _subs(), UMO, "9", "章节",
        index_lookup=lambda umo, key: (None, 5),
    )
    assert manga is None
    assert "1–5" in err and "9" in err


@pytest.mark.asyncio
async def test_index_without_cache_explains_ttl():
    client = _Client()
    manga, err = await resolve_manga(
        client, _subs(), UMO, "2", "下载",
        index_lookup=lambda umo, key: (None, 0),
    )
    assert manga is None
    assert "10 分钟" in err and "漫画 搜索" in err


@pytest.mark.asyncio
async def test_id_ref_resolves_and_does_not_fall_through_to_names():
    client = _Client(mangas={151: _manga(151)})
    manga, err = await resolve_manga(client, _subs(["安达与岛村"]), UMO, "ID:151", "阅读")
    assert err is None and manga.id == 151


@pytest.mark.asyncio
async def test_id_ref_missing_reports_id_not_found():
    client = _Client()
    manga, err = await resolve_manga(client, _subs(["安达与岛村"]), UMO, "id：999", "阅读")
    assert manga is None and "ID:999" in err and "未找到" in err


@pytest.mark.asyncio
async def test_id_probe_failure_falls_back_to_ttl_message():
    from suwayomi.client import SuwayomiError

    client = _Client()
    client.get_manga = AsyncMock(side_effect=SuwayomiError("boom"))
    manga, err = await resolve_manga(
        client, _subs(), UMO, "4", "阅读",
        index_lookup=lambda umo, key: (None, 0),
    )
    assert manga is None and "10 分钟" in err


@pytest.mark.asyncio
async def test_numeric_title_is_treated_as_index_not_crash():
    client = _Client()
    manga, err = await resolve_manga(
        client, _subs(), UMO, "86", "章节",
        index_lookup=lambda umo, key: (None, 0),
    )
    assert manga is None and "漫画 搜索" in err


@pytest.mark.asyncio
async def test_name_path_unchanged_and_multi_result_uses_id_prefix():
    client = _Client(by_title=[_manga(151), _manga(302, "安达与岛村官方同人集")])
    manga, err = await resolve_manga(client, _subs(["别的漫画"]), UMO, "安达与岛村", "章节")
    assert manga is None
    assert "ID:151" in err and "ID:302" in err
    assert "ID 151" not in err
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_resolve_manga.py -v`
Expected: FAIL（`TypeError: resolve_manga() got an unexpected keyword argument 'index_lookup'` 等）

- [ ] **Step 3: 实现 `resolve_manga`**

结构（`cmd` 只用于拼用法行）：

```python
async def resolve_manga(client, sub_mgr, umo, name_or_id, cmd, *, index_lookup=None):
    kind, value = parse_manga_ref(name_or_id)
    if kind == "id":
        try:
            return await client.get_manga(int(value)), None
        except SuwayomiError:
            return None, f"未找到 ID:{value} 的漫画。"
    if kind == "index":
        return await _resolve_by_index(client, index_lookup, umo, int(value), cmd)
    # name 分支：原订阅 → DB 标题逻辑，保持不变
```

新增私有协程 `_resolve_by_index(client, index_lookup, umo, n, cmd)`：

1. `index_lookup` 为 `None` → `(manga, count) = (None, 0)`；否则 `index_lookup(umo, str(n))`，异常按 `(None, 0)` 处理并 `logger.debug`。
2. 命中返回 `(manga, None)`，`logger.debug` 记录编号/manga_id/count。
3. 未命中：用 `client.get_manga(n)` 探测（`except Exception` 视为不存在，`logger.debug`），按设计文档三个文案返回，用法行 `/漫画 {cmd} ID:{n} <章节>`。

多结果清单同文件内改为 `f"  ID:{m.id}: ..."`，示例行改为 `f"找到多个结果，请使用 ID 指定。例如: /漫画 {cmd} ID:{mangas[0].id}"`。`name` 分支其余逻辑（订阅名子串、`get_sources` 源名映射、`sanitize_for_message`）保持不变。

- [ ] **Step 4: 运行确认通过 + 回归**

Run: `uv run pytest tests/test_resolve_manga.py tests/test_service.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add suwayomi/service.py tests/test_resolve_manga.py
git commit -m "feat(service): resolve_manga 支持 ID: 前缀与搜索结果编号"
```

---

### Task 3: 命令层注入搜索编号回调

**Files:**
- Modify: `main.py:653-664`（搜索缓存区）、`main.py:1565`、`main.py:1729`、`main.py:1798`
- Test: `tests/test_search_index_lookup.py`（新建）、`tests/test_list_chapters.py`（追加一条）

**Interfaces:**
- Consumes: `resolve_manga(..., index_lookup=...)`（Task 2）。
- Produces: `SuwayomiPlugin._search_index_lookup(self, umo: str, key: str) -> tuple[Manga | None, int]`。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_search_index_lookup.py`（沿用 `tests/test_search_ranking.py` 的 `_plugin` 构造方式，显式设置 `plugin._search_cache = {}` 与 `plugin._card_cache` 不需要）：

```python
import time
from unittest.mock import MagicMock

from plugin_pkg.main import SuwayomiPlugin
from plugin_pkg.suwayomi.models import Manga


def _plugin():
    plugin = SuwayomiPlugin.__new__(SuwayomiPlugin)
    plugin._search_cache = {}
    return plugin


def _manga(mid=302):
    return Manga(id=mid, source_id=2, url="", title="安达与岛村官方同人集")


def test_lookup_returns_manga_and_count():
    plugin = _plugin()
    plugin._search_cache["u1"] = (time.time(), {"1": _manga(1), "3": _manga(302)})
    manga, count = plugin._search_index_lookup("u1", "3")
    assert manga.id == 302 and count == 2


def test_lookup_expired_returns_empty():
    plugin = _plugin()
    plugin._search_cache["u1"] = (time.time() - 601, {"3": _manga()})
    assert plugin._search_index_lookup("u1", "3") == (None, 0)


def test_lookup_is_scoped_to_session():
    plugin = _plugin()
    plugin._search_cache["u1"] = (time.time(), {"3": _manga()})
    assert plugin._search_index_lookup("u2", "3") == (None, 0)
```

并给 `tests/test_list_chapters.py` 追加接线测试：

```python
@pytest.mark.asyncio
async def test_list_chapters_passes_index_lookup(monkeypatch):
    from unittest.mock import call
    plugin = _make_plugin()
    plugin._search_cache = {}
    event = _make_event()
    mocked = AsyncMock(return_value=(_make_manga(), None))
    monkeypatch.setattr("plugin_pkg.main.resolve_manga", mocked)
    monkeypatch.setattr(
        "plugin_pkg.main.get_or_fetch_chapters", AsyncMock(return_value=[])
    )
    _ = [msg async for msg in plugin.list_chapters(event, "测试漫画")]
    assert mocked.call_args.kwargs["index_lookup"].__self__ is plugin
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_search_index_lookup.py tests/test_list_chapters.py -k "lookup or passes_index_lookup" -v`
Expected: FAIL（`AttributeError: 'SuwayomiPlugin' object has no attribute '_search_index_lookup'` / 缺少 `index_lookup` kwarg）

- [ ] **Step 3: 实现**

在 `_get_cached_manga` 旁新增：

```python
def _search_index_lookup(self, umo: str, key: str) -> tuple[Manga | None, int]:
    cache = ttl_cache_lookup(self._search_cache, umo, _CACHE_TTL)
    if not cache:
        return None, 0
    return cache.get(key), len(cache)
```

`_get_cached_manga` 改为复用它（`return self._search_index_lookup(umo, key)[0]`），保持 `订阅` 行为不变。三处 `resolve_manga(...)` 调用追加 `, index_lookup=self._search_index_lookup`。

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_search_index_lookup.py tests/test_list_chapters.py tests/test_card_commands.py tests/test_search_ranking.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add main.py tests/test_search_index_lookup.py tests/test_list_chapters.py
git commit -m "feat(main): 章节/阅读/下载 消费搜索结果编号"
```

---

### Task 4: `取消订阅` 支持 `ID:` 并拒绝裸数字

**Files:**
- Modify: `main.py:1398-1424`（`unsubscribe_manga`）
- Test: `tests/test_unsubscribe.py`（新建）

**Interfaces:**
- Consumes: `parse_manga_ref`（Task 1）。
- Produces: `取消订阅 ID:151` 可用；`取消订阅 3` 返回引导文案；未订阅时返回 `未找到该订阅（ID:{n}）`。

- [ ] **Step 1: 写失败测试**

```python
"""Unit tests for /漫画 取消订阅 reference syntax (no network)."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from plugin_pkg.main import SuwayomiPlugin


def _plugin(subscriptions=None):
    plugin = SuwayomiPlugin.__new__(SuwayomiPlugin)
    plugin.sub_mgr = MagicMock()
    plugin.sub_mgr.get_subscriptions = AsyncMock(return_value=subscriptions or [])
    plugin.sub_mgr.unsubscribe = AsyncMock()
    return plugin


def _event(message):
    event = MagicMock()
    event.unified_msg_origin = "aiocqhttp:group:g1"
    event.message_str = message
    event.plain_result = MagicMock(side_effect=lambda text: text)
    return event


@pytest.mark.asyncio
async def test_unsubscribe_accepts_id_prefix():
    plugin = _plugin([{"manga_id": 151, "title": "安达与岛村"}])
    results = [m async for m in plugin.unsubscribe_manga(_event("/漫画 取消订阅 ID:151"), "ID:151")]
    plugin.sub_mgr.unsubscribe.assert_awaited_once_with(151, "aiocqhttp:group:g1")
    assert "已取消订阅" in results[0]


@pytest.mark.asyncio
async def test_unsubscribe_rejects_bare_number_with_guidance():
    plugin = _plugin([{"manga_id": 151, "title": "安达与岛村"}])
    results = [m async for m in plugin.unsubscribe_manga(_event("/漫画 取消订阅 3"), "3")]
    plugin.sub_mgr.unsubscribe.assert_not_awaited()
    assert "ID:3" in results[0]


@pytest.mark.asyncio
async def test_unsubscribe_unsubscribed_id_is_reported():
    plugin = _plugin([{"manga_id": 151, "title": "安达与岛村"}])
    results = [m async for m in plugin.unsubscribe_manga(_event("/漫画 取消订阅 ID:9"), "ID:9")]
    plugin.sub_mgr.unsubscribe.assert_not_awaited()
    assert "未找到该订阅" in results[0] and "ID:9" in results[0]
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_unsubscribe.py -v`
Expected: FAIL（`ID:151` 未被识别 → `unsubscribe` 未被调用 / 误报成功）

- [ ] **Step 3: 实现**

`unsubscribe_manga` 改为：

1. `kind, value = parse_manga_ref(manga_id_or_name)`。
2. `kind == "index"` → 直接 `yield "取消订阅不支持搜索结果编号，请用 ID:{value} 或订阅名称。"` 并 return。
3. `kind == "id"` → `manga_id = int(value)`；`kind == "name"` → 原订阅名子串匹配（`normalize_zh`）。
4. 取 `subs = await self.sub_mgr.get_subscriptions(umo)`，确认 `manga_id` 在其中；不在 → `未找到该订阅（ID:{manga_id}），可用「漫画 我的订阅」查看。` 并 return。
5. `await self.sub_mgr.unsubscribe(manga_id, umo)` → `✅ 已取消订阅（ID:{manga_id}）。`

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_unsubscribe.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add main.py tests/test_unsubscribe.py
git commit -m "feat(unsubscribe): 只认 ID: 前缀与订阅名称，未订阅时明确报错"
```

---

### Task 5: 文案与帮助统一 `ID:数字`

**Files:**
- Modify: `main.py`（帮助文本、`阅读`/`下载` 用法提示与 docstring、`我的订阅` 文本与卡片 detail、搜索文本尾部、`取消订阅` docstring）
- Test: `tests/test_help.py`、`tests/test_card_commands.py`

**Interfaces:**
- Consumes: Task 2/4 的 `ID:` 文案形态。

- [ ] **Step 1: 写失败测试**

`tests/test_help.py` 追加/修改：

```python
def test_help_documents_search_index_reference():
    help_text = _help_text()
    assert "ID:151" in help_text or "ID:123" in help_text
    assert "搜索" in help_text and "编号" in help_text
    assert "10 分钟" in help_text
```

`tests/test_card_commands.py` 追加文本回退断言（复用 `_plugin`/`_event`）：

```python
@pytest.mark.asyncio
async def test_my_subscriptions_text_uses_parseable_id(monkeypatch):
    plugin = _plugin(cards_enabled=False)
    plugin.sub_mgr.get_subscriptions = AsyncMock(return_value=[
        {"manga_id": 151, "title": "安达与岛村", "source_id": 2, "push_enabled": False},
    ])
    plugin.client.get_sources = AsyncMock(return_value=[_source()])
    results = [msg async for msg in plugin.my_subscriptions(_event())]
    assert "ID:151" in results[0] and "ID: 151" not in results[0]
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_help.py tests/test_card_commands.py -k "search_index_reference or parseable_id" -v`
Expected: FAIL

- [ ] **Step 3: 实现**

- 帮助 `📚 阅读与下载`：`<漫画名或ID>` → `<漫画名或 ID:编号>`，并加一行
  `搜索结果的 [编号] 在 10 分钟内可直接用于阅读/章节/下载；漫画 ID 必须写成 ID:151。`
  `🔍 搜索与订阅` 段末补 `结果编号也可用于「漫画 阅读 <编号> <章节>」`。
- `章节`/`阅读`/`下载` 的用法串与 docstring 同步该语法；`阅读` 用法示例保留一条名称示例与一条 `ID:` 示例。
- `my_subscriptions` 文本 `- ID: {id}` → `- ID:{id}`；卡片 `detail` `ID: {id}` → `ID:{id}`。
- 搜索文本模式尾部（`main.py` 排序分支的 `tail`）追加
  `\n编号也可用于「漫画 阅读 <编号> <章节>」（10 分钟内有效）`；卡片 footer 调用处**不改**。
- `取消订阅` docstring：`<ID或名称>` → `<ID:编号或名称>`。

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/test_help.py tests/test_card_commands.py tests/test_list_chapters.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add main.py tests/test_help.py tests/test_card_commands.py
git commit -m "docs(help): 统一漫画引用语法为 ID:数字，并说明搜索编号可直接阅读"
```

---

### Task 6: 文档、变更日志与版本号

**Files:**
- Modify: `README.md`、`docs/dev/development.md`、`CHANGELOG.md`、`metadata.yaml`

**Interfaces:**
- Consumes: Task 1-5 的最终行为。

- [ ] **Step 1: 更新 README**

命令表中 `章节`/`阅读`/`下载` 的参数改为 `<漫画名或 ID:编号>`；`取消订阅` 改为 `<ID:编号或名称>`；在 `<章节选择>` 说明块后补一段：

```
> 搜索结果的 [编号] 在 10 分钟内可用于章节/阅读/下载（与订阅共用编号）。
> 漫画 ID 必须写成 ID:151；纯数字一律按搜索结果编号解释。
```

并在注意事项里说明纯数字标题（如《86》）：先用「漫画 搜索」拿编号，或用 `ID:数字`。

- [ ] **Step 2: 更新开发文档**

`docs/dev/development.md`「按名称解析（不属于检索链）」段落改写为「漫画引用解析」：
`parse_manga_ref` 的三分类、`resolve_manga` 的 `index_lookup` 注入、编号 600s/仅展示条数、
`取消订阅` 例外，以及检索机制图末尾的编号行（`订阅` → `订阅/章节/阅读/下载`）。

- [ ] **Step 3: CHANGELOG 与版本**

`CHANGELOG.md` 的 `[Unreleased]` 写入：

```markdown
### Changed

- **破坏性：漫画 ID 必须写作 `ID:数字`** — 裸数字改为表示「最近一次搜索的结果编号」，
  并放宽到 `/漫画 章节`、`/漫画 阅读`、`/漫画 下载`（与 `/漫画 订阅` 共用，600 秒内有效）；
  编号未命中时按「ID 存在 / 越界 / 无有效搜索」给出可复制下一步，`取消订阅` 同步只认 `ID:` 与名称
```

`metadata.yaml` 版本 `0.7.3` → `0.8.0`。

- [ ] **Step 4: 全量验证**

Run: `uv run pytest -v`
Expected: 全部 PASS（live 用例无服务器时自动 skip）

- [ ] **Step 5: 提交**

```bash
git add README.md docs/dev/development.md CHANGELOG.md metadata.yaml
git commit -m "docs: 0.8.0 漫画引用语法与搜索编号说明"
```

---

### Task 7: 整体自检

**Files:** 无新增

- [ ] **Step 1: 语法检查**

Run: `python -c "import ast; ast.parse(open('main.py', encoding='utf-8').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 2: 全量测试 + 帮助文本一致性**

Run: `uv run pytest -v`
Expected: PASS

- [ ] **Step 3: 手工核对 spec 的「用户可见行为」表**

逐行确认：`ID:` 变体、裸数字、名称、越界、过期、`取消订阅` 例外、卡片 footer 未改、
`我的订阅`/多结果清单均为 `ID:数字`。发现偏差回到对应任务修复，不新建任务。
