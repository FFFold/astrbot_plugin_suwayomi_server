"""Standalone T2I rendering against a self-hosted astrbot-t2i-service.

Mirrors the subset of AstrBot's core network render strategy that the card
renderer needs: POST the Jinja2 template to ``{base}/text2img/generate`` and
save the returned image bytes to a temp file. Used only when the plugin is
configured with ``t2i_source = "custom"``; otherwise cards go through
AstrBot's built-in ``Star.html_render``.
"""
from __future__ import annotations

import tempfile
from collections.abc import Awaitable, Callable
from urllib.parse import urlparse

import aiohttp

# Backstop only: the governing timeout is the caller's
# ``card_render_timeout_sec`` (clamped to 120s in main.py), applied via
# ``asyncio.wait_for`` in cards.render_card. This value must stay above that
# clamp so it never preempts the user's setting.
_GENERATE_TIMEOUT = 130.0


def normalize_endpoint(endpoint: object) -> str:
    """Normalize a service address to its base URL ending in ``/text2img``.

    Mirrors AstrBot core's URL rule so users may enter either
    ``http://host:8999`` or ``http://host:8999/text2img`` (and tolerate a
    pasted ``/generate`` or trailing slash).

    Non-string input (hand-edited config, misbehaving API client) is rejected
    as empty rather than raising, so card rendering degrades to the system
    renderer instead of failing the command.
    """
    if not isinstance(endpoint, str):
        return ""
    url = endpoint.strip().rstrip("/")
    if not url:
        return ""
    if url.endswith("/generate"):
        url = url[: -len("/generate")]
    # Only a real ``/text2img`` path component counts as already normalized —
    # a bare ``endswith`` would misjudge hosts like ``/nottext2img``.
    if urlparse(url).path.rsplit("/", 1)[-1] != "text2img":
        url += "/text2img"
    return url


async def render_custom_template(
    endpoint: str,
    tmpl: str,
    tmpldata: dict,
    options: dict | None = None,
    timeout: float = _GENERATE_TIMEOUT,
) -> str:
    """Render ``tmpl`` on the standalone T2I service and return a local image path.

    Raises ``ValueError`` for an empty endpoint and ``RuntimeError`` for a
    non-200 response or an empty body, so ``cards.render_card`` can fall back
    to plain text.
    """
    base = normalize_endpoint(endpoint)
    if not base:
        raise ValueError("T2I 端点为空")

    payload = {
        "tmpl": tmpl,
        "tmpldata": tmpldata,
        "options": options or {},
        "json": False,
    }

    async with (
        aiohttp.ClientSession(
            trust_env=True, timeout=aiohttp.ClientTimeout(total=timeout)
        ) as session,
        session.post(f"{base}/generate", json=payload) as resp,
    ):
        if resp.status != 200:
            raise RuntimeError(f"T2I 服务返回 HTTP {resp.status}")
        content_type = resp.headers.get("Content-Type", "")
        data = await resp.read()

    if not data:
        raise RuntimeError("T2I 服务返回空响应")

    suffix = ".png" if "png" in content_type else ".jpg"
    with tempfile.NamedTemporaryFile(
        prefix="suwayomi_card_", suffix=suffix, delete=False
    ) as fh:
        fh.write(data)
        return fh.name


def make_endpoint_renderer(
    endpoint: str, timeout: float = _GENERATE_TIMEOUT
) -> Callable[..., Awaitable[str]]:
    """Return an ``html_render``-compatible callable bound to ``endpoint``."""

    async def _render(
        tmpl: str,
        data: dict,
        return_url: bool = False,
        options: dict | None = None,
    ) -> str:
        if return_url:
            raise NotImplementedError("独立 T2I 端点仅支持返回本地文件")
        return await render_custom_template(
            endpoint, tmpl, data, options=options, timeout=timeout
        )

    return _render
