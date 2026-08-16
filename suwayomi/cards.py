"""Render command results as HTML cards via AstrBot's remote T2I service.

The HTML template is rendered by the remote T2I endpoint (Jinja2 natively),
so this module only prepares data and never renders locally. All pure data
preparation lives here for testability; network work (cover download) is
delegated to utils.downloader via ``embed_covers``.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import html
import json
import math
import re
import time
from typing import TYPE_CHECKING, Any, TypedDict

from astrbot.api import logger

from . import PLUGIN_NAME
from .service import STATUS_EMOJI

if TYPE_CHECKING:
    pass

# 模板按 880 CSS 宽设计（所有尺寸为 440 设计的 2 倍），配合
# device_scale_factor_level=ultra(1.8) 输出约 1584px 物理像素宽，
# 手机 2x/3x 屏上文字与封面保持锐利。
CARD_WIDTH = 880
COVER_WIDTH = 320
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
  body { font-family: "Smiley Sans","LXGW WenKai","Noto Sans CJK SC","HarmonyOS Sans SC","MiSans","PingFang SC","Microsoft YaHei",sans-serif;
         background:#e9ecf3; padding:28px 28px 36px; color:#1a1d29; }
  .title { font-size:34px; font-weight:700; margin-bottom:20px; }
  .title .sub { font-size:24px; color:#8a8f9d; font-weight:400; }
  .card { background:#fff; border-radius:20px; padding:16px 20px; display:flex;
          align-items:center; gap:20px; box-shadow:0 2px 6px rgba(0,0,0,.05); }
  .card + .card { margin-top:16px; }
  .cover { border-radius:10px; object-fit:cover; flex-shrink:0; background:#e4e6ec; }
  .cover-placeholder { display:flex; align-items:center; justify-content:center;
                       color:#b0b5c3; font-size:32px; }
  .badge { min-width:40px; height:40px; border-radius:50%; background:#4f7cff;
           color:#fff; font-size:24px; font-weight:600; display:flex;
           align-items:center; justify-content:center; flex-shrink:0; }
  .mark { min-width:40px; height:40px; border-radius:50%; color:#fff; font-size:24px;
          display:flex; align-items:center; justify-content:center; flex-shrink:0; }
  .mark-ok { background:#3ecf6a; }
  .mark-skip { background:#f2b33d; }
  .mark-fail { background:#ef5350; }
  .body { flex:1; min-width:0; }
  .body .name { font-size:30px; font-weight:600; white-space:nowrap; overflow:hidden;
                text-overflow:ellipsis; }
  .body .meta { font-size:24px; color:#8a8f9d; margin-top:4px; }
  .footer { font-size:24px; color:#8a8f9d; text-align:center; margin-top:20px; }
  .chip { display:inline-block; background:#eef3ff; color:#4f7cff; font-size:24px;
          padding:6px 16px; border-radius:12px; margin:6px 6px 0 0; }
  .manga-card { background:#fff; border-radius:24px; padding:24px; display:flex;
                gap:24px; box-shadow:0 2px 6px rgba(0,0,0,.05); }
  .manga-card + .manga-card { margin-top:16px; }
  .manga-cover { border-radius:12px; object-fit:cover; flex-shrink:0; background:#e4e6ec; }
  .manga-body { flex:1; min-width:0; display:flex; flex-direction:column; }
  .manga-name { font-size:30px; font-weight:700; }
  .status-pill { font-size:20px; padding:2px 12px; border-radius:40px; margin-left:4px;
                 vertical-align:2px; }
  .status-ongoing { background:#eef3ff; color:#4f7cff; }
  .status-completed { background:#eef5ec; color:#3e9c4f; }
  .status-default { background:#f2f3f7; color:#6b7180; }
  .hint { font-size:22px; color:#8a8f9d; margin-top:12px; }
  .hint.pushed { margin-top:auto; padding-top:20px; }
  .cols { display:flex; gap:16px; margin-top:16px; }
  .col { flex:1; background:#fff; border-radius:16px; padding:16px; font-family:"Smiley Sans","LXGW WenKai","Noto Sans CJK SC","Noto Sans Mono CJK SC",Consolas,monospace;
         font-size:24px; color:#3a3f4b; line-height:1.8; overflow:hidden; }
  .row-main { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .row-id { color:#8a8f9d; font-size:20px; line-height:1.5; }
  .mini-head { display:flex; align-items:center; gap:20px; background:#fff; border-radius:20px;
               padding:16px 24px; box-shadow:0 2px 6px rgba(0,0,0,.05); }
  .mini-title { font-size:28px; font-weight:700; }
  .mini-title .cont { font-size:22px; color:#8a8f9d; font-weight:400; }
</style>

<body>
{% if card_type == "search" %}
  <div class="title">🔍 搜索结果 <span class="sub">（{{ subtitle }}）</span></div>
  {% for row in rows %}
  <div class="card">
    <div class="badge">{{ row.index }}</div>
    {% if row.cover_data_url %}
      <img class="cover" style="width:88px;height:120px" src="{{ row.cover_data_url }}">
    {% else %}
      <div class="cover cover-placeholder" style="width:88px;height:120px">?</div>
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
      <img class="manga-cover" style="width:240px;height:336px" src="{{ cover_data_url }}">
    {% else %}
      <div class="manga-cover cover-placeholder" style="width:240px;height:336px">?</div>
    {% endif %}
    <div class="manga-body">
      <div style="font-size:44px;font-weight:700">✅ 订阅成功</div>
      <div style="font-size:32px;font-weight:600;margin-top:12px">{{ title }}</div>
      <div class="meta" style="margin-top:4px">{{ meta }}</div>
      <div style="margin-top:12px"><span class="status-pill {{ status_class }}">{{ status }}</span></div>
      <div class="hint pushed">{{ footer }}</div>
    </div>
  </div>

{% elif card_type == "subscriptions" %}
  <div class="title">📋 你的订阅列表</div>
  {% for row in rows %}
  <div class="card">
    {% if row.cover_data_url %}
      <img class="cover" style="width:88px;height:120px" src="{{ row.cover_data_url }}">
    {% else %}
      <div class="cover cover-placeholder" style="width:88px;height:120px">?</div>
    {% endif %}
    <div class="body">
      <div class="name">{{ row.title }}</div>
      <div class="meta">{{ row.detail }}</div>
    </div>
  </div>
  {% endfor %}

{% elif card_type == "batch" %}
  <div class="title">📚 批量订阅完成 <span class="sub">（{{ summary }}）</span></div>
  {% for row in rows %}
  <div class="card">
    <div class="mark {{ row.mark_class }}">{{ row.icon }}</div>
    {% if row.cover_data_url %}
      <img class="cover" style="width:88px;height:120px" src="{{ row.cover_data_url }}">
    {% else %}
      <div class="cover cover-placeholder" style="width:88px;height:120px">?</div>
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
      <img class="manga-cover" style="width:144px;height:200px" src="{{ item.cover_data_url }}">
    {% else %}
      <div class="manga-cover cover-placeholder" style="width:144px;height:200px">?</div>
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
      <img class="manga-cover" style="width:200px;height:280px" src="{{ cover_data_url }}">
    {% else %}
      <div class="manga-cover cover-placeholder" style="width:200px;height:280px">?</div>
    {% endif %}
    <div class="manga-body">
      <div style="font-size:34px;font-weight:700">{{ title }}</div>
      <div class="meta" style="margin-top:6px">{{ meta }}</div>
      <div style="margin-top:16px">{% for t in tags %}<span class="status-pill {{ t.class }}">{{ t.text }}</span>{% endfor %}</div>
      <div class="hint" style="margin-top:16px">{{ hint }}</div>
    </div>
  </div>
  {% else %}
  <div class="mini-head">
    {% if cover_data_url %}
      <img class="cover" style="width:72px;height:100px" src="{{ cover_data_url }}">
    {% else %}
      <div class="cover cover-placeholder" style="width:72px;height:100px">?</div>
    {% endif %}
    <div class="mini-title">{{ title }} <span class="cont">{{ continuation }}</span></div>
  </div>
  {% endif %}
  {% if chunks %}
  <div class="cols">
    {% for col in chunks %}
    <div class="col">{% for line in col %}<div class="row"><div class="row-main">{{ line.main }}</div>{% if line.id %}<div class="row-id">{{ line.id }}</div>{% endif %}</div>{% endfor %}</div>
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
    """manga: {id, title, status, thumbnail_url}."""
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


_ID_TAG_RE = re.compile(r"\s*\(ID:\d+\)\s*$")

# ID 行渲染两行（标题 43.2px = 24px×1.8 + ID 行 30px = 20px×1.5），
# 与普通单行的行高比 = 73.2 / 43.2 ≈ 1.694，取 1.7。
_ROW_ID_WEIGHT = 1.7

# 章节卡一行：main 为标题（可省略号截断），id 为行尾灰色 ID 标注（可空）。
class CardLine(TypedDict):
    main: str
    id: str


def _row_weight(line: str | CardLine) -> float:
    """Render-height units of a chapter line.

    Rows carrying an ``(ID:xxx)`` tag render on two lines (title + gray ID
    line) and take ~1.7x the height of a plain row; the weight mirrors the
    actual CSS height ratio so chunking/column splitting balances rendered
    height, not line count. Accepts raw line strings or the dict rows
    produced by ``_chapter_row``.
    """
    if isinstance(line, dict):
        return _ROW_ID_WEIGHT if line.get("id") else 1.0
    return _ROW_ID_WEIGHT if _ID_TAG_RE.search(line) else 1.0


def _chunk_by_weight(lines: list[str], budget: int) -> list[list[str]]:
    """Split lines into chunks whose total weight stays within ``budget``."""
    chunks: list[list[str]] = []
    cur: list[str] = []
    weight = 0
    for line in lines:
        w = _row_weight(line)
        if cur and weight + w > budget:
            chunks.append(cur)
            cur, weight = [], 0
        cur.append(line)
        weight += w
    if cur:
        chunks.append(cur)
    return chunks


def _split_columns(lines: list[CardLine], n: int = 3) -> list[list[CardLine]]:
    """Split card lines into n columns preserving reading order and height balance.

    Each column gets a contiguous slice of lines (column 1 first, column 2
    next, ...) so columns read top-to-bottom in the same order as the
    plain-text list. Slicing is weighted by ``_row_weight`` so columns with
    many two-line ID rows do not end up visibly taller than others.
    """
    if not lines:
        return [[] for _ in range(n)]
    total = sum(_row_weight(line) for line in lines)
    target = math.ceil(total / n)
    cols: list[list[CardLine]] = []
    cur: list[CardLine] = []
    weight = 0.0
    for line in lines:
        w = _row_weight(line)
        # 达到或超过目标才切列（而不是"预测下一行会超就切"）：
        # 单行权重大时后者会产出单行孤列，让尾列堆积。
        if cur and weight >= target and len(cols) < n - 1:
            cols.append(cur)
            cur, weight = [], 0.0
        cur.append(line)
        weight += w
    if cur:
        cols.append(cur)
    while len(cols) < n:
        cols.append([])
    return cols


def _chapter_row(line: str) -> CardLine:
    """Split a chapter line into (main, id_tag) for single-line truncation.

    Lines like ``#1 单行本：第01卷 (ID:2539)`` become main ``#1 单行本：第01卷``
    and a fixed ``(ID:2539)`` tag, so the title can be ellipsized without
    ever hiding the ID users need for ``ID:xxx`` disambiguation.
    """
    m = _ID_TAG_RE.search(line)
    if m:
        main = line[: m.start()].strip()
        id_tag = m.group(0).strip()
    else:
        main = line
        id_tag = ""
    return {"main": html.escape(main), "id": html.escape(id_tag)}


def build_chapter_cards(manga: dict, lines: list[str]) -> tuple[list[dict], list[str]]:
    """Split chapter lines into card tmpldata list plus raw tail text lines.

    ``manga`` must already carry ``cover_data_url`` (from ``embed_covers``).
    Chapter ``lines`` are the same strings used for the text fallback (raw,
    NOT escaped); this function HTML-escapes the ones placed into cards and
    returns the unescaped overflow as ``tail``.
    """
    safe_lines: list[CardLine] = [_chapter_row(line) for line in lines]
    per_card = CHAPTER_LINES_PER_CARD
    if not lines:
        card_count = 1
        chunks_by_weight = [[]]
        tail: list[str] = []
    else:
        chunks_by_weight = _chunk_by_weight(lines, per_card)
        card_count = min(MAX_CHAPTER_CARDS, len(chunks_by_weight))
        tail = lines[sum(len(c) for c in chunks_by_weight[:card_count]):]

    tags = []
    for t in manga.get("tags", []):
        if isinstance(t, str):
            tags.append({"text": html.escape(t), "class": "status-default"})
        else:
            tags.append({"text": html.escape(t["text"]), "class": t.get("class", "status-default")})
    base = {
        "card_type": "chapter",
        "cover_data_url": manga.get("cover_data_url"),
        "title": html.escape(manga["title"]),
    }
    cards = []
    offset = 0
    for i in range(card_count):
        chunk = chunks_by_weight[i]
        card_lines = safe_lines[offset:offset + len(chunk)]
        offset += len(chunk)
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


def resolve_cover_url(client: Any, thumbnail_url: str | None) -> tuple[str | None, dict | None]:
    """Resolve a Suwayomi thumbnail URL plus auth headers for cover download.

    Thin wrapper over ``utils.downloader.resolve_image_url`` (the single
    source of truth for same-origin auth policy, shared with download_cover).
    """
    from ..utils.downloader import resolve_image_url

    return resolve_image_url(client, thumbnail_url, client.auth_headers)


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
    except Exception as exc:
        logger.warning(f"[{_PLUGIN_NAME}] 封面压缩失败（将显示占位块）: {path}: {exc}")
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

    covers: dict[int, str | None] = {}
    grouped: dict[tuple, list[tuple[int, str]]] = {}
    for idx, (_item, url, use_headers) in enumerate(resolved):
        if url is None:
            covers[idx] = None
            continue
        key = tuple(sorted((use_headers or {}).items()))
        grouped.setdefault(key, []).append((idx, url))

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
    opts = {
        "type": "jpeg",
        "quality": 95,
        "viewport_width": CARD_WIDTH,
        # 视口高度必须小于内容高度：服务端 scrollHeight = max(内容, 视口高)，
        # full_page 截图按 scrollHeight 输出，默认 720 会让矮卡片底部大片空白。
        "viewport_height": 100,
        # 880px 视口 × 1.8 设备像素比 → 约 1584px 物理像素输出，
        # 保证手机 2x/3x 屏上文字锐利（服务端默认 1.0x 会糊）
        "device_scale_factor_level": "ultra",
    }
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
