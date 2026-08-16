# 指令结果卡片化（T2I 渲染）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 AstrBot 的 T2I 服务把 6 类指令结果渲染为 440px 宽、带封面的卡片，失败/关闭时回退现有纯文本。

**Architecture:** 新增 `suwayomi/cards.py`（纯函数 + 依赖注入）：Jinja2 模板字符串 + 数据准备函数 + `embed_covers`（并发下载封面→PIL 压缩→base64 嵌入）+ `render_card`（超时包裹）+ `CardCache`（TTL 缓存）。命令层在 `main.py`/`suwayomi/updater.py` 通过统一套路接入：开关开→嵌入封面→渲染→成功发图 / 失败回退文本。

**Tech Stack:** Python 3.12、asyncio、aiohttp、Pillow（封面压缩）、AstrBot `html_render`（远程 T2I，服务端原生 Jinja2）、pytest + pytest-asyncio。

---

## 设计细化（相对 spec 的明确化）

1. `build_*` 数据准备函数只返回 `tmpldata`（不返回 fallback_text）：现有命令/updater 已经在生成文本内容，回退文本直接复用既有代码路径，避免重复拼装逻辑。
2. 章节卡行顺序与现有文本一致（`source_order` 升序）；mockup 中的 #253 置顶仅为示意。
3. `/漫画 更新` 的 summary 返回保持文本（`check_updates` 返回类型不变，既有测试零改动）；卡片仅用于**推送到会话的更新通知**。
4. `html_render(return_url=False)` 的输出经 `save_temp_img` 落在共享的 AstrBot 临时目录（单文件，不可 rmtree 父目录），新增 `schedule_cleanup_file()` 单文件清理。
5. 章节卡分块常量：`CHAPTER_LINES_PER_CARD = 130`、`MAX_CHAPTER_CARDS = 4`（440px 宽、1400px 高预算）。

## 文件结构

| 文件 | 责任 | 操作 |
| --- | --- | --- |
| `suwayomi/cards.py` | 模板 + 数据准备 + 封面嵌入 + 渲染 + 缓存 | 新建 |
| `tests/test_cards.py` | cards.py 纯单测 | 新建 |
| `tests/test_card_commands.py` | 搜索/订阅确认/我的订阅命令接入回归 | 新建 |
| `tests/test_list_chapters.py` | 章节命令卡片路径回归 | 修改 |
| `tests/test_updater.py` | 更新通知卡片路径回归 | 修改 |
| `utils/pusher.py` | 新增 `schedule_cleanup_file()` | 修改 |
| `main.py` | 5 处命令接入 + `_card_cache` + `_render_card_result` + `_build_check_updates_fn` 绑定 | 修改 |
| `suwayomi/updater.py` | `check_updates` 注入 `render_update_card_fn`，`_check_one_manga` 透传 manga 对象 | 修改 |
| `_conf_schema.json` | 新增 2 个配置项 | 修改 |
| `requirements.txt` | 新增 `pillow` | 修改 |
| `CHANGELOG.md` | 记录新功能 | 修改 |

---

## Task 1: `suwayomi/cards.py` — 模板与数据准备函数

**Files:**
- Create: `suwayomi/cards.py`
- Test: `tests/test_cards.py`

- [ ] **Step 1: 写失败测试** `tests/test_cards.py`（数据准备与分块部分）

```python
"""Unit tests for suwayomi/cards.py (no network)."""
import math

import pytest

from suwayomi.cards import (
    CHAPTER_LINES_PER_CARD,
    MAX_CHAPTER_CARDS,
    build_batch_card,
    build_chapter_cards,
    build_search_card,
    build_subscribe_confirm_card,
    build_update_card,
)


def _manga(title="咒术回战", status="ONGOING", thumbnail="/api/v1/manga/1/thumbnail"):
    return {"title": title, "status": status, "thumbnail_url": thumbnail}


def test_build_search_card_escapes_and_numbers_rows():
    data = build_search_card(
        [
            {"index": 1, "title": "咒术回战", "status": "ONGOING", "source": "拷贝漫画", "thumbnail_url": "/a"},
            {"index": 2, "title": "鬼灭<之刃", "status": "COMPLETED", "source": "拷贝漫画", "thumbnail_url": "/b"},
        ],
        subtitle="拷贝漫画 · 2 条",
        footer="回复「漫画 订阅 <编号>」订阅",
    )
    assert data["card_type"] == "search"
    assert data["rows"][0]["index"] == 1
    assert data["rows"][0]["detail"] == "连载中 · 拷贝漫画"
    assert data["rows"][1]["title"] == "鬼灭&lt;之刃"
    assert data["footer"] == "回复「漫画 订阅 &lt;编号&gt;」订阅"
    # thumbnail_url 原样保留供 embed_covers 使用
    assert data["rows"][0]["thumbnail_url"] == "/a"


def test_build_subscribe_confirm_card():
    data = build_subscribe_confirm_card(
        {"title": "鬼灭之刃", "status": "COMPLETED", "thumbnail_url": "/c"},
        source_name="拷贝漫画",
        footer="有新章节时会推送通知",
    )
    assert data["card_type"] == "confirm"
    assert data["title"] == "鬼灭之刃"
    assert data["status"] == "已完结"
    assert data["status_class"] == "status-completed"
    assert "ID" in data["meta"] and "拷贝漫画" in data["meta"]


def test_build_update_card_multi():
    data = build_update_card(
        [
            {"title": "咒术回战", "status": "ONGOING", "chapters": ["#251 新的一页", "#252 决战"],
             "read_hint": "「漫画 阅读 咒术回战 252」", "thumbnail_url": "/d"},
            {"title": "鬼灭之刃", "status": "COMPLETED", "chapters": ["#205"],
             "read_hint": "「漫画 阅读 鬼灭之刃 205」", "thumbnail_url": "/e"},
        ],
        heading="📢 2 部漫画更新了",
    )
    assert data["heading"] == "📢 2 部漫画更新了"
    assert data["items"][0]["status"] == "连载中"
    assert data["items"][1]["status_class"] == "status-completed"
    assert data["items"][0]["chapters"][0] == "#251 新的一页"


def test_build_batch_card_marks():
    data = build_batch_card(
        [
            {"status": "ok", "title": "咒术回战", "detail": "连载中 - 拷贝漫画", "thumbnail_url": "/f"},
            {"status": "exists", "title": "鬼灭之刃", "detail": "已完结 - 拷贝漫画（已订阅）", "thumbnail_url": "/g"},
            {"status": "fail", "title": "海贼王", "detail": "未找到匹配结果", "thumbnail_url": None},
        ],
        summary="1 新增, 1 已存在, 1 失败",
    )
    icons = {row["icon"] for row in data["rows"]}
    assert icons == {"✓", "⏭", "✕"}
    assert {row["mark_class"] for row in data["rows"]} == {"mark-ok", "mark-skip", "mark-fail"}
    assert data["rows"][2]["thumbnail_url"] is None


def test_build_chapter_cards_single_header_only():
    cards, tail = build_chapter_cards(
        {"title": "咒术回战", "cover_data_url": None, "meta": "拷贝漫画 · 3 话",
         "tags": ["连载中"], "hint": "「漫画 章节 咒术回战 --刷新」"},
        ["#1", "#2", "#3"],
    )
    assert len(cards) == 1
    assert tail == []
    assert cards[0]["is_continuation"] is False
    # 三列
    assert len(cards[0]["chunks"]) == 3
    assert sum(len(c) for c in cards[0]["chunks"]) == 3
    # 章节行 HTML 转义
    assert cards[0]["title"] == "咒术回战"


def test_build_chapter_cards_chunks_by_constant():
    lines = [f"#{i} 章" for i in range(1, CHAPTER_LINES_PER_CARD * 2 + 1)]
    cards, tail = build_chapter_cards({"title": "X", "cover_data_url": None}, lines)
    assert len(cards) == 2
    assert tail == []
    assert cards[1]["is_continuation"] is True
    assert cards[1]["continuation"] == "章节续 (2/2)"
    # 每张卡的行数不超过 per-card 常量
    for card in cards:
        total = sum(len(c) for c in card["chunks"])
        assert total <= CHAPTER_LINES_PER_CARD


def test_build_chapter_cards_tail_and_cap():
    lines = [f"#{i}" for i in range(1, CHAPTER_LINES_PER_CARD * (MAX_CHAPTER_CARDS + 1) + 10)]
    cards, tail = build_chapter_cards({"title": "X", "cover_data_url": None}, lines)
    assert len(cards) == MAX_CHAPTER_CARDS
    assert len(tail) == len(lines) - CHAPTER_LINES_PER_CARD * MAX_CHAPTER_CARDS


def test_build_chapter_cards_escapes_lines():
    lines = ["#1 章 & 节", "#2 <b>x</b>"]
    cards, tail = build_chapter_cards({"title": "X", "cover_data_url": None}, lines)
    flat = [line for col in cards[0]["chunks"] for line in col]
    assert "章 &amp; 节" in flat[0]
    assert "<b>" not in "".join(flat)
    # tail 返回原始行（用于纯文本，不转义）
    cards2, tail2 = build_chapter_cards({"title": "X", "cover_data_url": None}, ["#1 & x"] * 600)
    assert tail2 == ["#1 & x"] * (600 - CHAPTER_LINES_PER_CARD * MAX_CHAPTER_CARDS)


def test_build_chapter_cards_empty_lines_returns_header():
    cards, tail = build_chapter_cards({"title": "X", "cover_data_url": None}, [])
    assert len(cards) == 1
    assert tail == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_cards.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'suwayomi.cards'`）

- [ ] **Step 3: 实现 `suwayomi/cards.py`（模板 + 数据准备 + 分块）**

```python
"""Render command results as HTML cards via AstrBot's remote T2I service.

The HTML template is rendered by the remote T2I endpoint (Jinja2 natively),
so this module only prepares data and never renders locally. All pure data
preparation lives here for testability; network work (cover download) is
delegated to utils.downloader via ``embed_covers``.
"""
from __future__ import annotations

import html
import math

from . import PLUGIN_NAME
from .service import STATUS_EMOJI

CARD_WIDTH = 440
COVER_WIDTH = 120
CHAPTER_LINES_PER_CARD = 130
MAX_CHAPTER_CARDS = 4

_PLUGIN_NAME = PLUGIN_NAME


def _status_pill_class(status: str) -> str:
    if status == "ONGOING":
        return "status-ongoing"
    if status in ("COMPLETED", "PUBLISHING_FINISHED"):
        return "status-completed"
    return "status-default"


CARD_TEMPLATE = """
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: "PingFang SC","Microsoft YaHei",sans-serif; background:#f8f9fb;
         padding:14px; color:#1a1d29; }
  .title { font-size:17px; font-weight:700; margin-bottom:10px; }
  .title .sub { font-size:12px; color:#8a8f9d; font-weight:400; }
  .card { background:#fff; border-radius:10px; padding:8px 10px; display:flex;
          align-items:center; gap:10px; box-shadow:0 1px 3px rgba(0,0,0,.05); }
  .card + .card { margin-top:8px; }
  .cover { border-radius:5px; object-fit:cover; flex-shrink:0; background:#e4e6ec; }
  .cover-placeholder { display:flex; align-items:center; justify-content:center;
                       color:#b0b5c3; font-size:16px; }
  .badge { min-width:20px; height:20px; border-radius:50%; background:#4f7cff;
           color:#fff; font-size:12px; font-weight:600; display:flex;
           align-items:center; justify-content:center; flex-shrink:0; }
  .mark { min-width:20px; height:20px; border-radius:50%; color:#fff; font-size:12px;
          display:flex; align-items:center; justify-content:center; flex-shrink:0; }
  .mark-ok { background:#3ecf6a; }
  .mark-skip { background:#f2b33d; }
  .mark-fail { background:#ef5350; }
  .body { flex:1; min-width:0; }
  .body .name { font-size:15px; font-weight:600; white-space:nowrap; overflow:hidden;
                text-overflow:ellipsis; }
  .body .meta { font-size:12px; color:#8a8f9d; margin-top:2px; }
  .footer { font-size:12px; color:#8a8f9d; text-align:center; margin-top:10px; }
  .chip { display:inline-block; background:#eef3ff; color:#4f7cff; font-size:12px;
          padding:3px 8px; border-radius:6px; margin:3px 3px 0 0; }
  .manga-card { background:#fff; border-radius:12px; padding:12px; display:flex;
                gap:12px; box-shadow:0 1px 3px rgba(0,0,0,.05); }
  .manga-card + .manga-card { margin-top:8px; }
  .manga-cover { border-radius:6px; object-fit:cover; flex-shrink:0; background:#e4e6ec; }
  .manga-body { flex:1; min-width:0; display:flex; flex-direction:column; }
  .manga-name { font-size:15px; font-weight:700; }
  .status-pill { font-size:10px; padding:1px 6px; border-radius:20px; margin-left:2px;
                 vertical-align:1px; }
  .status-ongoing { background:#eef3ff; color:#4f7cff; }
  .status-completed { background:#eef5ec; color:#3e9c4f; }
  .status-default { background:#f2f3f7; color:#6b7180; }
  .hint { font-size:11px; color:#8a8f9d; margin-top:6px; }
  .hint.pushed { margin-top:auto; padding-top:10px; }
  .cols { display:flex; gap:8px; margin-top:8px; }
  .col { flex:1; background:#fff; border-radius:8px; padding:8px; font-family:Consolas,monospace;
         font-size:12px; color:#3a3f4b; line-height:1.8; }
  .mini-head { display:flex; align-items:center; gap:10px; background:#fff; border-radius:10px;
               padding:8px 12px; box-shadow:0 1px 3px rgba(0,0,0,.05); }
  .mini-title { font-size:14px; font-weight:700; }
  .mini-title .cont { font-size:11px; color:#8a8f9d; font-weight:400; }
</style>

<body>
{% if card_type == "search" %}
  <div class="title">🔍 搜索结果 <span class="sub">（{{ subtitle }}）</span></div>
  {% for row in rows %}
  <div class="card">
    <div class="badge">{{ row.index }}</div>
    {% if row.cover_data_url %}
      <img class="cover" style="width:44px;height:60px" src="{{ row.cover_data_url }}">
    {% else %}
      <div class="cover cover-placeholder" style="width:44px;height:60px">?</div>
    {% endif %}
    <div class="body">
      <div class="name">{{ row.title }}</div>
      <div class="meta">{{ row.detail }}</div>
    </div>
  </div>
  {% endfor %}
  <div class="footer">{{ footer }}</div>

{% elif card_type == "confirm" %}
  <div class="manga-card">
    {% if cover_data_url %}
      <img class="manga-cover" style="width:120px;height:168px" src="{{ cover_data_url }}">
    {% else %}
      <div class="manga-cover cover-placeholder" style="width:120px;height:168px">?</div>
    {% endif %}
    <div class="manga-body">
      <div style="font-size:22px;font-weight:700">✅ 订阅成功</div>
      <div style="font-size:16px;font-weight:600;margin-top:6px">{{ title }}</div>
      <div class="meta" style="margin-top:2px">{{ meta }}</div>
      <div style="margin-top:6px"><span class="status-pill {{ status_class }}">{{ status }}</span></div>
      <div class="hint pushed">{{ footer }}</div>
    </div>
  </div>

{% elif card_type == "batch" %}
  <div class="title">📚 批量订阅完成 <span class="sub">（{{ summary }}）</span></div>
  {% for row in rows %}
  <div class="card">
    <div class="mark {{ row.mark_class }}">{{ row.icon }}</div>
    {% if row.cover_data_url %}
      <img class="cover" style="width:44px;height:60px" src="{{ row.cover_data_url }}">
    {% else %}
      <div class="cover cover-placeholder" style="width:44px;height:60px">?</div>
    {% endif %}
    <div class="body">
      <div class="name">{{ row.title }}</div>
      <div class="meta">{{ row.detail }}</div>
    </div>
  </div>
  {% endfor %}

{% elif card_type == "update" %}
  <div class="title">{{ heading }}</div>
  {% for item in items %}
  <div class="manga-card">
    {% if item.cover_data_url %}
      <img class="manga-cover" style="width:72px;height:100px" src="{{ item.cover_data_url }}">
    {% else %}
      <div class="manga-cover cover-placeholder" style="width:72px;height:100px">?</div>
    {% endif %}
    <div class="manga-body">
      <div class="manga-name">{{ item.title }}
        <span class="status-pill {{ item.status_class }}">{{ item.status }}</span>
      </div>
      <div>{% for ch in item.chapters %}<span class="chip">{{ ch }}</span>{% endfor %}</div>
      <div class="hint">{{ item.read_hint }}</div>
    </div>
  </div>
  {% endfor %}

{% elif card_type == "chapter" %}
  {% if not is_continuation %}
  <div class="manga-card">
    {% if cover_data_url %}
      <img class="manga-cover" style="width:100px;height:140px" src="{{ cover_data_url }}">
    {% else %}
      <div class="manga-cover cover-placeholder" style="width:100px;height:140px">?</div>
    {% endif %}
    <div class="manga-body">
      <div style="font-size:17px;font-weight:700">{{ title }}</div>
      <div class="meta" style="margin-top:3px">{{ meta }}</div>
      <div style="margin-top:8px">{% for t in tags %}<span class="status-pill {{ t.class }}">{{ t.text }}</span>{% endfor %}</div>
      <div class="hint" style="margin-top:8px">{{ hint }}</div>
    </div>
  </div>
  {% else %}
  <div class="mini-head">
    {% if cover_data_url %}
      <img class="cover" style="width:36px;height:50px" src="{{ cover_data_url }}">
    {% else %}
      <div class="cover cover-placeholder" style="width:36px;height:50px">?</div>
    {% endif %}
    <div class="mini-title">{{ title }} <span class="cont">{{ continuation }}</span></div>
  </div>
  {% endif %}
  {% if chunks %}
  <div class="cols">
    {% for col in chunks %}
    <div class="col">{% for line in col %}{{ line }}{% if not loop.last %}<br>{% endif %}{% endfor %}</div>
    {% endfor %}
  </div>
  {% endif %}
{% endif %}
</body>
"""


def build_search_card(rows: list[dict], subtitle: str, footer: str) -> dict:
    """rows: [{index, title, status, source, thumbnail_url}]."""
    cleaned = []
    for r in rows:
        status = STATUS_EMOJI.get(r["status"], "未知")
        cleaned.append({
            "index": r["index"],
            "title": html.escape(r["title"]),
            "detail": html.escape(f"{status} · {r['source']}"),
            "thumbnail_url": r.get("thumbnail_url"),
        })
    return {
        "card_type": "search",
        "subtitle": html.escape(subtitle),
        "rows": cleaned,
        "footer": html.escape(footer),
    }


def build_subscribe_confirm_card(manga: dict, source_name: str, footer: str) -> dict:
    """manga: {title, status, thumbnail_url}."""
    status = STATUS_EMOJI.get(manga["status"], "未知")
    meta = f"ID: {manga.get('id', '?')}" + (f" · 源: {source_name}" if source_name else "")
    return {
        "card_type": "confirm",
        "title": html.escape(manga["title"]),
        "meta": html.escape(meta),
        "status": status,
        "status_class": _status_pill_class(manga["status"]),
        "footer": html.escape(footer),
        "thumbnail_url": manga.get("thumbnail_url"),
    }


def build_update_card(items: list[dict], heading: str) -> dict:
    """items: [{title, status, chapters, read_hint, thumbnail_url}]."""
    cleaned = []
    for it in items:
        cleaned.append({
            "title": html.escape(it["title"]),
            "status": STATUS_EMOJI.get(it.get("status", "UNKNOWN"), "未知"),
            "status_class": _status_pill_class(it.get("status", "UNKNOWN")),
            "chapters": [html.escape(c) for c in it["chapters"]],
            "read_hint": html.escape(it["read_hint"]),
            "thumbnail_url": it.get("thumbnail_url"),
        })
    return {"card_type": "update", "heading": html.escape(heading), "items": cleaned}


def build_batch_card(rows: list[dict], summary: str) -> dict:
    """rows: [{status: ok|exists|fail, title, detail, thumbnail_url}]."""
    mark_map = {"ok": ("✓", "mark-ok"), "exists": ("⏭", "mark-skip"), "fail": ("✕", "mark-fail")}
    cleaned = []
    for r in rows:
        icon, mark_class = mark_map.get(r["status"], ("✕", "mark-fail"))
        cleaned.append({
            "icon": icon,
            "mark_class": mark_class,
            "title": html.escape(r["title"]),
            "detail": html.escape(r["detail"]),
            "thumbnail_url": r.get("thumbnail_url"),
        })
    return {"card_type": "batch", "summary": html.escape(summary), "rows": cleaned}


def _split_columns(lines: list[str], n: int = 3) -> list[list[str]]:
    return [lines[i::n] for i in range(n)]


def build_chapter_cards(manga: dict, lines: list[str]) -> tuple[list[dict], list[str]]:
    """Split chapter lines into card tmpldata list plus raw tail text lines.

    ``manga`` must already carry ``cover_data_url`` (from ``embed_covers``).
    Chapter ``lines`` are the same strings used for the text fallback (raw,
    NOT escaped); this function HTML-escapes the ones placed into cards and
    returns the unescaped overflow as ``tail``.
    """
    safe_lines = [html.escape(line) for line in lines]
    per_card = CHAPTER_LINES_PER_CARD
    if not lines:
        card_count = 1
    else:
        card_count = min(MAX_CHAPTER_CARDS, math.ceil(len(lines) / per_card))
    tail = lines[card_count * per_card:] if lines else []

    tags = [
        {"text": html.escape(t["text"]), "class": t.get("class", "status-default")}
        for t in manga.get("tags", [])
    ]
    base = {
        "card_type": "chapter",
        "cover_data_url": manga.get("cover_data_url"),
        "title": html.escape(manga["title"]),
    }
    cards = []
    for i in range(card_count):
        card_lines = safe_lines[i * per_card:(i + 1) * per_card]
        chunks = _split_columns(card_lines)
        if i == 0:
            card = dict(base, is_continuation=False)
            card["meta"] = html.escape(manga.get("meta", ""))
            card["tags"] = tags
            card["hint"] = html.escape(manga.get("hint", ""))
            card["chunks"] = chunks
        else:
            card = dict(base, is_continuation=True)
            card["continuation"] = f"章节续 ({i + 1}/{card_count})"
            card["chunks"] = chunks
        cards.append(card)
    return cards, tail
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_cards.py -v`
Expected: PASS（11 passed）

- [ ] **Step 5: 提交**

```bash
git add suwayomi/cards.py tests/test_cards.py
git commit -m "feat: add card template and data prep functions"
```

---

## Task 2: `embed_covers`（封面下载 → PIL 压缩 → base64）

**Files:**
- Modify: `suwayomi/cards.py`
- Test: `tests/test_cards.py`

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_cards.py`）

```python
from unittest.mock import AsyncMock, MagicMock, patch

from suwayomi.cards import COVER_WIDTH, embed_covers, resolve_cover_url


class FakeClient:
    def __init__(self):
        self.server_url = "http://localhost:4567"
        self.auth_headers = {"Authorization": "Bearer tok"}

    def build_image_url(self, rel):
        return f"{self.server_url}{rel}"


def _pillow_cover(path):
    # 生成一张 300x400 的 JPEG 用于压缩验证
    from PIL import Image
    img = Image.new("RGB", (300, 400), (200, 100, 50))
    img.save(path, format="JPEG")
    return path


def test_resolve_cover_url_relative_uses_auth():
    client = FakeClient()
    url, headers = resolve_cover_url(client, "/api/v1/manga/1/thumbnail")
    assert url == "http://localhost:4567/api/v1/manga/1/thumbnail"
    assert headers == {"Authorization": "Bearer tok"}


def test_resolve_cover_url_external_no_auth():
    client = FakeClient()
    url, headers = resolve_cover_url(client, "https://cdn.example.com/c.jpg")
    assert url == "https://cdn.example.com/c.jpg"
    assert headers is None


def test_resolve_cover_url_none():
    client = FakeClient()
    assert resolve_cover_url(client, None) == (None, None)


@patch("suwayomi.cards.download_images", new_callable=AsyncMock)
@patch("suwayomi.cards.schedule_cleanup")
async def test_embed_covers_success(mock_cleanup, mock_download, tmp_path):
    cover = tmp_path / "cover.jpg"
    _pillow_cover(str(cover))
    mock_download.return_value = ([str(cover)], tmp_path)
    client = FakeClient()
    items = [{"title": "A", "thumbnail_url": "/a"}, {"title": "B", "thumbnail_url": "/b"}]
    result = await embed_covers(client, items, custom_tmp="", retries=3, concurrency=2)
    assert len(result) == 2
    assert result[0]["cover_data_url"].startswith("data:image/jpeg;base64,")
    assert result[1]["cover_data_url"].startswith("data:image/jpeg;base64,")
    assert "thumbnail_url" not in result[0]
    mock_cleanup.assert_called_once()


@patch("suwayomi.cards.download_images", new_callable=AsyncMock)
@patch("suwayomi.cards.schedule_cleanup")
async def test_embed_covers_partial_failure_placeholder(mock_cleanup, mock_download):
    mock_download.return_value = (["/missing.jpg", ""], MagicMock())
    client = FakeClient()
    result = await embed_covers(client, [{"title": "A", "thumbnail_url": "/a"}], retries=3)
    assert result[0]["cover_data_url"] is None


@patch("suwayomi.cards.download_images", new_callable=AsyncMock)
@patch("suwayomi.cards.schedule_cleanup")
async def test_embed_covers_download_error_no_raise(mock_cleanup, mock_download):
    mock_download.side_effect = OSError("boom")
    client = FakeClient()
    items = [{"title": "A", "thumbnail_url": "/a"}, {"title": "B", "thumbnail_url": "/b"}]
    result = await embed_covers(client, items, retries=3)
    assert all(item["cover_data_url"] is None for item in result)


def test_embed_covers_bad_image_no_raise(tmp_path):
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"not an image")
    assert _cover_data_url(str(bad)) is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_cards.py -v`
Expected: FAIL（`ImportError` / `NameError: name 'embed_covers' is not defined`）

- [ ] **Step 3: 实现**（追加到 `suwayomi/cards.py`）

在文件顶部 import 增加（保持 `utils.pusher` 为函数级 import，避免模块级循环）：

```python
import asyncio
import base64
import time
from urllib.parse import urlparse
from typing import TYPE_CHECKING, Any

from astrbot.api import logger

if TYPE_CHECKING:
    from ..utils.downloader import download_images
```

并在 `CARD_TEMPLATE` 之后追加：

```python
def resolve_cover_url(client: Any, thumbnail_url: str | None) -> tuple[str | None, dict | None]:
    """Resolve a Suwayomi thumbnail URL to a fetchable URL plus auth headers.

    Mirrors utils.downloader.download_cover's same-origin policy: relative
    paths always carry auth headers; absolute URLs only when same-origin
    (avoid leaking credentials to third-party hosts).
    """
    if not thumbnail_url:
        return None, None
    if thumbnail_url.startswith(("http://", "https://")):
        url = thumbnail_url
        use_headers = None
        server = urlparse(client.server_url) if client.server_url else None
        if server:
            target = urlparse(thumbnail_url)
            server_port = server.port or (443 if server.scheme == "https" else 80 if server.scheme == "http" else None)
            target_port = target.port or (443 if target.scheme == "https" else 80 if target.scheme == "http" else None)
            if (
                server.scheme == target.scheme
                and server.hostname == target.hostname
                and server_port == target_port
            ):
                use_headers = client.auth_headers
    else:
        url = client.build_image_url(thumbnail_url)
        use_headers = client.auth_headers
    return url, use_headers


def _cover_data_url(path: str) -> str | None:
    """Downscale a local cover to a JPEG base64 data URL (or None on failure)."""
    try:
        from io import BytesIO

        from PIL import Image

        img = Image.open(path)
        img = img.convert("RGB")
        width = COVER_WIDTH
        height = max(1, round(img.height * width / img.width))
        img = img.resize((width, height), Image.LANCZOS)
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=80)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return None


async def embed_covers(
    client: Any,
    items: list[dict],
    custom_tmp: str = "",
    retries: int = 3,
    concurrency: int = 6,
) -> list[dict]:
    """Download covers in parallel and attach ``cover_data_url`` to each item.

    Returns new dicts (originals untouched). ``cover_data_url`` is None when
    the cover is missing or failed — the template renders a placeholder.
    """
    from ..utils.downloader import download_images
    from ..utils.pusher import schedule_cleanup

    resolved = []
    for item in items:
        url, use_headers = resolve_cover_url(client, item.get("thumbnail_url"))
        resolved.append((item, url, use_headers))

    grouped: dict[tuple, list[tuple[int, str]]] = {}
    for idx, (_item, url, use_headers) in enumerate(resolved):
        key = tuple(sorted((use_headers or {}).items()))
        grouped.setdefault(key, []).append((idx, url))

    covers: dict[int, str | None] = {}
    for key, entries in grouped.items():
        urls = [url for _, url in entries]
        if not urls:
            continue
        headers = dict(key) or None
        try:
            paths, tmp_dir = await download_images(
                urls, concurrency=concurrency, custom_tmp=custom_tmp,
                retries=retries, headers=headers,
            )
        except Exception as exc:
            logger.warning(f"[{_PLUGIN_NAME}] 封面批量下载失败: {exc}")
            for idx, _ in entries:
                covers[idx] = None
            continue
        for (idx, _), path in zip(entries, paths):
            covers[idx] = _cover_data_url(path) if path else None
        if tmp_dir is not None:
            schedule_cleanup(tmp_dir, delay=60)

    result = []
    for idx, (item, _url, _headers) in enumerate(resolved):
        new_item = dict(item)
        new_item["cover_data_url"] = covers.get(idx)
        new_item.pop("thumbnail_url", None)
        result.append(new_item)
    return result
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_cards.py -v`
Expected: PASS（17 passed）

- [ ] **Step 5: 提交**

```bash
git add suwayomi/cards.py tests/test_cards.py
git commit -m "feat: add cover embed (PIL resize + base64) for cards"
```

---

## Task 3: `render_card` 与 `CardCache`

**Files:**
- Modify: `suwayomi/cards.py`
- Test: `tests/test_cards.py`

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_cards.py`）

```python
import asyncio

from suwayomi.cards import CardCache, render_card, render_card_cached


@pytest.mark.asyncio
async def test_render_card_returns_path():
    async def fake_html_render(tmpl, data, return_url, options):
        return "/tmp/card.jpg"

    path = await render_card(fake_html_render, {"card_type": "search"}, timeout=10)
    assert path == "/tmp/card.jpg"


@pytest.mark.asyncio
async def test_render_card_failure_returns_none():
    async def boom(tmpl, data, return_url, options):
        raise RuntimeError("endpoint down")

    assert await render_card(boom, {"card_type": "search"}, timeout=10) is None


@pytest.mark.asyncio
async def test_render_card_timeout_returns_none():
    async def slow(tmpl, data, return_url, options):
        await asyncio.sleep(5)

    assert await render_card(slow, {"card_type": "search"}, timeout=0.01) is None


def test_card_cache_hit_and_miss():
    cache = CardCache(ttl=600)
    data = {"card_type": "search", "rows": []}
    assert cache.get(data) is None
    cache.put(data, "/a")
    assert cache.get(data) == "/a"
    assert cache.get({"card_type": "search", "rows": [1]}) is None


def test_card_cache_ttl_expiry():
    cache = CardCache(ttl=10)
    data = {"card_type": "search"}
    cache.put(data, "/a", now=100)
    assert cache.get(data, now=105) == "/a"
    assert cache.get(data, now=111) is None


def test_card_cache_key_ignores_key_order():
    cache = CardCache()
    cache.put({"a": 1, "b": 2}, "/x")
    assert cache.get({"b": 2, "a": 1}) == "/x"


def test_card_cache_max_entries_evicts_oldest():
    cache = CardCache(ttl=600, max_entries=2)
    cache.put({"k": 1}, "/1", now=1)
    cache.put({"k": 2}, "/2", now=2)
    cache.put({"k": 3}, "/3", now=3)
    assert cache.get({"k": 1}, now=4) is None
    assert cache.get({"k": 2}, now=4) == "/2"


@pytest.mark.asyncio
async def test_render_card_cached_skips_render_on_hit():
    cache = CardCache(ttl=600)
    calls = 0

    async def fake_html_render(tmpl, data, return_url, options):
        nonlocal calls
        calls += 1
        return "/tmp/card.jpg"

    data = {"card_type": "search"}
    first = await render_card_cached(cache, fake_html_render, data, timeout=10)
    second = await render_card_cached(cache, fake_html_render, data, timeout=10)
    assert first == second == "/tmp/card.jpg"
    assert calls == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_cards.py -v`
Expected: FAIL（`ImportError: cannot import name 'CardCache'`）

- [ ] **Step 3: 实现**（追加到 `suwayomi/cards.py`）

文件顶部 import 增加：

```python
import hashlib
import json
```

在 `embed_covers` 之后追加：

```python
class CardCache:
    """In-memory TTL cache keyed by a stable hash of the tmpldata dict."""

    def __init__(self, ttl: float = 600.0, max_entries: int = 32):
        self._ttl = ttl
        self._max_entries = max_entries
        self._data: dict[str, tuple[float, str]] = {}

    @staticmethod
    def _key(tmpldata: dict) -> str:
        payload = json.dumps(tmpldata, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()

    def get(self, tmpldata: dict, now: float | None = None) -> str | None:
        key = self._key(tmpldata)
        entry = self._data.get(key)
        if entry is None:
            return None
        ts, path = entry
        t = now if now is not None else time.time()
        if t - ts > self._ttl:
            self._data.pop(key, None)
            return None
        return path

    def put(self, tmpldata: dict, path: str, now: float | None = None) -> None:
        key = self._key(tmpldata)
        t = now if now is not None else time.time()
        self._data[key] = (t, path)
        if len(self._data) > self._max_entries:
            oldest = min(self._data, key=lambda k: self._data[k][0])
            self._data.pop(oldest, None)


async def render_card(
    html_render: Any,
    tmpldata: dict,
    options: dict | None = None,
    timeout: float = 30.0,
) -> str | None:
    """Render tmpldata via the injected html_render; return local path or None."""
    opts = {"type": "jpeg", "quality": 85, "viewport_width": CARD_WIDTH}
    if options:
        opts.update(options)
    try:
        return await asyncio.wait_for(
            html_render(CARD_TEMPLATE, tmpldata, return_url=False, options=opts),
            timeout=timeout,
        )
    except Exception as exc:
        logger.warning(f"[{_PLUGIN_NAME}] 卡片渲染失败: {exc}")
        return None


async def render_card_cached(
    cache: CardCache,
    html_render: Any,
    tmpldata: dict,
    options: dict | None = None,
    timeout: float = 30.0,
) -> str | None:
    cached = cache.get(tmpldata)
    if cached:
        return cached
    path = await render_card(html_render, tmpldata, options=options, timeout=timeout)
    if path:
        cache.put(tmpldata, path)
    return path
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_cards.py -v`
Expected: PASS（25 passed）

- [ ] **Step 5: 提交**

```bash
git add suwayomi/cards.py tests/test_cards.py
git commit -m "feat: add render_card and CardCache"
```

---

## Task 4: 配置、依赖与清理助手

**Files:**
- Modify: `_conf_schema.json`
- Modify: `requirements.txt`
- Modify: `utils/pusher.py`
- Test: `tests/test_push.py`

- [ ] **Step 1: 读当前文件确认插入点**

Run: `Get-Content _conf_schema.json | Select-String -Pattern "ai_tool_timeout_sec" -Context 0,6` 和 `Get-Content requirements.txt`

- [ ] **Step 2: 写失败测试**（追加到 `tests/test_push.py`，若文件顶部无 `import asyncio`，先补充 `import asyncio`）

```python
from pathlib import Path

from utils.pusher import schedule_cleanup_file


@pytest.mark.asyncio
async def test_schedule_cleanup_file_deletes_file(tmp_path):
    target = tmp_path / "card.jpg"
    target.write_bytes(b"x")
    schedule_cleanup_file(str(target), delay=0)
    await asyncio.sleep(0.05)
    assert not target.exists()


@pytest.mark.asyncio
async def test_schedule_cleanup_file_none_noop():
    assert schedule_cleanup_file(None) is None
```

- [ ] **Step 3: 运行测试确认失败**

Run: `uv run pytest tests/test_push.py -v`
Expected: FAIL（`ImportError: cannot import name 'schedule_cleanup_file'`）

- [ ] **Step 4: 实现**

**a) `utils/pusher.py`** — 在 `cancel_pending_cleanups` 后追加：

```python
def schedule_cleanup_file(path: str | None, delay: int = 60) -> asyncio.Task | None:
    """Schedule deletion of a single rendered-card image file."""
    if not path:
        return None

    async def _cleanup():
        await asyncio.sleep(delay)
        try:
            Path(path).unlink(missing_ok=True)
        except Exception:
            pass

    task = asyncio.create_task(_cleanup())
    _cleanup_tasks.add(task)
    task.add_done_callback(_cleanup_tasks.discard)
    return task
```

**b) `_conf_schema.json`** — 在 `ai_tool_timeout_sec` 之后追加：

```json
  ,
  "result_cards_enabled": {
    "description": "指令结果卡片渲染",
    "type": "bool",
    "default": true,
    "hint": "使用 T2I 服务把指令结果渲染为带封面的卡片（搜索/订阅/更新通知/章节列表等）；关闭或渲染失败时回退纯文本"
  },
  "card_render_timeout_sec": {
    "description": "卡片渲染超时（秒）",
    "type": "int",
    "default": 30,
    "min": 5,
    "max": 120,
    "hint": "单张卡片渲染的超时上限，超时自动回退纯文本"
  }
```

**c) `requirements.txt`** — 末尾追加：

```
pillow>=10.0.0
```

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/test_push.py -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add _conf_schema.json requirements.txt utils/pusher.py tests/test_push.py
git commit -m "feat: add card config, pillow dep and single-file cleanup helper"
```

---

## Task 5: `main.py` 基础设施（缓存实例 + 渲染助手）

**Files:**
- Modify: `main.py`
- Test: 无（随后续任务）

- [ ] **Step 1: 实现**

**a) imports** — 在现有 `.suwayomi.service` import 附近追加：

```python
from .suwayomi.cards import (
    CardCache,
    build_batch_card,
    build_chapter_cards,
    build_search_card,
    build_subscribe_confirm_card,
    build_update_card,
    embed_covers,
    render_card_cached,
)
```

（注意：`build_subscriptions_card` 在第 8 任务才加入 `cards.py` 并被 import，Task 5 不要引用它，避免中间提交导入失败。）

在 `.utils.pusher` import 中追加 `schedule_cleanup_file`。

**b) 常量**（`_AI_TOOL_REPAIR_KEY` 之后）：

```python
CARD_CACHE_TTL = 600
```

**c) `__init__`** — 在 `self._ai_send_locks` 后追加：

```python
self._card_cache = CardCache(ttl=CARD_CACHE_TTL)
```

**d) 助手方法**（放在 `_set_search_cache` 之后）：

```python
def _result_cards_enabled(self) -> bool:
    return self._config_bool(self.config.get("result_cards_enabled", True), True)

async def _render_card_result(self, tmpldata: dict) -> str | None:
    """Render one card to a local file; return path or None on failure."""
    try:
        timeout = float(self.config.get("card_render_timeout_sec", 30))
    except (TypeError, ValueError):
        timeout = 30.0
    timeout = max(5.0, min(timeout, 120.0))
    path = await render_card_cached(
        self._card_cache, self.html_render, tmpldata, timeout=timeout
    )
    if path:
        schedule_cleanup_file(path, delay=CARD_CACHE_TTL + 60)
    return path
```

- [ ] **Step 2: 语法检查**

Run: `python -c "import ast; ast.parse(open('main.py', encoding='utf-8').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: 全量测试确认无回归**

Run: `uv run pytest tests/test_web_api.py tests/test_ai_service.py tests/test_ai_tools.py -v`
Expected: PASS

- [ ] **Step 4: 提交**

```bash
git add main.py
git commit -m "feat: add card cache instance and render helper to plugin"
```

---

## Task 6: 搜索命令卡片化

**Files:**
- Modify: `main.py`（`search_manga`）
- Test: `tests/test_card_commands.py`（新建）

- [ ] **Step 1: 写失败测试** `tests/test_card_commands.py`

```python
"""Command-level card regression tests (no network)."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from plugin_pkg.main import SuwayomiPlugin
from plugin_pkg.suwayomi.models import Manga, SearchResult, Source


def _plugin(cards_enabled=True):
    plugin = SuwayomiPlugin.__new__(SuwayomiPlugin)
    plugin.client = MagicMock()
    plugin.client.auth_headers = {}
    plugin.sub_mgr = MagicMock()
    plugin.config = {
        "chapter_list_show_cover": True,
        "temp_dir": "",
        "download_retries": 3,
        "result_cards_enabled": cards_enabled,
        "card_render_timeout_sec": 30,
    }
    plugin.get_kv_data = AsyncMock(return_value={})
    plugin.put_kv_data = AsyncMock()
    plugin._search_cache = {}
    return plugin


def _event():
    event = MagicMock()
    event.unified_msg_origin = "aiocqhttp:group:g1"
    event.message_str = "/漫画 搜索 咒术回战"
    event.plain_result = MagicMock(side_effect=lambda text: text)
    event.chain_result = MagicMock(side_effect=lambda chain: chain)
    event.send = AsyncMock()
    return event


def _manga(title, mid):
    return Manga(id=mid, source_id=2, url="", title=title,
                 status="ONGOING", thumbnail_url=f"/api/v1/manga/{mid}/thumbnail")


def _source(name="拷贝漫画"):
    return Source(id="2", name="manga", lang="zh", display_name=name)


def _plugin_with_search(plugin, mangas):
    src = _source()
    plugin.client.get_sources = AsyncMock(return_value=[src])
    plugin.client.search_manga = AsyncMock(
        return_value=SearchResult(mangas=mangas, has_next_page=False)
    )


@pytest.mark.asyncio
async def test_search_cards_disabled_keeps_plain_text(monkeypatch):
    plugin = _plugin(cards_enabled=False)
    _plugin_with_search(plugin, [_manga("咒术回战", 1)])
    event = _event()
    monkeypatch.setattr("plugin_pkg.main.SuwayomiClient", MagicMock())

    results = [msg async for msg in plugin.search_manga(event, "咒术回战")]
    assert len(results) == 1
    assert "搜索结果" in results[0]
    event.plain_result.assert_called_once()
    event.chain_result.assert_not_called()


@pytest.mark.asyncio
async def test_search_cards_render_failure_falls_back_to_text(monkeypatch):
    plugin = _plugin(cards_enabled=True)
    _plugin_with_search(plugin, [_manga("咒术回战", 1)])
    event = _event()
    plugin._render_card_result = AsyncMock(return_value=None)

    results = [msg async for msg in plugin.search_manga(event, "咒术回战")]
    assert len(results) == 1
    assert "搜索结果" in results[0]
    event.plain_result.assert_called_once()
    event.chain_result.assert_not_called()


@pytest.mark.asyncio
async def test_search_cards_success_sends_image(monkeypatch):
    plugin = _plugin(cards_enabled=True)
    _plugin_with_search(plugin, [_manga("咒术回战", 1)])
    event = _event()
    plugin._render_card_result = AsyncMock(return_value="/tmp/card.jpg")
    monkeypatch.setattr("plugin_pkg.main.embed_covers", AsyncMock(side_effect=lambda c, items, **kw: items))

    results = [msg async for msg in plugin.search_manga(event, "咒术回战")]
    assert len(results) == 1
    event.chain_result.assert_called_once()
    event.plain_result.assert_not_called()
    chain = event.chain_result.call_args[0][0]
    assert len(chain) == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_card_commands.py -v`
Expected: FAIL（当前 `search_manga` 无卡片路径）

- [ ] **Step 3: 实现 `search_manga` 卡片路径**

在现有 `search_manga` 中，把「收集结果」循环改为同时收集 `card_rows`（在 `lines.append(...)` 处同步收集），并把 `self._set_search_cache(...)` 与文本 yield 之间的部分改造为：

```python
            text = "\n".join(lines)
            self._set_search_cache(event.unified_msg_origin, cache)

            if self._result_cards_enabled():
                try:
                    card_rows = []
                    for source_name, result in all_results:
                        for m in result.mangas:
                            card_rows.append({
                                "index": len(card_rows) + 1,
                                "title": m.title,
                                "status": m.status,
                                "source": source_name,
                                "thumbnail_url": m.thumbnail_url,
                            })
                    subtitle = f"{' · '.join(dict.fromkeys(source_name for source_name, _ in all_results))} · {len(card_rows)} 条"
                    tmpldata = build_search_card(card_rows, subtitle, "回复「漫画 订阅 编号」订阅，如「漫画 订阅 1」")
                    tmpldata["rows"] = await embed_covers(
                        self.client, tmpldata["rows"],
                        custom_tmp=self.config.get("temp_dir", "").strip(),
                        retries=self.config.get("download_retries", 3),
                        concurrency=self.config.get("download_concurrency", 6),
                    )
                    path = await self._render_card_result(tmpldata)
                    if path:
                        yield event.chain_result([Comp.Image.fromFileSystem(path)])
                        return
                except Exception as e:
                    logger.warning(f"[{_PLUGIN_NAME}] 搜索卡片渲染失败，回退文本: {e}")

            yield event.plain_result(text)
```

注意：原文本路径的 `lines` 构建、`if idx == 1` 提前返回、`self._set_search_cache(...)` 均保持原样；卡片块插在「文本构建完成之后、最终 `yield event.plain_result("\n".join(lines))` 之前」。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_card_commands.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 全量回归**

Run: `uv run pytest tests/test_list_chapters.py tests/test_web_api.py tests/test_ai_service.py -v`
Expected: PASS（未触及这些命令的文本行为；若 `test_ai_service.py` 因 mock 影响失败，检查 `embed_covers` 是否被意外调用——卡片开关未开时应完全走文本路径）

- [ ] **Step 6: 提交**

```bash
git add main.py tests/test_card_commands.py
git commit -m "feat: cardify search results"
```

---

## Task 7: 订阅确认 + 批量订阅卡片化

**Files:**
- Modify: `main.py`（`subscribe_manga`, `batch_subscribe`）
- Test: `tests/test_card_commands.py`

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_card_commands.py`）

```python
@pytest.mark.asyncio
async def test_subscribe_confirm_card_success(monkeypatch):
    plugin = _plugin(cards_enabled=True)
    manga = _manga("咒术回战", 1)
    plugin._get_cached_manga = MagicMock(return_value=manga)
    plugin.sub_mgr.subscribe = AsyncMock()
    plugin.sub_mgr.update_latest_chapter = AsyncMock()
    monkeypatch.setattr(
        "plugin_pkg.main.get_or_fetch_chapters", AsyncMock(return_value=[])
    )
    plugin._render_card_result = AsyncMock(return_value="/tmp/confirm.jpg")
    monkeypatch.setattr(
        "plugin_pkg.main.embed_covers",
        AsyncMock(side_effect=lambda c, items, **kw: [dict(items[0], cover_data_url="data:image/jpeg;base64,AA==")]),
    )
    event = _event()

    results = [msg async for msg in plugin.subscribe_manga(event, "1")]
    assert len(results) == 1
    event.chain_result.assert_called_once()
    event.plain_result.assert_not_called()


@pytest.mark.asyncio
async def test_subscribe_confirm_render_failure_text(monkeypatch):
    plugin = _plugin(cards_enabled=True)
    manga = _manga("咒术回战", 1)
    plugin._get_cached_manga = MagicMock(return_value=manga)
    plugin.sub_mgr.subscribe = AsyncMock()
    plugin.sub_mgr.update_latest_chapter = AsyncMock()
    monkeypatch.setattr(
        "plugin_pkg.main.get_or_fetch_chapters", AsyncMock(return_value=[])
    )
    plugin._render_card_result = AsyncMock(return_value=None)
    event = _event()

    results = [msg async for msg in plugin.subscribe_manga(event, "1")]
    assert len(results) == 1
    assert "已订阅" in results[0]
    event.plain_result.assert_called_once()
    event.chain_result.assert_not_called()


@pytest.mark.asyncio
async def test_batch_subscribe_card_success(monkeypatch):
    plugin = _plugin(cards_enabled=True)
    plugin.client.get_sources = AsyncMock(return_value=[_source()])
    plugin.sub_mgr.get_subscriptions = AsyncMock(return_value=[])
    plugin.sub_mgr.subscribe = AsyncMock()
    plugin.sub_mgr.update_latest_chapter = AsyncMock()
    plugin._render_card_result = AsyncMock(return_value="/tmp/batch.jpg")
    monkeypatch.setattr(
        "plugin_pkg.main.search_best_match",
        AsyncMock(return_value=(_manga("咒术回战", 1), None)),
    )
    monkeypatch.setattr(
        "plugin_pkg.main.get_or_fetch_chapters", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        "plugin_pkg.main.embed_covers",
        AsyncMock(side_effect=lambda c, items, **kw: [dict(i, cover_data_url="x") for i in items]),
    )
    event = _event()
    event.message_str = "/漫画 批量订阅 咒术回战"

    results = [msg async for msg in plugin.batch_subscribe(event)]
    # 卡片成功后仅剩一张图（进度消息通过 event.send 发出）
    final = [r for r in results if r is not None]
    assert event.chain_result.call_count >= 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_card_commands.py -v`
Expected: FAIL（新测试）

- [ ] **Step 3: 实现**

**a) `subscribe_manga`** — 把最后 `yield event.plain_result(f"✅ 已订阅...")` 替换为：

```python
            if self._result_cards_enabled():
                try:
                    tmpldata = build_subscribe_confirm_card(
                        {"id": manga.id, "title": manga.title,
                         "status": manga.status, "thumbnail_url": manga.thumbnail_url},
                        source_name="",
                        footer="有新章节时会推送通知",
                    )
                    card = (await embed_covers(
                        self.client, [tmpldata],
                        custom_tmp=self.config.get("temp_dir", "").strip(),
                        retries=self.config.get("download_retries", 3),
                        concurrency=self.config.get("download_concurrency", 6),
                    ))[0]
                    path = await self._render_card_result(card)
                    if path:
                        yield event.chain_result([Comp.Image.fromFileSystem(path)])
                        return
                except Exception as e:
                    logger.warning(f"[{_PLUGIN_NAME}] 订阅确认卡片渲染失败，回退文本: {e}")
            yield event.plain_result(f"✅ 已订阅「{manga.title}」，有新章节时会推送。")
```

（`source_name` 为空时 meta 不含源名；如需源名可在命令内先 `get_sources` 查，这里保持简洁——空串即不显示。）

**b) `batch_subscribe`** — 收集卡片行并在汇总处渲染：

在循环内 `results.append(...)` 处同时收集 `card_rows`（ok/exists 用 `manga.thumbnail_url`，fail 用 `None`），并在汇总文本构建后追加：

```python
            summary_text = "\n".join(lines)
            if self._result_cards_enabled():
                try:
                    tmpldata = build_batch_card(
                        card_rows,
                        f"{ok_count} 新增, {exist_count} 已存在, {fail_count} 失败",
                    )
                    tmpldata["rows"] = await embed_covers(
                        self.client, tmpldata["rows"],
                        custom_tmp=self.config.get("temp_dir", "").strip(),
                        retries=self.config.get("download_retries", 3),
                        concurrency=self.config.get("download_concurrency", 6),
                    )
                    path = await self._render_card_result(tmpldata)
                    if path:
                        yield event.chain_result([Comp.Image.fromFileSystem(path)])
                        return
                except Exception as e:
                    logger.warning(f"[{_PLUGIN_NAME}] 批量订阅卡片渲染失败，回退文本: {e}")
            yield event.plain_result(summary_text)
```

`card_rows` 在循环中构造，样例：

```python
                if manga.id in existing_ids:
                    ...
                    card_rows.append({"status": "exists", "title": manga.title,
                                      "detail": f"{status_text} - {source_name}（已订阅）",
                                      "thumbnail_url": manga.thumbnail_url})
                    continue
                ...
                card_rows.append({"status": "ok", "title": manga.title,
                                  "detail": f"{status_text} - {source_name}",
                                  "thumbnail_url": manga.thumbnail_url})
                ...
                card_rows.append({"status": "fail", "title": name,
                                  "detail": error or "未找到匹配结果", "thumbnail_url": None})
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_card_commands.py -v`
Expected: PASS（6 passed）

- [ ] **Step 5: 提交**

```bash
git add main.py tests/test_card_commands.py
git commit -m "feat: cardify subscribe confirm and batch subscribe summary"
```

---

## Task 8: 我的订阅卡片化

**Files:**
- Modify: `main.py`（`my_subscriptions`）
- Test: `tests/test_card_commands.py`

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_card_commands.py`）

```python
@pytest.mark.asyncio
async def test_my_subscriptions_card_success(monkeypatch):
    plugin = _plugin(cards_enabled=True)
    plugin.sub_mgr.get_subscriptions = AsyncMock(return_value=[
        {"manga_id": 1, "title": "咒术回战", "source_id": 2, "latest_chapter_id": 5,
         "push_enabled": True},
    ])
    plugin.client.get_sources = AsyncMock(return_value=[_source()])
    plugin.client.get_manga = AsyncMock(return_value=_manga("咒术回战", 1))
    plugin._render_card_result = AsyncMock(return_value="/tmp/subs.jpg")
    monkeypatch.setattr(
        "plugin_pkg.main.embed_covers",
        AsyncMock(side_effect=lambda c, items, **kw: [dict(i, cover_data_url="x") for i in items]),
    )
    event = _event()

    results = [msg async for msg in plugin.my_subscriptions(event)]
    assert len(results) == 1
    event.chain_result.assert_called_once()
    event.plain_result.assert_not_called()


@pytest.mark.asyncio
async def test_my_subscriptions_card_render_failure_text(monkeypatch):
    plugin = _plugin(cards_enabled=True)
    plugin.sub_mgr.get_subscriptions = AsyncMock(return_value=[
        {"manga_id": 1, "title": "咒术回战", "source_id": 2, "latest_chapter_id": 5,
         "push_enabled": True},
    ])
    plugin.client.get_sources = AsyncMock(return_value=[_source()])
    plugin.client.get_manga = AsyncMock(return_value=_manga("咒术回战", 1))
    plugin._render_card_result = AsyncMock(return_value=None)
    event = _event()

    results = [msg async for msg in plugin.my_subscriptions(event)]
    assert len(results) == 1
    assert "订阅列表" in results[0]
    event.plain_result.assert_called_once()
    event.chain_result.assert_not_called()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_card_commands.py -v`
Expected: FAIL（新测试）

- [ ] **Step 3: 实现 `my_subscriptions`**

在命令开头加入卡片路径：封面需先并行 `client.get_manga()` 拉取元数据（失败用存储标题 + 占位封面），再渲染：

```python
            subs = await self.sub_mgr.get_subscriptions(event.unified_msg_origin)
            if not subs:
                yield event.plain_result("📭 你还没有订阅任何漫画。使用「漫画 搜索」来查找并订阅。")
                return
            sources = await self.client.get_sources()
            src_map = {str(s.id): s.display_name for s in sources}

            if self._result_cards_enabled():
                try:
                    metadatas = await asyncio.gather(
                        *(self.client.get_manga(s["manga_id"]) for s in subs),
                        return_exceptions=True,
                    )
                    card_rows = []
                    for s, meta in zip(subs, metadatas):
                        thumbnail = meta.thumbnail_url if not isinstance(meta, Exception) else None
                        status = meta.status if not isinstance(meta, Exception) else "UNKNOWN"
                        src_name = src_map.get(str(s["source_id"]), "")
                        push = "🔔 推送开" if s.get("push_enabled") else "🔕 推送关"
                        tag = f" - {src_name}" if src_name else ""
                        card_rows.append({
                            "title": s["title"],
                            "detail": f"{STATUS_EMOJI.get(status, '未知')}{tag} · {push} · ID: {s['manga_id']}",
                            "thumbnail_url": thumbnail,
                        })
                    tmpldata = build_subscriptions_card(card_rows)
                    tmpldata["rows"] = await embed_covers(
                        self.client, tmpldata["rows"],
                        custom_tmp=self.config.get("temp_dir", "").strip(),
                        retries=self.config.get("download_retries", 3),
                        concurrency=self.config.get("download_concurrency", 6),
                    )
                    path = await self._render_card_result(tmpldata)
                    if path:
                        yield event.chain_result([Comp.Image.fromFileSystem(path)])
                        return
                except Exception as e:
                    logger.warning(f"[{_PLUGIN_NAME}] 订阅列表卡片渲染失败，回退文本: {e}")

            lines = ["📋 你的订阅列表:"]
            for s in subs:
                source_name = src_map.get(str(s["source_id"]), "")
                tag = f" - {source_name}" if source_name else ""
                lines.append(f"  • {s['title']}{tag} - ID: {s['manga_id']}")
            yield event.plain_result("\n".join(lines))
```

**同时**在 `suwayomi/cards.py` 增加 `build_subscriptions_card`，并在 `main.py` 的 `.suwayomi.cards` import 中追加 `build_subscriptions_card`：

```python
def build_subscriptions_card(rows: list[dict]) -> dict:
    """rows: [{title, detail, thumbnail_url}]."""
    cleaned = []
    for r in rows:
        cleaned.append({
            "title": html.escape(r["title"]),
            "detail": html.escape(r["detail"]),
            "thumbnail_url": r.get("thumbnail_url"),
        })
    return {"card_type": "subscriptions", "rows": cleaned}
```

并在 `CARD_TEMPLATE` 中新增一个 `{% elif card_type == "subscriptions" %}` 分支（复用搜索卡行样式）：

```
{% elif card_type == "subscriptions" %}
  <div class="title">📋 你的订阅列表</div>
  {% for row in rows %}
  <div class="card">
    {% if row.cover_data_url %}
      <img class="cover" style="width:44px;height:60px" src="{{ row.cover_data_url }}">
    {% else %}
      <div class="cover cover-placeholder" style="width:44px;height:60px">?</div>
    {% endif %}
    <div class="body">
      <div class="name">{{ row.title }}</div>
      <div class="meta">{{ row.detail }}</div>
    </div>
  </div>
  {% endfor %}
```

**补充** `tests/test_cards.py` 对 `build_subscriptions_card` 的测试：

```python
def test_build_subscriptions_card():
    data = build_subscriptions_card([
        {"title": "咒术回战", "detail": "连载中 - 拷贝漫画 · 🔔 推送开 · ID: 1", "thumbnail_url": "/a"},
    ])
    assert data["card_type"] == "subscriptions"
    assert data["rows"][0]["title"] == "咒术回战"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_card_commands.py tests/test_cards.py -v`
Expected: PASS（新增 2 + 1）

- [ ] **Step 5: 提交**

```bash
git add main.py suwayomi/cards.py tests/test_card_commands.py tests/test_cards.py
git commit -m "feat: cardify my subscriptions"
```

---

## Task 9: 章节列表卡片化（分块多图）

**Files:**
- Modify: `main.py`（`list_chapters`）
- Modify: `tests/test_list_chapters.py`

- [ ] **Step 1: 更新现有测试的配置默认**（防止既有测试误入卡片路径）

`tests/test_list_chapters.py` 的 `_make_plugin` 中 `plugin.config` 增加 `"result_cards_enabled": False`。

- [ ] **Step 2: 写失败测试**（追加到 `tests/test_list_chapters.py`）

```python
@pytest.mark.asyncio
async def test_list_chapters_cards_success_multiple_images(monkeypatch):
    manga = _make_manga()
    chapters = [Chapter(id=i, url="", name=f"第{i}话", chapter_number=float(i),
                        source_order=i, manga_id=1) for i in range(1, 300)]
    plugin = _make_plugin(config={"result_cards_enabled": True})
    event = _make_event()

    monkeypatch.setattr("plugin_pkg.main.resolve_manga", AsyncMock(return_value=(manga, None)))
    monkeypatch.setattr("plugin_pkg.main.get_or_fetch_chapters", AsyncMock(return_value=chapters))
    monkeypatch.setattr(
        "plugin_pkg.main.embed_covers",
        AsyncMock(side_effect=lambda c, items, **kw: [dict(i, cover_data_url="x") for i in items]),
    )
    plugin._render_card_result = AsyncMock(
        side_effect=lambda data: f"/tmp/card{data['title']}.jpg"
    )
    schedule_cleanup_mock = MagicMock()
    monkeypatch.setattr("plugin_pkg.main.schedule_cleanup", schedule_cleanup_mock)

    results = [msg async for msg in plugin.list_chapters(event, "测试漫画")]

    # 多张卡：第一张 chain_result，后续 event.send
    assert event.chain_result.call_count == 1
    assert event.send.await_count == plugin._render_card_result.call_count - 1
    # 尾部文本（300 行超出 2 张卡 × 130）
    assert any("章节续" in str(c) or "章节" in str(c) for c in results)


@pytest.mark.asyncio
async def test_list_chapters_cards_render_failure_falls_back(monkeypatch):
    manga = _make_manga()
    chapters = [Chapter(id=i, url="", name=f"第{i}话", chapter_number=float(i),
                        source_order=i, manga_id=1) for i in range(1, 4)]
    plugin = _make_plugin(config={"result_cards_enabled": True})
    event = _make_event()
    plugin._render_card_result = AsyncMock(return_value=None)
    monkeypatch.setattr("plugin_pkg.main.resolve_manga", AsyncMock(return_value=(manga, None)))
    monkeypatch.setattr("plugin_pkg.main.get_or_fetch_chapters", AsyncMock(return_value=chapters))
    cover_tmp = MagicMock()
    monkeypatch.setattr("plugin_pkg.main.download_cover",
                        AsyncMock(return_value=("/tmp/cover.jpg", cover_tmp)))
    schedule_cleanup_mock = MagicMock()
    monkeypatch.setattr("plugin_pkg.main.schedule_cleanup", schedule_cleanup_mock)

    results = [msg async for msg in plugin.list_chapters(event, "测试漫画")]

    assert len(results) == 1
    assert "章节列表" in results[0]
    event.chain_result.assert_called_once()  # 旧封面+文本路径
```

- [ ] **Step 3: 运行测试确认失败**

Run: `uv run pytest tests/test_list_chapters.py -v`
Expected: 旧测试 PASS（cards 关闭），新测试 FAIL

- [ ] **Step 4: 实现 `list_chapters` 卡片路径**

先确认 `main.py` 已导入 `fmt_chapter_num`（当前未导入）：在 `.suwayomi.service` 的 import 中追加 `fmt_chapter_num`。

在命令中，`chapters.sort(...)` 与分块文本构建之间插入卡片路径（渲染全部成功后发送，否则走旧逻辑）：

```python
            chapters.sort(key=lambda ch: ch.source_order)
            num_count: dict[float, int] = {}
            for ch in chapters:
                num_count[ch.chapter_number] = num_count.get(ch.chapter_number, 0) + 1

            show_cover = self.config.get("chapter_list_show_cover", True)
            if self._result_cards_enabled() and show_cover:
                try:
                    lines_card = []
                    dl_count = 0
                    for ch in chapters:
                        dl_mark = " 📥" if ch.is_downloaded else ""
                        if ch.is_downloaded:
                            dl_count += 1
                        lines_card.append(f"{fmt_chapter_label(ch, num_count)}{dl_mark}")

                    latest = fmt_chapter_num(chapters[-1].chapter_number) if chapters else "?"
                    meta = f"{src_name or '未知源'} · 共 {len(chapters)} 话"
                    if dl_count:
                        meta += f" · 本地 {dl_count}"
                    card_base = {
                        "title": manga.title,
                        "thumbnail_url": manga.thumbnail_url,
                        "meta": meta,
                        "tags": [{"text": f"最近更新 #{latest}"}],
                        "hint": f"「漫画 章节 {manga.title} --刷新」强制刷新",
                    }
                    (card_base,) = await embed_covers(
                        self.client, [card_base],
                        custom_tmp=self.config.get("temp_dir", "").strip(),
                        retries=self.config.get("download_retries", 3),
                        concurrency=self.config.get("download_concurrency", 6),
                    )
                    cards_tmpldata, tail_lines = build_chapter_cards(card_base, lines_card)
                    rendered: list[str] = []
                    for card_data in cards_tmpldata:
                        path = await self._render_card_result(card_data)
                        if path is None:
                            rendered = []
                            break
                        rendered.append(path)
                    if rendered:
                        yield event.chain_result([Comp.Image.fromFileSystem(rendered[0])])
                        for path in rendered[1:]:
                            await event.send(event.chain_result([Comp.Image.fromFileSystem(path)]))
                        if tail_lines:
                            tail_text = "\n".join(tail_lines)
                            if len(tail_text) > 1500:
                                for i in range(0, len(tail_text), 1500):
                                    chunk = tail_text[i:i + 1500]
                                    if i == 0:
                                        yield event.plain_result(chunk)
                                    else:
                                        await event.send(event.plain_result(chunk))
                            else:
                                yield event.plain_result(tail_text)
                        return
                except Exception as e:
                    logger.warning(f"[{_PLUGIN_NAME}] 章节卡片渲染失败，回退旧路径: {e}")
```

说明：`src_name` 需在卡片路径前已解析（现有代码在 `chapters.sort` 后已 `get_sources` 解析 `src_name`）。原文本分块逻辑保留在其后作为回退。

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/test_list_chapters.py tests/test_card_commands.py -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add main.py tests/test_list_chapters.py
git commit -m "feat: cardify chapter list with chunked multi-image cards"
```

---

## Task 10: 更新通知卡片化

**Files:**
- Modify: `suwayomi/updater.py`
- Modify: `main.py`（`_build_check_updates_fn`）
- Modify: `tests/test_updater.py`

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_updater.py`）

```python
import astrbot.api.message_components as Comp
from unittest.mock import patch

from suwayomi.models import Manga


def _update_manga(thumbnail="/api/v1/manga/1/thumbnail"):
    return Manga(id=1, source_id=1, url="", title="T1", status="ONGOING",
                 thumbnail_url=thumbnail)


@pytest.mark.asyncio
async def test_check_updates_sends_card_when_render_fn_succeeds():
    client = CountingClient({1: _chapters(1, [1, 2])})
    client.get_manga = AsyncMock(return_value=_update_manga())
    plugin = FakePlugin()
    sub_mgr = _make_sub_mgr(plugin)
    await sub_mgr.subscribe(1, "T1", 1, "u1")
    await sub_mgr.update_latest_chapter(1, 1)
    ctx = _context()

    async def render_fn(umo, items, heading):
        return "/tmp/update-card.jpg"

    with patch("suwayomi.updater.Comp.Image.fromFileSystem") as mock_img:
        mock_img.return_value = MagicMock()
        summary = await check_updates(
            client, sub_mgr, ctx, _config(),
            plugin.get_kv_data, plugin.put_kv_data, asyncio.Lock(),
            AsyncMock(), AsyncMock(),
            render_update_card_fn=render_fn,
        )
    mock_img.assert_called_once_with("/tmp/update-card.jpg")
    assert ctx.send_message.await_count == 1


@pytest.mark.asyncio
async def test_check_updates_falls_back_to_text_when_render_fails():
    client = CountingClient({1: _chapters(1, [1, 2])})
    client.get_manga = AsyncMock(return_value=_update_manga())
    plugin = FakePlugin()
    sub_mgr = _make_sub_mgr(plugin)
    await sub_mgr.subscribe(1, "T1", 1, "u1")
    await sub_mgr.update_latest_chapter(1, 1)
    ctx = _context()

    async def render_fn(umo, items, heading):
        return None

    with patch("suwayomi.updater.Comp.Image.fromFileSystem") as mock_img:
        mock_img.return_value = MagicMock()
        summary = await check_updates(
            client, sub_mgr, ctx, _config(),
            plugin.get_kv_data, plugin.put_kv_data, asyncio.Lock(),
            AsyncMock(), AsyncMock(),
            render_update_card_fn=render_fn,
        )
    mock_img.assert_not_called()
    assert ctx.send_message.await_count == 1  # 文本消息回退


@pytest.mark.asyncio
async def test_check_updates_build_update_items_include_thumbnail():
    client = CountingClient({1: _chapters(1, [1, 2])})
    client.get_manga = AsyncMock(return_value=_update_manga())
    plugin = FakePlugin()
    sub_mgr = _make_sub_mgr(plugin)
    await sub_mgr.subscribe(1, "T1", 1, "u1")
    await sub_mgr.update_latest_chapter(1, 1)
    ctx = _context()
    seen = {}

    async def render_fn(umo, items, heading):
        seen["items"] = items
        seen["heading"] = heading
        return "/tmp/c.jpg"

    with patch("suwayomi.updater.Comp.Image.fromFileSystem") as mock_img:
        mock_img.return_value = MagicMock()
        await check_updates(
            client, sub_mgr, ctx, _config(),
            plugin.get_kv_data, plugin.put_kv_data, asyncio.Lock(),
            AsyncMock(), AsyncMock(),
            render_update_card_fn=render_fn,
        )
    assert seen["items"][0]["thumbnail_url"] == "/api/v1/manga/1/thumbnail"
    assert seen["items"][0]["title"] == "T1"
    assert seen["items"][0]["status"] == "ONGOING"
```

注意：`CountingClient.get_manga` 默认抛 `SuwayomiError`（`_check_one_manga` 会吞掉并得到 `manga_obj=None`）；测试里必须替换为返回 `_update_manga()` 才能验证 thumbnail/status 透传。

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_updater.py -v`
Expected: FAIL（`check_updates` 不接受 `render_update_card_fn` 关键字参数）

- [ ] **Step 3: 实现 `suwayomi/updater.py`**

**a) 顶部 import** — 追加：

```python
import astrbot.api.message_components as Comp
```

**b) `_check_one_manga`** — 函数签名与返回调整，透传 manga 对象：

- 在 `manga = await client.get_manga(manga_id)` 的 try 中，捕获到对象后保存 `manga_obj = manga`（try 外默认 `manga_obj = None`）。
- 返回元组改为：`return (manga_id, title, ch_info, new_chapters, subscribers, manga_obj), False`

**b) `check_updates`** — 签名增加 `render_update_card_fn: Callable | None = None`（放在 `force: bool = False` 之后）。更新所有 `for manga_id, title, ch_info, new_chapters, subscribers in updated_mangas` 解包为 6 元组。

将推送循环改为：

```python
        user_msgs: dict[str, list[str]] = {}
        user_updates: dict[str, list[dict]] = {}
        for manga_id, title, ch_info, new_chapters, subscribers, manga_obj in updated_mangas:
            latest_num = fmt_chapter_num(new_chapters[-1].chapter_number)
            msg = (
                f"📢「{title}」更新了！\n"
                f"新增章节：{', '.join(ch_info)}\n"
                f"发送「漫画 阅读 {title} {latest_num}」开始阅读"
            )
            item = {
                "title": title,
                "status": manga_obj.status if manga_obj else "UNKNOWN",
                "chapters": ch_info,
                "read_hint": f"「漫画 阅读 {title} {latest_num}」",
                "thumbnail_url": manga_obj.thumbnail_url if manga_obj else None,
            }
            for umo in subscribers:
                user_msgs.setdefault(umo, []).append(msg)
                user_updates.setdefault(umo, []).append(item)

        for umo, msgs in user_msgs.items():
            try:
                if render_update_card_fn is not None:
                    heading = (
                        f"📢「{user_updates[umo][0]['title']}」更新了！"
                        if len(user_updates[umo]) == 1
                        else f"📢 {len(user_updates[umo])} 部漫画更新了"
                    )
                    card_path = await render_update_card_fn(
                        umo, user_updates[umo], heading
                    )
                    if card_path:
                        chain = MessageChain(
                            chain=[Comp.Image.fromFileSystem(card_path)]
                        )
                        await context.send_message(umo, chain)
                        continue
                chain = MessageChain().message("\n---\n".join(msgs))
                await context.send_message(umo, chain)
            except Exception as e:
                logger.warning(
                    f"[{_PLUGIN_NAME}] 推送到 {umo} 失败: {e}"
                )
```

**c) main.py `_build_check_updates_fn`** — 在 `_check` 内（或单独绑定）注入渲染函数：

```python
        async def _render_update_card(umo, items, heading):
            try:
                tmpldata = build_update_card(items, heading)
                tmpldata["items"] = await embed_covers(
                    client, tmpldata["items"],
                    custom_tmp=config.get("temp_dir", "").strip(),
                    retries=config.get("download_retries", 3),
                    concurrency=config.get("download_concurrency", 6),
                )
                return await self._render_card_result(tmpldata)
            except Exception as e:
                logger.warning(f"[{_PLUGIN_NAME}] 更新通知卡片渲染失败: {e}")
                return None
```

并在 `_check` 调用 `_check_updates` 时传入 `render_update_card_fn=_render_update_card`（仅当 `result_cards_enabled` 为真时传入，否则传 `None`）：

```python
        async def _check(force=False):
            render_fn = _render_update_card if self._result_cards_enabled() else None
            return await _check_updates(
                client, self.sub_mgr, context, config,
                self.get_kv_data, self.put_kv_data,
                self._update_lock,
                _push_images, _push_file,
                force=force,
                render_update_card_fn=render_fn,
            )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_updater.py -v`
Expected: PASS（含 3 个新测试）

- [ ] **Step 5: 全量回归**

Run: `uv run pytest -v`
Expected: 全部 PASS

- [ ] **Step 6: 提交**

```bash
git add suwayomi/updater.py main.py tests/test_updater.py
git commit -m "feat: cardify update notifications"
```

---

## Task 11: 文档与手动验收

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `docs/dev/development.md`（架构章节）
- Modify: `docs/dev/doc-update-checklist.md`（若要求）

- [ ] **Step 1: CHANGELOG**

在 `CHANGELOG.md` 顶部 `## Unreleased` 下追加：

```markdown
- 新功能：指令结果卡片化。搜索、订阅确认、批量订阅、我的订阅、更新通知、章节列表通过 T2I 服务渲染为带封面的 440px 卡片；新增 `result_cards_enabled` 与 `card_render_timeout_sec` 配置；关闭或渲染失败自动回退纯文本。
```

- [ ] **Step 2: 全量测试**

Run: `uv run pytest -v`
Expected: 全部 PASS（含 live 测试自动跳过）

- [ ] **Step 3: ruff 格式化**

Run: `uv run ruff check suwayomi/cards.py main.py suwayomi/updater.py utils/pusher.py tests/`
Expected: 无错误（若项目无 ruff 配置，跳过）

- [ ] **Step 4: 手动验收清单（需真实 T2I 端点 + 真实 Suwayomi）**

1. 启动 AstrBot，WebUI 确认两个新配置出现且默认值正确。
2. `/漫画 搜索 咒术回战` → 收到卡片（含封面、编号、状态）。
3. `/漫画 章节 咒术回战` → 收到信息卡 + 章节三列（若 >260 话则多张续卡）。
4. 断网/关闭 T2I 端点 → 上述命令回退纯文本，无报错。
5. `_conf_schema.json` 中 `result_cards_enabled=false` → 全部回退文本。
6. 订阅两部漫画后 `/漫画 更新` → 订阅者收到多部更新卡片。

- [ ] **Step 5: 提交**

```bash
git add CHANGELOG.md docs/dev/development.md docs/dev/doc-update-checklist.md
git commit -m "docs: document result cards feature"
```

---

## Self-Review

**Spec coverage 检查：**
- 6 类卡片：搜索(Task6)、订阅确认(Task7)、批量订阅(Task7)、我的订阅(Task8)、更新通知单/多部(Task10)、章节分块(Task9) ✅
- 失败回退纯文本：`render_card` 返回 None → 命令走文本（Task6-9 均有 fallback）✅
- 全局开关：`result_cards_enabled`（Task4 配置 + `_result_cards_enabled`）✅
- 440px 窄卡：`render_card` options `viewport_width=CARD_WIDTH`（Task3）✅
- 全部封面并发下载：`embed_covers` 复用 `download_images`（Task2）✅
- 占位块：模板 `cover-placeholder` 分支 ✅
- 渲染缓存：`CardCache` TTL 600（Task3/5）✅
- 超时：`card_render_timeout_sec`（Task5）✅
- 更新通知捕获 thumbnail：`_check_one_manga` 透传 manga 对象（Task10）✅
- 配置 schema：Task4 ✅
- `chapter_list_show_cover` 语义：Task9 卡片路径要求该开关为真，否则走旧逻辑 ✅

**占位符扫描：** 无 TBD/TODO；所有步骤含完整代码。

**类型一致性：**
- `build_chapter_cards` 返回 `(list[dict], list[str])` — Task1 定义，Task9 调用一致 ✅
- `embed_covers(client, items, custom_tmp=, retries=, concurrency=) -> list[dict]` — Task2 定义，Task6-10 调用一致 ✅
- `render_card_cached(cache, html_render, tmpldata, options=None, timeout=)` — Task3/5 一致 ✅
- `schedule_cleanup_file(path, delay=)` — Task4 定义，Task5 调用 ✅
- `_render_card_result(tmpldata) -> str|None` — Task5 定义，Task6-9 调用一致 ✅
- `build_update_card(items, heading)` / `build_search_card(rows, subtitle, footer)` / `build_subscribe_confirm_card(manga, source_name, footer)` / `build_batch_card(rows, summary)` / `build_subscriptions_card(rows)` — Task1/8 定义与调用一致 ✅
- updater `check_updates` 6 元组解包 — Task10 改 all loop 解包 ✅
