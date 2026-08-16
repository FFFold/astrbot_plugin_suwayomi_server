"""Tests for utils/downloader.py (no network)."""
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from plugin_pkg.suwayomi.client import SuwayomiClient
from plugin_pkg.utils.downloader import download_cover, download_images, download_one


@pytest.mark.asyncio
async def test_download_images_creates_missing_custom_tmp(tmp_path, monkeypatch):
    target = tmp_path / "nested" / "tmp"

    async def fake_download_one(session, url, dest, retries=3):
        dest.write_bytes(b"x")
        return True

    monkeypatch.setattr("plugin_pkg.utils.downloader.download_one", fake_download_one)

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

    monkeypatch.setattr("plugin_pkg.utils.downloader.download_one", failing)

    paths, tmp_dir = await download_images(
        ["http://x/1", "http://x/2"],
        custom_tmp=str(tmp_path),
    )

    assert paths == ["", ""]


@pytest.mark.asyncio
async def test_download_one_retries_then_succeeds(tmp_path):
    responses = [500, 200]

    class Resp:
        def __init__(self, status):
            self.status = status
            self.headers = {"Content-Type": "image/jpeg"}

        async def read(self):
            return b"data"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    def fake_get(url, timeout=None):
        return Resp(responses.pop(0))

    session = AsyncMock()
    session.get = fake_get

    ok = await download_one(session, "http://x/1", tmp_path / "img", retries=2)

    assert ok is True
    assert (tmp_path / "img.jpg").exists()


@pytest.mark.asyncio
async def test_download_cover_returns_none_when_no_thumbnail(monkeypatch):
    client = SuwayomiClient("http://localhost:4567", "none", "", "")

    async def unexpected(*args, **kwargs):
        raise AssertionError("download_images should not be called")

    monkeypatch.setattr("plugin_pkg.utils.downloader.download_images", unexpected)

    path, tmp_dir = await download_cover(client, None)

    assert path is None
    assert tmp_dir is None


@pytest.mark.asyncio
async def test_download_cover_success_with_relative_url(tmp_path, monkeypatch):
    client = SuwayomiClient("http://localhost:4567", "basic", "admin", "pass")
    cover_tmp = tmp_path / "cover"
    cover_tmp.mkdir()
    cover_file = cover_tmp / "0000.jpg"
    cover_file.write_bytes(b"cover")
    captured = {}

    async def fake_download_images(urls, **kwargs):
        captured["urls"] = urls
        captured["headers"] = kwargs.get("headers")
        return [str(cover_file)], cover_tmp

    monkeypatch.setattr("plugin_pkg.utils.downloader.download_images", fake_download_images)

    path, tmp_dir = await download_cover(
        client,
        "/api/v1/manga/1/thumbnail",
        headers={"Authorization": "Basic xyz"},
    )

    assert path == str(cover_file)
    assert tmp_dir == cover_tmp
    assert captured["urls"] == ["http://localhost:4567/api/v1/manga/1/thumbnail"]
    assert captured["headers"] == {"Authorization": "Basic xyz"}


@pytest.mark.asyncio
async def test_download_cover_failure_cleans_tmp_dir(tmp_path, monkeypatch):
    client = SuwayomiClient("http://localhost:4567", "none", "", "")
    cover_tmp = tmp_path / "cover"
    cover_tmp.mkdir()

    async def fake_download_images(urls, **kwargs):
        return [""], cover_tmp

    monkeypatch.setattr("plugin_pkg.utils.downloader.download_images", fake_download_images)

    path, tmp_dir = await download_cover(client, "/api/v1/manga/1/thumbnail")

    assert path is None
    assert tmp_dir is None
    assert not cover_tmp.exists()


@pytest.mark.asyncio
async def test_download_cover_external_url_does_not_forward_auth(tmp_path, monkeypatch):
    client = SuwayomiClient("http://localhost:4567", "basic", "admin", "pass")
    cover_tmp = tmp_path / "cover"
    cover_tmp.mkdir()
    cover_file = cover_tmp / "0000.jpg"
    cover_file.write_bytes(b"cover")
    captured = {}

    async def fake_download_images(urls, **kwargs):
        captured["headers"] = kwargs.get("headers")
        return [str(cover_file)], cover_tmp

    monkeypatch.setattr("plugin_pkg.utils.downloader.download_images", fake_download_images)

    await download_cover(
        client,
        "https://cdn.example.com/cover.jpg",
        headers={"Authorization": "Basic xyz"},
    )

    assert captured["headers"] is None


@pytest.mark.asyncio
async def test_download_cover_same_origin_absolute_keeps_auth(tmp_path, monkeypatch):
    client = SuwayomiClient("http://localhost:4567", "basic", "admin", "pass")
    cover_tmp = tmp_path / "cover"
    cover_tmp.mkdir()
    cover_file = cover_tmp / "0000.jpg"
    cover_file.write_bytes(b"cover")
    captured = {}

    async def fake_download_images(urls, **kwargs):
        captured["headers"] = kwargs.get("headers")
        return [str(cover_file)], cover_tmp

    monkeypatch.setattr("plugin_pkg.utils.downloader.download_images", fake_download_images)

    await download_cover(
        client,
        "http://localhost:4567/api/v1/manga/1/thumbnail",
        headers={"Authorization": "Basic xyz"},
    )

    assert captured["headers"] == {"Authorization": "Basic xyz"}


@pytest.mark.asyncio
async def test_download_cover_swallows_download_exception(tmp_path, monkeypatch):
    client = SuwayomiClient("http://localhost:4567", "none", "", "")

    async def boom(*args, **kwargs):
        raise OSError("boom")

    monkeypatch.setattr("plugin_pkg.utils.downloader.download_images", boom)

    path, tmp_dir = await download_cover(client, "/api/v1/manga/1/thumbnail")

    assert path is None
    assert tmp_dir is None
