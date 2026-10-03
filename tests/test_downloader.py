"""Tests for utils/downloader.py (no network)."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from plugin_pkg.suwayomi.client import SuwayomiClient
from plugin_pkg.utils.downloader import (
    download_cover,
    download_images,
    download_one,
    get_file_delivery_max_pages,
    resolve_image_url,
)


@pytest.mark.asyncio
async def test_download_images_creates_missing_custom_tmp(tmp_path, monkeypatch):
    target = tmp_path / "nested" / "tmp"

    async def fake_download_one(session, url, dest, retries=3, headers=None):
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
    async def failing(session, url, dest, retries=3, headers=None):
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
            self.content = self  # download_one 以 iter_chunked 流式读取

        async def read(self):
            return b"data"

        async def iter_chunked(self, n):
            yield b"data"

        async def release(self):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    async def fake_get(url, timeout=None, allow_redirects=True, headers=None):
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
async def test_download_cover_absolute_url_without_server_url_does_not_forward_headers(tmp_path, monkeypatch):
    client = SuwayomiClient("", "none", "", "")
    cover_tmp = tmp_path / "cover"
    cover_tmp.mkdir()
    cover_file = cover_tmp / "0000.jpg"
    cover_file.write_bytes(b"cover")
    captured = {}

    async def fake_download_images(urls, **kwargs):
        captured["headers"] = kwargs.get("headers")
        return [str(cover_file)], cover_tmp

    monkeypatch.setattr("plugin_pkg.utils.downloader.download_images", fake_download_images)

    path, tmp_dir = await download_cover(
        client,
        "https://example.com/cover.jpg",
        headers={"Authorization": "Basic xyz"},
    )

    assert path == str(cover_file)
    assert tmp_dir == cover_tmp
    assert captured["headers"] is None


@pytest.mark.asyncio
async def test_download_cover_swallows_download_exception(tmp_path, monkeypatch):
    client = SuwayomiClient("http://localhost:4567", "none", "", "")

    async def boom(*args, **kwargs):
        raise OSError("boom")

    monkeypatch.setattr("plugin_pkg.utils.downloader.download_images", boom)

    path, tmp_dir = await download_cover(client, "/api/v1/manga/1/thumbnail")

    assert path is None
    assert tmp_dir is None


class TestResolveImageUrlSsrfGuard:
    """第三方绝对封面地址指向私网/环回 → 拒绝下载（防 SSRF）。"""

    def _client(self, url="http://localhost:4567"):
        return SuwayomiClient(url, "none", "", "")

    def test_rejects_metadata_service_ip(self):
        url, headers = resolve_image_url(
            self._client(), "http://169.254.169.254/latest/meta-data", {"Authorization": "Bearer x"}
        )
        assert url is None and headers is None

    def test_rejects_private_lan_ip(self):
        url, headers = resolve_image_url(
            self._client(), "http://10.0.0.5:8080/cover.jpg", {"Authorization": "Bearer x"}
        )
        assert url is None and headers is None

    def test_rejects_localhost_hostname(self):
        url, headers = resolve_image_url(
            self._client(), "http://localhost:9999/cover.jpg", {"Authorization": "Bearer x"}
        )
        assert url is None and headers is None

    def test_allows_same_server_private_address_with_auth(self):
        client = self._client("http://192.168.1.5:4567")
        auth = {"Authorization": "Bearer x"}
        url, headers = resolve_image_url(
            client, "http://192.168.1.5:4567/api/v1/manga/1/thumbnail", auth
        )
        # Suwayomi 本机部署在内网是常态：同源私网地址必须放行并携带凭据
        assert url is not None and headers is auth

    def test_allows_public_absolute_url_without_auth(self):
        url, headers = resolve_image_url(
            self._client(), "https://cdn.example.com/cover.jpg", {"Authorization": "Bearer x"}
        )
        assert url == "https://cdn.example.com/cover.jpg"
        assert headers is None


class _FakeResp:
    def __init__(self, status, headers=None, peer=None):
        self.status = status
        self.headers = headers if headers is not None else {
            "Content-Type": "image/jpeg"
        }
        self.content = self
        if peer is not None:
            transport = SimpleNamespace(get_extra_info=lambda key: peer)
            self.connection = SimpleNamespace(transport=transport)

    async def iter_chunked(self, n):
        yield b"data"

    async def release(self):
        pass

    def close(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def _session_routing(routes: dict):
    """session.get 按 URL 精确路由到预置响应；calls 记录 (url, headers)。"""
    calls: list[tuple[str, dict | None]] = []

    async def get(url, timeout=None, allow_redirects=True, headers=None):
        calls.append((url, headers))
        assert allow_redirects is False, "must disable auto redirects"
        return routes[url]

    session = AsyncMock()
    session.get = get
    return session, calls


class TestSsrfRedirectGuard:
    """PR #21 评审：aiohttp 自动跟随重定向会绕过私网地址过滤，须逐跳校验。"""

    @pytest.mark.asyncio
    async def test_redirect_to_private_host_refused(self, tmp_path):
        session, calls = _session_routing({
            "https://cdn.example.com/cover.jpg": _FakeResp(302, {
                "Content-Type": "text/plain", "Location": "http://127.0.0.1/evil"
            }),
        })
        ok = await download_one(
            session, "https://cdn.example.com/cover.jpg", tmp_path / "img"
        )
        assert ok is False
        # 私网目标被拒：只发出了首个请求，从未向 127.0.0.1 发起连接
        assert [c[0] for c in calls] == ["https://cdn.example.com/cover.jpg"]

    @pytest.mark.asyncio
    async def test_redirect_to_same_origin_private_allowed(self, tmp_path):
        # 初始 URL 即同服务器私网（Suwayomi 内网部署常态）：跳回自身 origin 放行
        session, calls = _session_routing({
            "http://192.168.1.5:4567/api/v1/manga/1/thumbnail": _FakeResp(302, {
                "Content-Type": "text/plain",
                "Location": "http://192.168.1.5:4567/api/v1/manga/1/thumbnail/v2",
            }),
            "http://192.168.1.5:4567/api/v1/manga/1/thumbnail/v2": _FakeResp(200),
        })
        ok = await download_one(
            session,
            "http://192.168.1.5:4567/api/v1/manga/1/thumbnail",
            tmp_path / "img",
        )
        assert ok is True and len(calls) == 2

    @pytest.mark.asyncio
    async def test_redirect_to_public_host_followed(self, tmp_path):
        session, calls = _session_routing({
            "https://cdn.example.com/cover.jpg": _FakeResp(302, {
                "Content-Type": "text/plain", "Location": "https://img.example.net/c.png"
            }),
            "https://img.example.net/c.png": _FakeResp(200),
        })
        ok = await download_one(
            session, "https://cdn.example.com/cover.jpg", tmp_path / "img"
        )
        assert ok is True and len(calls) == 2

    @pytest.mark.asyncio
    async def test_relative_location_resolved_against_current_url(self, tmp_path):
        session, calls = _session_routing({
            "https://cdn.example.com/a/cover.jpg": _FakeResp(302, {
                "Content-Type": "text/plain", "Location": "../b/real.png"
            }),
            "https://cdn.example.com/b/real.png": _FakeResp(200),
        })
        ok = await download_one(
            session, "https://cdn.example.com/a/cover.jpg", tmp_path / "img"
        )
        assert ok is True
        assert calls[-1][0] == "https://cdn.example.com/b/real.png"


class TestSsrfHostCanonicalization:
    """PR #21 复审：非规范主机写法（尾点/数字 IP 变体）不得绕过私网过滤。"""

    def test_rejects_localhost_trailing_dot(self):
        url, headers = resolve_image_url(
            SuwayomiClient("http://localhost:4567", "none", "", ""),
            "http://localhost.:9999/cover.jpg",
            {"Authorization": "Bearer x"},
        )
        assert url is None and headers is None

    def test_rejects_non_canonical_ipv4_literals(self):
        client = SuwayomiClient("http://localhost:4567", "none", "", "")
        for target in (
            "http://2130706433/cover.jpg",
            "http://0x7f.1/cover.jpg",
            "http://0177.0.0.1/cover.jpg",
            "http://127.1/cover.jpg",
        ):
            url, headers = resolve_image_url(
                client, target, {"Authorization": "Bearer x"}
            )
            assert url is None and headers is None, target

    def test_private_host_detection_covers_encodings(self):
        from plugin_pkg.utils.downloader import _is_private_host

        for host in ("localhost.", "2130706433", "0x7f.1", "0177.0.0.1", "127.1"):
            assert _is_private_host(host) is True, host

    def test_domain_like_hosts_not_flagged(self):
        from plugin_pkg.utils.downloader import _is_private_host

        for host in ("example.com", "123.com", "cafe.com", None, ""):
            assert _is_private_host(host) is False, host

    @pytest.mark.asyncio
    async def test_redirect_to_non_canonical_private_ip_refused(self, tmp_path):
        session, calls = _session_routing({
            "https://cdn.example.com/cover.jpg": _FakeResp(302, {
                "Content-Type": "text/plain", "Location": "http://2130706433/evil"
            }),
        })
        ok = await download_one(
            session, "https://cdn.example.com/cover.jpg", tmp_path / "img"
        )
        assert ok is False
        assert [c[0] for c in calls] == ["https://cdn.example.com/cover.jpg"]


class TestSsrfPeerGuard:
    """PR #21 复审：跨源跳转连接建立后复核对端 IP（防 DNS rebinding/编码绕过）。"""

    @pytest.mark.asyncio
    async def test_cross_origin_redirect_peer_private_refused(self, tmp_path):
        session, calls = _session_routing({
            "https://cdn.example.com/cover.jpg": _FakeResp(302, {
                "Content-Type": "text/plain",
                "Location": "https://img.example.net/c.png",
            }),
            "https://img.example.net/c.png": _FakeResp(200, peer=("127.0.0.1", 443)),
        })
        ok = await download_one(
            session, "https://cdn.example.com/cover.jpg", tmp_path / "img"
        )
        assert ok is False
        assert len(calls) == 2  # 连接已被复检拦下，响应不落盘
        assert not (tmp_path / "img.jpg").exists()

    @pytest.mark.asyncio
    async def test_same_origin_private_peer_allowed(self, tmp_path):
        # Suwayomi 内网部署常态：同源私网对端必须放行
        session, calls = _session_routing({
            "http://192.168.1.5:4567/api/v1/manga/1/thumbnail": _FakeResp(
                200, peer=("192.168.1.5", 4567)
            ),
        })
        ok = await download_one(
            session,
            "http://192.168.1.5:4567/api/v1/manga/1/thumbnail",
            tmp_path / "img",
        )
        assert ok is True


class TestRedirectHeaderHygiene:
    """PR #21 复审：跨 origin 跳转须丢弃认证头（aiohttp 自动重定向语义）。"""

    @pytest.mark.asyncio
    async def test_cross_origin_redirect_drops_auth_headers(self, tmp_path):
        session, calls = _session_routing({
            "https://cdn.example.com/cover.jpg": _FakeResp(302, {
                "Content-Type": "text/plain",
                "Location": "https://img.example.net/c.png",
            }),
            "https://img.example.net/c.png": _FakeResp(200),
        })
        ok = await download_one(
            session, "https://cdn.example.com/cover.jpg", tmp_path / "img",
            headers={"Authorization": "Bearer secret"},
        )
        assert ok is True
        assert (calls[0][1] or {}).get("Authorization") == "Bearer secret"
        assert not (calls[1][1] or {}).get("Authorization")

    @pytest.mark.asyncio
    async def test_same_origin_redirect_keeps_auth_headers(self, tmp_path):
        session, calls = _session_routing({
            "http://192.168.1.5:4567/a/cover.jpg": _FakeResp(302, {
                "Content-Type": "text/plain",
                "Location": "http://192.168.1.5:4567/b/cover.jpg",
            }),
            "http://192.168.1.5:4567/b/cover.jpg": _FakeResp(200),
        })
        ok = await download_one(
            session, "http://192.168.1.5:4567/a/cover.jpg", tmp_path / "img",
            headers={"Authorization": "Basic abc"},
        )
        assert ok is True
        assert (calls[1][1] or {}).get("Authorization") == "Basic abc"


class TestFileDeliveryMaxPages:
    """PR #21 评审：整卷/合集章节页数可合法超过默认值，上限须用户可调。"""

    def test_default_when_missing(self):
        assert get_file_delivery_max_pages({}) == 300
        assert get_file_delivery_max_pages(None) == 300

    def test_configured_value_used(self):
        assert get_file_delivery_max_pages(
            {"file_delivery_max_pages": 500}
        ) == 500

    def test_invalid_values_fall_back(self):
        assert get_file_delivery_max_pages({"file_delivery_max_pages": "abc"}) == 300
        assert get_file_delivery_max_pages({"file_delivery_max_pages": None}) == 300

    def test_non_positive_clamped_to_one(self):
        assert get_file_delivery_max_pages({"file_delivery_max_pages": 0}) == 1
        assert get_file_delivery_max_pages({"file_delivery_max_pages": -5}) == 1
