"""Tests for suwayomi/t2i.py — standalone astrbot-t2i-service client (no network)."""
from pathlib import Path

import pytest
from plugin_pkg.suwayomi import t2i
from plugin_pkg.suwayomi.cards import render_card
from plugin_pkg.suwayomi.t2i import make_endpoint_renderer, normalize_endpoint


class _FakeResponse:
    def __init__(self, status, body, content_type="image/jpeg"):
        self.status = status
        self._body = body
        self.headers = {"Content-Type": content_type}

    async def read(self):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    def __init__(self, response, captured):
        self._response = response
        self._captured = captured

    def post(self, url, json=None, timeout=None):
        self._captured["url"] = url
        self._captured["payload"] = json
        self._captured["timeout"] = timeout
        return self._response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _patch_session(monkeypatch, response, captured):
    def factory(**kwargs):
        captured["session_kwargs"] = kwargs
        return _FakeSession(response, captured)

    monkeypatch.setattr(t2i.aiohttp, "ClientSession", factory)


def _rm(path):
    Path(path).unlink(missing_ok=True)


# ── normalize_endpoint ──────────────────────────────────────────────

def test_normalize_endpoint_appends_text2img():
    assert normalize_endpoint("http://host:8999") == "http://host:8999/text2img"


def test_normalize_endpoint_keeps_existing_path():
    assert normalize_endpoint("http://host:8999/text2img") == "http://host:8999/text2img"


def test_normalize_endpoint_strips_trailing_slash():
    assert normalize_endpoint("http://host:8999/") == "http://host:8999/text2img"
    assert normalize_endpoint("http://host:8999/text2img/") == "http://host:8999/text2img"


def test_normalize_endpoint_strips_generate_suffix():
    assert (
        normalize_endpoint("http://host:8999/text2img/generate")
        == "http://host:8999/text2img"
    )


def test_normalize_endpoint_empty():
    assert normalize_endpoint("") == ""
    assert normalize_endpoint("   ") == ""


# ── render_custom_template ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_render_custom_template_posts_and_writes_image(monkeypatch):
    captured = {}
    _patch_session(monkeypatch, _FakeResponse(200, b"\xff\xd8image"), captured)

    path = await t2i.render_custom_template(
        "http://host:8999",
        "<html>{{ t }}</html>",
        {"t": "x"},
        options={"type": "jpeg", "quality": 95},
        timeout=12.0,
    )

    assert captured["url"] == "http://host:8999/text2img/generate"
    payload = captured["payload"]
    assert payload["tmpl"] == "<html>{{ t }}</html>"
    assert payload["tmpldata"] == {"t": "x"}
    assert payload["json"] is False
    assert payload["options"] == {"type": "jpeg", "quality": 95}
    assert Path(path).suffix == ".jpg"
    assert Path(path).read_bytes() == b"\xff\xd8image"
    _rm(path)


@pytest.mark.asyncio
async def test_render_custom_template_uses_png_suffix_per_content_type(monkeypatch):
    captured = {}
    _patch_session(
        monkeypatch,
        _FakeResponse(200, b"\x89PNG", content_type="image/png"),
        captured,
    )

    path = await t2i.render_custom_template("http://host:8999", "t", {})

    assert Path(path).suffix == ".png"
    _rm(path)


@pytest.mark.asyncio
async def test_render_custom_template_raises_on_http_error(monkeypatch):
    captured = {}
    _patch_session(monkeypatch, _FakeResponse(500, b"boom"), captured)

    with pytest.raises(RuntimeError):
        await t2i.render_custom_template("http://host:8999", "t", {})


@pytest.mark.asyncio
async def test_render_custom_template_raises_on_empty_body(monkeypatch):
    captured = {}
    _patch_session(monkeypatch, _FakeResponse(200, b""), captured)

    with pytest.raises(RuntimeError):
        await t2i.render_custom_template("http://host:8999", "t", {})


@pytest.mark.asyncio
async def test_render_custom_template_rejects_empty_endpoint(monkeypatch):
    captured = {}
    _patch_session(monkeypatch, _FakeResponse(200, b"x"), captured)

    with pytest.raises(ValueError):
        await t2i.render_custom_template("", "t", {})

    assert "url" not in captured


# ── make_endpoint_renderer ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_make_endpoint_renderer_drives_render_card(monkeypatch):
    captured = {}
    _patch_session(monkeypatch, _FakeResponse(200, b"IMG"), captured)

    path = await render_card(
        make_endpoint_renderer("http://host:8999"),
        {"card_type": "search"},
        timeout=10,
    )

    assert path is not None
    assert captured["url"] == "http://host:8999/text2img/generate"
    # render_card 的高清渲染选项必须原样转发给独立端点
    assert captured["payload"]["options"]["viewport_width"] == 880
    assert captured["payload"]["options"]["device_scale_factor_level"] == "ultra"
    _rm(path)
