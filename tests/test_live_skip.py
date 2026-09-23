"""Tests for the live-server probe helper (offline, uses a local HTTP server)."""
import pytest
import pytest_asyncio
from aiohttp import web

from tests.helpers import server_reachable, t2i_reachable


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


@pytest_asyncio.fixture
async def local_t2i_server():
    """Minimal stand-in for astrbot-t2i-service: answers /text2img/generate."""
    app = web.Application()

    async def handler(request):
        return web.Response(body=b"\x89PNG", content_type="image/png")

    app.router.add_post("/text2img/generate", handler)
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


@pytest.mark.asyncio
async def test_t2i_reachable_true_with_bare_host(local_t2i_server):
    """A bare host:port (no /text2img) must still probe /text2img/generate."""
    assert await t2i_reachable(local_t2i_server) is True


@pytest.mark.asyncio
async def test_t2i_reachable_false_on_unreachable_port():
    assert await t2i_reachable("http://127.0.0.1:1", timeout=1.0) is False


@pytest.mark.asyncio
async def test_t2i_reachable_false_on_empty_endpoint():
    assert await t2i_reachable("") is False
