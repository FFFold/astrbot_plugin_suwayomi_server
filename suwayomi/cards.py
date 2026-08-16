"""Render command results as HTML cards via AstrBot's remote T2I service.

The HTML template is rendered by the remote T2I endpoint (Jinja2 natively),
so this module only prepares data and never renders locally. All pure data
preparation lives here for testability; network work (cover download) is
delegated to utils.downloader via ``embed_covers``.
"""
from __future__ import annotations

import base64
import html
import math
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from astrbot.api import logger

from . import PLUGIN_NAME
from .service import STATUS_EMOJI

if TYPE_CHECKING:
    from .client import SuwayomiClient

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
