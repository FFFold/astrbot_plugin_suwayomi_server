"""Tests for utils/downloader.py (no network)."""
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from astrbot_suwayomi_server.utils.downloader import download_images, download_one


@pytest.mark.asyncio
async def test_download_images_creates_missing_custom_tmp(tmp_path, monkeypatch):
    target = tmp_path / "nested" / "tmp"

    async def fake_download_one(session, url, dest, retries=3):
        dest.write_bytes(b"x")
        return True

    monkeypatch.setattr("astrbot_suwayomi_server.utils.downloader.download_one", fake_download_one)

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

    monkeypatch.setattr("astrbot_suwayomi_server.utils.downloader.download_one", failing)

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
